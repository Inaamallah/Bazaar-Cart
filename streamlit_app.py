from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from shopping_agent import SYSTEM_PROMPT, _checkout, _search_products, continue_agent_conversation


APP_NAME = "Bazaar Cart"
DB_PATH = Path(__file__).with_name("shopping_agent.db")


def clean_assistant_text(content: str) -> str:
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</?ul>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<li>", "- ", content, flags=re.IGNORECASE)
    content = re.sub(r"</li>", "\n", content, flags=re.IGNORECASE)
    return re.sub(r"</?[^>]+>", "", content).strip()


def query_table(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_metrics() -> dict[str, Any]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        review_count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(total_price), 0) FROM orders WHERE status = 'paid'"
        ).fetchone()[0]

    return {
        "products": product_count,
        "orders": order_count,
        "reviews": review_count,
        "revenue": float(revenue),
    }


def reset_chat() -> None:
    st.session_state.chat_messages = [
        {
            "role": "assistant",
            "content": f"Welcome to {APP_NAME}. Tell me what you want to find, add to cart, or purchase.",
        }
    ]


def initialize_state() -> None:
    if "chat_messages" not in st.session_state:
        reset_chat()
    if "last_search_query" not in st.session_state:
        st.session_state.last_search_query = "headphones under 100"


def agent_messages_from_history(customer_name: str, shipping_address: str, prompt: str) -> list[Any]:
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    for item in st.session_state.chat_messages[-10:]:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            messages.append(AIMessage(content=item["content"]))

    messages.append(
        HumanMessage(
            content=(
                f"Customer name: {customer_name or 'Guest'}\n"
                f"Shipping address: {shipping_address or 'not provided'}\n"
                f"Customer request: {prompt}"
            )
        )
    )
    return messages


def product_rows(products: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "ID": item["id"],
            "SKU": item["sku"],
            "Name": item["name"],
            "Brand": item["brand"],
            "Category": item["category"],
            "Price": f"${float(item['price']):.2f}",
            "Stock": item["stock_quantity"],
            "Rating": item["average_rating"],
            "Reviews": item["review_count"],
        }
        for item in products
    ]
    return pd.DataFrame(rows)


def render_product_actions(products: list[dict[str, Any]], customer_name: str, shipping_address: str) -> None:
    if not products:
        st.info("No matching products found.")
        return

    for product in products:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.subheader(product["name"])
                st.caption(f"{product['brand']} | {product['category']} | SKU {product['sku']}")
                st.write(product["description"])
                st.write(
                    f"**${float(product['price']):.2f}** | "
                    f"{product['stock_quantity']} in stock | "
                    f"{product['average_rating']} rating"
                )
            with right:
                quantity = st.number_input(
                    "Qty",
                    min_value=1,
                    max_value=min(5, max(1, int(product["stock_quantity"]))),
                    value=1,
                    key=f"qty_{product['id']}",
                )
                add_clicked = st.button("Add", key=f"add_{product['id']}", width="stretch")
                buy_clicked = st.button("Buy", key=f"buy_{product['id']}", width="stretch")

            if add_clicked or buy_clicked:
                action = "purchase" if buy_clicked else "add_to_cart"
                if action == "purchase" and not shipping_address.strip():
                    st.error("Enter a shipping address before purchasing.")
                    continue

                result = _checkout(
                    customer_name=customer_name,
                    product_query=str(product["sku"]),
                    quantity=int(quantity),
                    action=action,
                    shipping_address=shipping_address,
                )
                if isinstance(result, str):
                    result = json.loads(result)

                if result.get("success"):
                    st.success(result["message"])
                else:
                    st.error(result.get("message", "Checkout could not be completed."))


def render_chat(customer_name: str, shipping_address: str) -> None:
    st.write("Ask naturally: search for products, add an item to cart, or purchase it.")

    chat_container = st.container()
    with chat_container:
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"], unsafe_allow_html=False)

    prompt = st.chat_input("Find wireless earbuds under 50, or add headphones to cart")
    if not prompt:
        return

    agent_messages = agent_messages_from_history(customer_name, shipping_address, prompt)
    st.session_state.chat_messages.append({"role": "user", "content": prompt})

    with chat_container:
        with st.chat_message("user"):
            st.markdown(prompt, unsafe_allow_html=False)

        with st.chat_message("assistant"):
            with st.spinner("Thinking through the catalog..."):
                try:
                    response, _ = continue_agent_conversation(agent_messages)
                    response = clean_assistant_text(response)
                except Exception as exc:
                    response = f"I could not complete that request: {exc}"

    st.session_state.chat_messages.append({"role": "assistant", "content": response})
    st.rerun()


def render_search(customer_name: str, shipping_address: str) -> None:
    col_a, col_b = st.columns([4, 1])
    with col_a:
        query = st.text_input(
            "Product search",
            value=st.session_state.last_search_query,
            placeholder="Try: shoes under 100, electronics, air fryer",
        )
    with col_b:
        limit = st.number_input("Limit", min_value=1, max_value=25, value=8)

    st.session_state.last_search_query = query
    products = _search_products(query, limit=int(limit)) if query.strip() else []

    if products:
        st.dataframe(product_rows(products), hide_index=True, width="stretch")

    render_product_actions(products, customer_name, shipping_address)


def render_orders() -> None:
    orders = query_table(
        """
        SELECT
            orders.id,
            orders.customer_name,
            products.name AS product,
            orders.quantity,
            orders.total_price,
            orders.status,
            orders.shipping_address,
            orders.created_at
        FROM orders
        JOIN products ON products.id = orders.product_id
        ORDER BY orders.id DESC
        LIMIT 100
        """
    )
    st.dataframe(orders, hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="cart", layout="wide")
    load_dotenv()
    initialize_state()

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; }
        [data-testid="stMetricValue"] { font-size: 1.6rem; }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.title(APP_NAME)
        customer_name = st.text_input("Customer name", value="Guest")
        shipping_address = st.text_area("Shipping address", value="", height=90)
        st.divider()
        if st.button("Reset chat", width="stretch"):
            reset_chat()
            st.rerun()

        metrics = get_metrics()
        st.metric("Products", metrics["products"])
        st.metric("Reviews", metrics["reviews"])
        st.metric("Orders", metrics["orders"])
        st.metric("Paid revenue", f"${metrics['revenue']:.2f}")

    st.title(APP_NAME)
    st.caption(f"AI storefront powered by Streamlit and SQLite. Model: `{os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b')}`")

    tab_chat, tab_search, tab_orders = st.tabs(["Chat", "Catalog", "Orders"])
    with tab_chat:
        render_chat(customer_name, shipping_address)
    with tab_search:
        render_search(customer_name, shipping_address)
    with tab_orders:
        render_orders()


if __name__ == "__main__":
    main()
