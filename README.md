# 🛡️ CodeGuard

> Multi-agent Python code analysis and automated refactoring powered by LangGraph.

---

## What is CodeGuard?

CodeGuard is an agentic pipeline that takes raw Python code, analyzes it for quality issues, automatically refactors it, and validates the result — all without human intervention.

### Architecture

CodeGuard is built on **LangGraph**, a framework for building stateful multi-agent workflows as directed graphs. The system is composed of two LLM agents and three plain-function nodes, each with a specific role:

```
[Input Code]
     │
     ▼
┌─────────────┐
│  Analyzer   │ ◄──── analysis_tool (complexity + SOLID + clean code index)
│  (function) │       called directly — no LLM, no message history
└──────┬──────┘
       │  original_analyzer_report (captured once, never overwritten)
       ▼
┌─────────────┐
│  Refactor   │ ◄──── LLM rewrites code based on analysis report
│   Agent     │       REFACTOR_SYSTEM_PROMPT (1st pass)
│   (LLM)     │       REFACTOR_SYSTEM_PROMPT2 (subsequent passes)
└──────┬──────┘
       │  refactored_code
       ▼
┌─────────────┐     SyntaxError + error message
│   Syntax    │ ──────────────────────────────► Refactor Agent (retry)
│   Check     │
│  (function) │  ast.parse() only — no LLM
└──────┬──────┘
       │  valid code
       ▼
┌─────────────┐               ┌──────────────┐
│  Analyzer   │ ── report ──► │  Comparator  │ ◄──── diffs original vs refactored report
│  (function) │               │    Agent     │       RESOLVED / UNRESOLVED / REGRESSED
│  re-analyze │               │    (LLM)     │       outputs numbered Refactor Instructions
│ refactored  │               └──────┬───────┘              on FAIL
│    code     │                      │
└─────────────┘            PASS ─────┼───── FAIL ──► Refactor Agent (max 3 iterations)
                                     ▼
                              ┌─────────────┐
                              │  Executor   │ ◄──── execute_code_tool
                              │ (function)  │       runs code in Docker sandbox
                              └──────┬──────┘       no LLM involved
                                     │
                          PASS ──► END
                          FAIL ──► Refactor Agent (counted in refactor iterations)
```

**LLM Agents** — only two nodes use a language model:
- **Refactor Agent** — rewrites code to fix all flagged issues. Uses `REFACTOR_SYSTEM_PROMPT` on the first pass and `REFACTOR_SYSTEM_PROMPT2` on subsequent passes (fixes only what the Comparator or Executor flagged, without regressing already-resolved issues).
- **Comparator Agent** — receives `original_analyzer_report` + `analyzer_report` (refactored). Diffs them, classifies every issue as `RESOLVED` / `UNRESOLVED` / `REGRESSED`, and outputs numbered Refactor Instructions on `FAIL`. No tools, no code — reports only.

**Plain-function nodes** — three nodes run deterministic logic with no LLM:
- **Analyzer** — calls `analysis_tool` directly. Runs twice: once on the original code (result stored as `original_analyzer_report`, never overwritten), and once on the refactored code before the Comparator.
- **Syntax Check** — runs `ast.parse()` on the refactored code. Sends the error message back to the Refactor Agent on failure; continues to re-analysis on success.
- **Executor** — calls `execute_code_tool` directly. Runs the refactored code in a Docker sandbox and sends runtime errors back to the Refactor Agent.

**Tools** are Python functions decorated with `@tool`:
- `analysis_tool` — single merged tool: time & space complexity, SOLID violations (SRP/OCP/LSP/ISP/DIP), and clean code index. Called directly by the Analyzer function — not by any LLM.
- `execute_code_tool` — runs code in a Docker sandbox (`python:3.11-slim`), 10s timeout, 128MB memory, network disabled. Called directly by the Executor function — not by any LLM.

**The Graph** (defined in `graph.py`) wires the nodes together with conditional edges:
- **Syntax Check** loops back to Refactor Agent on `ast.parse()` failure
- **Comparator Agent** loops back to Refactor Agent if any issue is `UNRESOLVED` or `REGRESSED`
- **Executor** loops back to Refactor Agent on runtime errors
- Maximum of **3 refactor iterations** before the pipeline exits

**State** (`AgentState`) is a typed dictionary shared across all nodes:

| Field | Description |
|-------|-------------|
| `original_code` | Input code — never changes |
| `refactored_code` | Latest refactor output |
| `original_analyzer_report` | Captured on first Analyzer run — never overwritten |
| `analyzer_report` | Overwritten each Analyzer run (used as Comparator's refactored report) |
| `comparator_report` | Latest Comparator output, fed back to Refactor Agent on FAIL |
| `syntax_error` | Populated by Syntax Check on failure, cleared on success |
| `execution_result` | Populated by Executor, fed back to Refactor Agent on FAIL |
| `refactor_iterations` | Loop counter — hard stop at 3 |

### Project Structure

```
CodeGuard/
├── main.py               # CLI entry point
├── app.py                # Streamlit web UI
├── graph.py              # LangGraph graph definition and routing logic
├── agents.py             # Analyzer, Refactor, Comparator, and Executor node functions
├── state.py              # AgentState TypedDict
├── tools.py              # analysis_tool + execute_code_tool definitions
├── complexity.py         # AST-based complexity analyzer
├── prompts.py            # REFACTOR_SYSTEM_PROMPT, REFACTOR_SYSTEM_PROMPT2, COMPARATOR_PROMPT
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

## Docker Setup

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

> **Sandbox constraints:** The container runs with no network access, a read-only filesystem, 128MB memory limit, and a 10-second timeout. It is automatically removed after each run.

---

## Usage

### Web UI (Streamlit)

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser. Paste your Python code or upload a `.py` file and click **Run Analysis**. Results stream live across four tabs: Analysis Report, Refactored Code, Comparator Report, and Execution Result.

### CLI

Paste your code into `code_to_analyze.py`, then run:

```bash
python main.py
```

The final execution result will be printed to the terminal.

---

## Models

| Node | Type | Model | Provider |
|------|------|-------|----------|
| Analyzer | Plain function | — | — |
| Refactor Agent | LLM | `poolside/laguna-m.1:free` | OpenRouter |
| Syntax Check | Plain function | — | — |
| Comparator Agent | LLM | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq |
| Executor | Plain function | — | — |

> Both LLM nodes use `temperature=0`. The Comparator uses `max_retries=2`. All `.bind_tools()` calls use `parallel_tool_calls=False`.

---

## License

MIT