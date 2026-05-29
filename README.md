# Bazaar Cart

Bazaar Cart is a Streamlit shopping assistant backed by a local SQLite catalog.

Main files:

- `shopping_agent.py` - LangChain tools, agent loop, checkout rules, and database logic.
- `streamlit_app.py` - Streamlit frontend for chat, catalog search, checkout, and orders.

## Run

```powershell
.\env\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8501
```

Then open:

```text
http://localhost:8501
```
