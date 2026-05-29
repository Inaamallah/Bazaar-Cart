# Bazaar AI: Stateful E-Commerce AI Agent

An autonomous, full-stack AI shopping assistant built with LangChain and Groq. 

Unlike standard RAG (Retrieval-Augmented Generation) applications that only read data, this project implements a **custom Reasoning and Acting (ReAct) loop** that allows the LLM to autonomously search a database, evaluate inventory, and execute mock checkout transactions using SQLite.

## 🚀 Features

* **Custom ReAct Loop:** Bypasses heavy abstraction frameworks (like LangGraph) in favor of a manual, deterministic 4-turn execution loop to optimize speed and strictly bound token spend.
* **Algorithmic Product Search:** A custom-built local search engine that tokenizes natural language queries, removes stop-words, extracts numerical price ceilings via Regex, and ranks SQLite rows using a tiered heuristic scoring system.
* **Transactional State Management:** An interactive checkout tool that validates inventory levels before safely mutating database state.
* **Unified Interface:** A clean Streamlit dashboard featuring a conversational chat UI, a manual catalog search fallback, and real-time business metrics.

## 🛠️ Tech Stack

* **Frontend & Orchestration:** [Streamlit](https://streamlit.io/)
* **AI & Agent Framework:** [LangChain Core](https://python.langchain.com/)
* **LLM Provider:** [Groq](https://groq.com/) (Open-source models for ultra-low latency inference)
* **Database:** SQLite3 (Local, serverless relational database)
* **Data Processing:** Pandas, Regex

## ⚙️ Architecture

This project uses a monolithic architecture designed for rapid prototyping and easy local execution. 
1. **User Input:** Captured via Streamlit Chat UI.
2. **Context Injection:** User profile data (Name, Address) is dynamically injected into the LangChain message history array.
3. **Agent Loop:** The Groq LLM evaluates the history and decides whether to respond directly or invoke a tool (`search_products` or `get_checkout`).
4. **Tool Execution:** Python functions execute raw SQL queries against `shopping_agent.db` and return formatted JSON payloads back to the LLM for synthesis.

## 💻 Local Setup & Installation

Follow these steps to run the agent locally on your machine.

### 1. Clone the repository
```bash
git clone https://github.com/Inaamallah/Bazaar-Cart.git
cd Bazaar-Cart

```

### 2. Set up a virtual environment (Recommended)

```bash
python -m venv env
# On Windows:
env\Scripts\activate
# On macOS/Linux:
source env/bin/activate

```

### 3. Install dependencies

```bash
pip install -r requirements.txt

```

### 4. Configure Environment Variables

Create a `.env` file in the root directory of the project and add your Groq API key:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama3-8b-8192  # Or your preferred Groq model

```

### 5. Run the Application

```bash
streamlit run app.py

```

The application will automatically initialize the `shopping_agent.db` SQLite database if it does not exist, and launch the web interface at `http://localhost:8501`.

## 🧠 Example Prompts to Try

Once the app is running, try testing the agent's boundaries with these prompts:

* *"I need a wireless mouse under $50."* (Tests Regex price extraction and search tool)
* *"Add two of the AeroGlide mice to my cart."* (Tests the checkout tool and inventory validation)
* *"What is the total cost of my current order?"* (Tests multi-turn context memory)

## 🛡️ Guardrails Implemented

* **Iteration Caps:** The ReAct loop is hardcoded to a maximum of 4 turns to prevent infinite looping and runaway API costs.
* **Inventory Protection:** The `_checkout` function explicitly checks `stock_quantity` against the requested amount before allowing a database write.
* **Query Sanitization:** Input queries are stripped of stop-words and non-alphanumeric characters before hitting the SQL `LIKE` clauses to prevent query failure.

---

*Built as a demonstration of autonomous agent design and local database orchestration.*

```

```
