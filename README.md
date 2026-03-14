# 🛡️ CodeGuard

> Multi-agent Python code analysis and automated refactoring powered by LangGraph.

---

## What is CodeGuard?

CodeGuard is an agentic pipeline that takes raw Python code, analyzes it for quality issues, automatically refactors it, and validates the result — all without human intervention.

### Architecture

CodeGuard is built on **LangGraph**, a framework for building stateful multi-agent workflows as directed graphs. The system is composed of three cooperating agents, each with a specific role:

```
[Input Code]
     │
     ▼
┌─────────────┐
│  Analyzer   │ ◄──── 3 analysis tools (complexity, SOLID, clean code)
│   Agent     │
└──────┬──────┘
       │  analyzer_report
       ▼
┌─────────────┐
│  Refactor   │ ◄──── LLM rewrites code based on the report
│   Agent     │
└──────┬──────┘
       │  refactored_code
       ▼
┌─────────────┐
│  Validator  │ ◄──── execute_code_tool (runs code in Docker)
│   Agent     │
└──────┬──────┘
       │
  PASS ──► END
  FAIL ──► Refactor Agent (up to 3 iterations)
```

**Agents** are LLM-powered nodes in the graph. Each agent receives the shared state, invokes its tools or LLM, and writes results back to state.

**Tools** are Python functions decorated with `@tool` that agents can call. CodeGuard uses four tools: `complexity_analyzer_tool`, `solid_analysis_tool`, `clean_code_analysis_tool`, and `execute_code_tool`.

**The Graph** (defined in `graph.py`) wires the agents together with conditional edges — the validator can loop back to the refactor agent if issues remain, up to a maximum of 3 iterations.

**State** (`AgentState`) is a typed dictionary shared across all nodes. It holds the messages history, analyzer report, refactored code, validator report, and iteration count.

### Project Structure

```
CodeGuard/
├── main.py               # CLI entry point
├── app.py                # Streamlit web UI
├── graph.py              # LangGraph graph definition and routing logic
├── agents.py             # Analyzer, Refactor, and Validator agent functions
├── state.py              # AgentState TypedDict
├── tools.py              # All @tool definitions + Docker execution + safety checks
├── complexity.py         # AST-based complexity analyzer
├── prompts.py            # All LLM system prompts
├── llms.py               # LLM instantiation (Groq + OpenRouter)
├── code_to_analyze.py    # Drop your code here for CLI usage
└── requirements.txt
```

---

## Requirements

- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (must be running)
- A [Groq](https://console.groq.com) API key (free)
- An [OpenRouter](https://openrouter.ai) API key (free)
- A [LangSmith](https://smith.langchain.com) API key (free, for tracing)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/CodeGuard.git
cd CodeGuard
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Setup

Create a `.env` file in the project root:

```bash
touch .env   # macOS/Linux
# or create it manually on Windows
```

Add the following keys:

```env
GROQ_API_KEY=your_groq_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
LANGSMITH_API_KEY=your_langsmith_api_key_here
```

| Key | Where to get it |
|-----|----------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `LANGSMITH_API_KEY` | [smith.langchain.com](https://smith.langchain.com) → Settings → API Keys |

---

## Docker Desktop Setup

CodeGuard executes refactored code inside an isolated Docker container for safety. Docker Desktop must be installed and **running** before you start CodeGuard.

### 1. Install Docker Desktop

Download and install from: https://www.docker.com/products/docker-desktop/

### 2. Start Docker Desktop

Open Docker Desktop and wait until the status shows **"Engine running"** in the bottom left.

### 3. Pull the Python image

```bash
docker pull python:3.11-slim
```

This is the sandboxed environment CodeGuard uses to run code. It only needs to be pulled once.

### 4. Verify Docker is working

```bash
docker run --rm python:3.11-slim python --version
```

You should see `Python 3.11.x`. If you get an error, make sure Docker Desktop is running.

> **Note:** The container runs with no network access, a read-only filesystem, 128MB memory limit, and a 10-second timeout. It is automatically removed after each run.

---

## Usage

### Web UI (Streamlit)

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser. Paste your Python code or upload a `.py` file and click **Run Analysis**.

### CLI

Paste your code into `code_to_analyze.py`, then run:

```bash
python main.py
```

The final validator report will be printed to the terminal.

---

## Models Used

| Agent | Model | Provider |
|-------|-------|----------|
| Analyzer | `llama-3.3-70b-versatile` | Groq |
| Refactor | `stepfun/step-3.5-flash:free` | OpenRouter |
| Validator | `llama-3.3-70b-versatile` | Groq |

---

## License

MIT
