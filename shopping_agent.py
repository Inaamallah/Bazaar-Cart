from __future__ import annotations

import os
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq


DB_PATH = Path(__file__).with_name("shopping_agent.db")
COMPETITOR_FALLBACK = "I can only provide information about our exclusive catalog. How else can I help you shop today?"
RESTRICTED_COMPETITORS = ("Amazon", "eBay", "Walmart")
SYSTEM_PROMPT = (
    "You are a shopping assistant for our e-commerce store only. "
    "Strictly refuse to discuss anything outside our store, including politics, "
    "coding advice, general trivia, news, entertainment, education, health, "
    "finance, or competitor shopping sites. If the customer asks an off-topic "
    "question, politely refuse in one short sentence and immediately pivot back "
    "to helping them shop our exclusive catalog. "
    "Use search_products to find items. "
    "Use get_checkout when the customer asks to add an item to cart, "
    "checkout, buy, order, or purchase. If the customer says add to cart, "
    "use action='add_to_cart'. If they say buy, order, checkout, or "
    "purchase, use action='purchase'. Ask for missing details only when "
    "they are required. Do not output raw HTML tags; format product details "
    "with plain Markdown tables or bullet lists."
)
STOP_WORDS = {
    "a",
    "an",
    "and",
    "below",
    "buy",
    "find",
    "for",
    "less",
    "me",
    "show",
    "than",
    "the",
    "to",
    "under",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _price_ceiling(query: str) -> float | None:
    match = re.search(r"(?:under|below|less than)\s*\$?\s*(\d+(?:\.\d+)?)", query.lower())
    return float(match.group(1)) if match else None


def _search_products(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    limit = max(1, min(limit, 50))
    query_lower = query.lower()
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", query_lower)
        if token not in STOP_WORDS and not token.isdigit()
    ]
    max_price = _price_ceiling(query)

    sql = """
        SELECT
            id,
            sku,
            name,
            brand,
            category,
            description,
            price,
            stock_quantity,
            average_rating,
            review_count,
            condition,
            status
        FROM products
        WHERE status = 'active'
    """

    with closing(_connect()) as conn:
        rows = conn.execute(sql).fetchall()

    scored_products = []
    for row in rows:
        product = dict(row)
        if max_price is not None and float(product["price"]) > max_price:
            continue

        haystack = " ".join(
            str(product[field] or "")
            for field in ("sku", "name", "brand", "category", "description")
        ).lower()

        score = 0
        if query_lower in haystack:
            score += 20
        if str(product["name"]).lower().startswith(query_lower):
            score += 15

        token_hits = sum(1 for token in tokens if token in haystack)
        score += token_hits * 5

        if tokens and token_hits == 0:
            continue
        if not tokens and query_lower not in haystack:
            continue

        scored_products.append((score, product))

    scored_products.sort(
        key=lambda item: (
            -item[0],
            -float(item[1]["average_rating"]),
            -int(item[1]["review_count"]),
            float(item[1]["price"]),
        )
    )
    return [product for _, product in scored_products[:limit]]


def _next_order_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM orders").fetchone()
    return int(row["next_id"])


def _guard_final_response(content: str) -> str:
    if any(re.search(rf"\b{re.escape(name)}\b", content, re.IGNORECASE) for name in RESTRICTED_COMPETITORS):
        return COMPETITOR_FALLBACK
    return content


def _checkout(
    customer_name: str,
    product_query: str,
    quantity: int = 1,
    action: Literal["add_to_cart", "purchase"] = "add_to_cart",
    shipping_address: str = "",
) -> dict[str, Any] | str:
    customer_name = customer_name.strip() or "guest"
    product_query = product_query.strip()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    if quantity > 5:
        return json.dumps(
            {
                "success": False,
                "error": "bulk_order_limit",
                "message": "Bulk orders are limited to 5 units per checkout. Please reduce the quantity to 5 or fewer.",
                "max_quantity": 5,
            }
        )

    if action == "purchase" and not shipping_address.strip():
        return json.dumps(
            {
                "success": False,
                "error": "shipping_address_required",
                "message": "A shipping address is required before completing a purchase.",
            }
        )

    if not product_query:
        return {"success": False, "message": "Please provide a product query."}

    matches = _search_products(product_query, limit=1)
    if not matches:
        return {
            "success": False,
            "message": f"No active product matched '{product_query}'.",
            "order": None,
        }

    product = matches[0]
    product_id = int(product["id"])
    stock_quantity = int(product["stock_quantity"])
    unit_price = float(product["price"])
    total_price = round(unit_price * quantity, 2)

    if stock_quantity < quantity:
        return {
            "success": False,
            "message": f"Only {stock_quantity} unit(s) are available for {product['name']}.",
            "product": product,
        }

    status = "pending" if action == "add_to_cart" else "paid"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(_connect()) as conn:
        order_id = _next_order_id(conn)
        conn.execute(
            """
            INSERT INTO orders (
                id,
                customer_name,
                product_id,
                quantity,
                unit_price,
                total_price,
                status,
                shipping_address,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                customer_name,
                product_id,
                quantity,
                unit_price,
                total_price,
                status,
                shipping_address,
                created_at,
            ),
        )

        if action == "purchase":
            conn.execute(
                "UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ?",
                (quantity, product_id),
            )

        conn.commit()

    verb = "added to cart" if action == "add_to_cart" else "purchased"
    return {
        "success": True,
        "message": f"{quantity} x {product['name']} {verb}.",
        "order": {
            "id": order_id,
            "customer_name": customer_name,
            "product_id": product_id,
            "product_name": product["name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "status": status,
            "shipping_address": shipping_address,
            "created_at": created_at,
        },
        "matched_product": product,
    }


@tool
def search_products(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search the product catalog by product name, category, brand, SKU, or description."""
    return _search_products(query=query, limit=limit)


@tool
def get_checkout(
    customer_name: str,
    product_query: str,
    quantity: int = 1,
    action: Literal["add_to_cart", "purchase"] = "add_to_cart",
    shipping_address: str = "",
) -> dict[str, Any] | str:
    """Add a matched product to cart or purchase it based on the customer's request."""
    return _checkout(
        customer_name=customer_name,
        product_query=product_query,
        quantity=quantity,
        action=action,
        shipping_address=shipping_address,
    )


def _agent_tools() -> list[Any]:
    return [search_products, get_checkout]


def _bound_llm() -> Any:
    load_dotenv()

    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is missing. Add it to your .env file.")

    return ChatGroq(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        temperature=0,
    ).bind_tools(_agent_tools())


def continue_agent_conversation(messages: list[Any]) -> tuple[str, list[Any]]:
    tools_by_name = {tool_item.name: tool_item for tool_item in _agent_tools()}
    llm = _bound_llm()

    for _ in range(4):
        ai_message = llm.invoke(messages)
        messages.append(ai_message)

        if not ai_message.tool_calls:
            return _guard_final_response(str(ai_message.content)), messages

        for tool_call in ai_message.tool_calls:
            selected_tool = tools_by_name[tool_call["name"]]
            result = selected_tool.invoke(tool_call["args"])
            tool_content = result if isinstance(result, str) else json.dumps(result)
            messages.append(
                ToolMessage(
                    content=tool_content,
                    tool_call_id=tool_call["id"],
                )
            )

    final_message = llm.invoke(messages)
    messages.append(final_message)
    return _guard_final_response(str(final_message.content)), messages


def run_agent(customer_message: str) -> str:
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=customer_message),
    ]

    response, _ = continue_agent_conversation(messages)
    return response


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    customer_message = " ".join(sys.argv[1:]).strip()
    if not customer_message:
        customer_message = input("Customer: ").strip()

    response = run_agent(customer_message)
    print(f"Assistant: {response}")


if __name__ == "__main__":
    main()
