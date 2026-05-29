from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


APP_NAME = "Bazaar Cart"
DEFAULT_API_URL = "http://localhost:8000"


def api_base_url() -> str:
    return os.getenv("BAZAAR_CART_API_URL", DEFAULT_API_URL).rstrip("/")


def clean_assistant_text(content: str) -> str:
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</?ul>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<li>", "- ", content, flags=re.IGNORECASE)
    content = re.sub(r"</li>", "\n", content, flags=re.IGNORECASE)
    return re.sub(r"</?[^>]+>", "", content).strip()


def api_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    url = f"{api_base_url()}{path}"
    try:
        response = requests.request(method, url, timeout=90, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach the {APP_NAME} API at {url}. Start FastAPI first. Details: {exc}") from exc


def get_metrics() -> dict[str, Any]:
    return api_request("GET", "/metrics")


def search_products(query: str, limit: int) -> list[dict[str, Any]]:
    data = api_request("POST", "/products/search", json={"query": query, "limit": limit})
    return data.get("products", [])


def checkout(
    customer_name: str,
    product_query: str,
    quantity: int,
    action: str,
    shipping_address: str,
) -> dict[str, Any]:
    return api_request(
        "POST",
        "/checkout",
        json={
            "customer_name": customer_name,
            "product_query": product_query,
            "quantity": quantity,
            "action": action,
            "shipping_address": shipping_address,
        },
    )


def get_orders() -> list[dict[str, Any]]:
    return api_request("GET", "/orders").get("orders", [])


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

                try:
                    result = checkout(
                        customer_name=customer_name,
                        product_query=str(product["sku"]),
                        quantity=int(quantity),
                        action=action,
                        shipping_address=shipping_address,
                    )
                    if result.get("success"):
                        st.success(result["message"])
                    else:
                        st.error(result.get("message", "Checkout could not be completed."))
                except RuntimeError as exc:
                    st.error(str(exc))


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

    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    history = st.session_state.chat_messages[:-1]

    with chat_container:
        with st.chat_message("user"):
            st.markdown(prompt, unsafe_allow_html=False)

        with st.chat_message("assistant"):
            with st.spinner("Thinking through the catalog..."):
                try:
                    data = api_request(
                        "POST",
                        "/chat",
                        json={
                            "message": prompt,
                            "customer_name": customer_name,
                            "shipping_address": shipping_address,
                            "history": history,
                        },
                    )
                    response = clean_assistant_text(data.get("response", ""))
                except RuntimeError as exc:
                    response = str(exc)

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
    try:
        products = search_products(query, int(limit)) if query.strip() else []
    except RuntimeError as exc:
        st.error(str(exc))
        products = []

    if products:
        st.dataframe(product_rows(products), hide_index=True, width="stretch")

    render_product_actions(products, customer_name, shipping_address)


def render_orders() -> None:
    try:
        orders = get_orders()
    except RuntimeError as exc:
        st.error(str(exc))
        orders = []

    st.dataframe(pd.DataFrame(orders), hide_index=True, width="stretch")


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
        st.caption(f"API: `{api_base_url()}`")
        st.divider()
        if st.button("Reset chat", width="stretch"):
            reset_chat()
            st.rerun()

        try:
            metrics = get_metrics()
            st.metric("Products", metrics["products"])
            st.metric("Reviews", metrics["reviews"])
            st.metric("Orders", metrics["orders"])
            st.metric("Paid revenue", f"${float(metrics['revenue']):.2f}")
        except RuntimeError as exc:
            st.error(str(exc))

    st.title(APP_NAME)
    st.caption("AI storefront powered by a FastAPI backend and SQLite catalog.")

    tab_chat, tab_search, tab_orders = st.tabs(["Chat", "Catalog", "Orders"])
    with tab_chat:
        render_chat(customer_name, shipping_address)
    with tab_search:
        render_search(customer_name, shipping_address)
    with tab_orders:
        render_orders()


if __name__ == "__main__":
    main()
