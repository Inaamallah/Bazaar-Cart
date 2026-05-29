from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from shopping_agent import SYSTEM_PROMPT, _checkout, _search_products, continue_agent_conversation


APP_NAME = "Bazaar Cart"
DB_PATH = Path(__file__).with_name("shopping_agent.db")

app = FastAPI(title=f"{APP_NAME} API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    customer_name: str = "Guest"
    shipping_address: str = ""
    history: list[ChatHistoryItem] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    limit: int = 8


class CheckoutRequest(BaseModel):
    customer_name: str = "Guest"
    product_query: str
    quantity: int = 1
    action: Literal["add_to_cart", "purchase"] = "add_to_cart"
    shipping_address: str = ""


def _query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _metrics() -> dict[str, Any]:
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


def _agent_messages(request: ChatRequest) -> list[Any]:
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    for item in request.history[-10:]:
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        else:
            messages.append(AIMessage(content=item.content))

    contextual_prompt = (
        f"Customer name: {request.customer_name or 'Guest'}\n"
        f"Shipping address: {request.shipping_address or 'not provided'}\n"
        f"Customer request: {request.message}"
    )
    messages.append(HumanMessage(content=contextual_prompt))
    return messages


@app.get("/")
def root() -> dict[str, str]:
    return {"name": APP_NAME, "status": "ready"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return _metrics()


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    response, _ = continue_agent_conversation(_agent_messages(request))
    return {"response": response}


@app.post("/products/search")
def search_products(request: SearchRequest) -> dict[str, Any]:
    return {"products": _search_products(request.query, request.limit)}


@app.post("/checkout")
def checkout(request: CheckoutRequest) -> dict[str, Any]:
    result = _checkout(
        customer_name=request.customer_name,
        product_query=request.product_query,
        quantity=request.quantity,
        action=request.action,
        shipping_address=request.shipping_address,
    )
    if isinstance(result, str):
        return json.loads(result)
    return result


@app.get("/orders")
def orders(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    rows = _query(
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
        LIMIT ?
        """,
        (limit,),
    )
    return {"orders": rows}
