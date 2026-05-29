# Bazaar Cart

Bazaar Cart is an AI shopping assistant with:

- FastAPI backend for the catalog, checkout, orders, metrics, and LangChain agent.
- Streamlit frontend for chat, catalog search, checkout actions, and order viewing.
- SQLite catalog stored in `shopping_agent.db`.

## Run

```powershell
.\env\Scripts\python.exe -m uvicorn api_server:app --host 127.0.0.1 --port 8000
.\env\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8501
```
