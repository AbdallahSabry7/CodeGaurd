# 🛡️ CodeGuard

> Multi-agent Python code analysis and automated refactoring powered by LangGraph — with black-box behavioral-equivalence verification.
> 

## What is CodeGuard?

CodeGuard is an agentic pipeline that takes raw code, detects its language, analyzes it for quality issues, automatically refactors it, and validates the result — all without human intervention. Python is analyzed directly; Java and C++ are translated to Python, processed, then translated back. Before refactoring, CodeGuard captures a **golden master** of the original's boundary behavior and replays it after every refactor, so a cleaner structure can never silently change what the program does.

## Architecture

CodeGuard is built on **LangGraph**. The pipeline combines **three core LLM agents** (Translator, Architect, Refactor), one **LLM-assisted Characterizer**, and several **deterministic plain-function nodes** — including a **Convergence controller** (which replaced the old LLM comparator) and an **Equivalence gate** — wired together as a directed graph with conditional edges and a hard cap of `max_iterations` (default 3) refactor loops.

```mermaid
flowchart TD
    Start([Input code]) --> Detect["Detect Language (plain fn)"]
    Detect -->|"unsupported / unknown"| End1([END])
    Detect -->|python| Char["Characterize → Golden Master (once)"]
    Detect -->|"java / cpp"| ToPy["Translate to Python (LLM)"]
    ToPy --> SynT["Syntax Check - translation"]
    SynT -->|fix| ToPy
    SynT -->|proceed| Char
    Char --> Analyze["Analyzer (analysis_tool)"]
    Analyze --> Arch["Architect Agent (LLM)"]
    Arch -->|HALT_PERFECT_ENOUGH| End2([END])
    Arch -->|"first pass: directives"| Refactor["Refactor Agent (LLM)"]
    Arch -->|"re-entry"| Conv["Convergence Node (plain fn)"]
    Refactor --> Syn["Syntax Check (ast.parse)"]
    Syn -->|fix| Refactor
    Syn -->|proceed| Analyze
    Conv -->|continue| Refactor
    Conv -->|finalize| Exec["Executor (Docker sandbox)"]
    Exec -->|FAIL| Refactor
    Exec -->|PASS| Equiv["Equivalence Gate (replay Golden Master)"]
    Equiv -->|behavior changed| Refactor
    Equiv -->|"preserved / unverified"| Fin{"non-python?"}
    Fin -->|yes| FromPy["Translate from Python (LLM)"]
    Fin -->|no| End3([END])
    FromPy --> End4([END])
```

### LLM agents + Characterizer

- **Translator Agent** — converts Java/C++ → Python before analysis, and Python → the original language after refactoring. Runs only for non-Python input. (`model3`, Groq, temp 0.2)
- **Architect Agent** — runs after every analyzer pass. Consumes the raw analyzer report, validates its output against a Pydantic schema (with retries), classifies findings (SOLID / Clean Code / Complexity) with severity + confidence, and emits a numbered, severity-sorted list of refactor directives. The global verdict is recomputed in code, never trusted from the model. (`model4`, OpenRouter, temp 0.2)
- **Refactor Agent** — rewrites code to satisfy the Architect's directives on the first pass, and on re-entry fixes only what the Syntax Check, Executor, or **Equivalence Gate** flagged (in that priority order). (`model1`, OpenRouter, temp 0.2)
- **Characterizer (LLM-assisted)** — runs once at ingestion. Reads the Python original, decides the behavioral boundary (`stdio` vs `api`), and designs a coverage-minded input suite. The LLM only picks the inputs; capturing and comparing observations is deterministic. (`model2`, Groq, temp 0.1)

### Plain-function nodes (no LLM)

- **Detect Language** — regex scoring with positive/negative signals to pick Python / Java / C++ or mark input unsupported.
- **Analyzer** — calls `analysis_tool` directly. The first run is captured as the baseline report.
- **Syntax Check** — `ast.parse()` on refactored (and separately on translated) code; loops back on failure.
- **Convergence Node** — scores each Architect report into a single weighted number and decides whether to keep refactoring or finalize. Replaces the old LLM comparator. (details below)
- **Executor** — calls `execute_code_tool` to run the code in a Docker container.
- **Equivalence Gate (Golden Master)** — replays the captured input suite against the refactored code and compares observations. `changed` → back to Refactor with the failing inputs as evidence; `preserved` / `unverified` → proceed (only a true `changed` verdict blocks).

### Tools & services

- `tools/analysis_tool.py` — single merged tool: time & space complexity, SOLID violations (SRP / OCP / LSP / ISP / DIP), and a clean-code index.
- `tools/execute_code_tool.py` — runs code in a Docker container, auto-installing third-party imports via pip before execution.
- `tools/convergence.py` — deterministic quality scoring: `score_report`, `compare_reports`, and the `ConvergenceController` stop logic.
- `tools/golden_master.py` — deterministic capture / replay / compare engine for behavioral equivalence.

## Behavioral Equivalence (Golden Master)

A refactor is *supposed* to rename, split, merge, add, and delete functions — so equivalence cannot be checked per-function. CodeGuard checks it at the **boundary** instead:

1. **Characterize once** — before any refactoring, run the original on a generated suite of inputs and record its observations (stdout + exception kind). That snapshot is the **golden master**.
2. **Replay** — after each refactor, feed the same inputs to the new code and compare to the golden master. Internal renames/splits/additions are invisible by construction.

Two boundaries, one rule:

- **stdio** — programs that read stdin / print: compare stdout + exception kind on identical input.
- **api** — libraries: an LLM-written driver reads JSON args from stdin and calls the **public** functions; public names stay stable while internals churn freely.

If the original can't be run or no cases can be generated, the result is **unverified** — flagged for visibility but **never blocking** and never counted as a pass. Only a genuine `changed` verdict sends the code back to the Refactor agent. Equivalence answers only *"same behavior?"*; *"better?"* is decided by the deterministic convergence loop below.

## Quality Convergence (deterministic)

Instead of asking an LLM *"is this better?"*, CodeGuard scores quality deterministically. After each refactor pass the Analyzer and Architect re-evaluate the code; the **Convergence Node** then turns the latest Architect report into a single weighted score (severity- and complexity-weighted — lower is better, `0` = clean) and appends it to a history. The `ConvergenceController` then decides:

- **continue** → send the code back to the Refactor agent for another pass, or
- **finalize** → stop and hand off to the Executor, when the score reaches `0`, the per-pass gain drops below `min_gain` (default 0.05), or the loop hits `max_improvement_loops` (default 3).

This replaces the old LLM Comparator with a reproducible, explainable stop condition.

## Models

| **Node** | **Type** | **Model (default)** | **Provider** | **Temp** |
| --- | --- | --- | --- | --- |
| Detect Language | Plain fn | — | — | — |
| Translator | LLM | `model3` (llama-3.3-70b-versatile) | Groq | 0.2 |
| Characterizer | LLM-assisted | `model2` (llama-4-scout-17b-16e-instruct) | Groq | 0.1 |
| Analyzer | Plain fn | — | — | — |
| Architect | LLM | `model4` (set in .env) | OpenRouter | 0.2 |
| Refactor | LLM | `model1` (openrouter/owl-alpha) | OpenRouter | 0.2 |
| Syntax Check | Plain fn | — | — | — |
| Convergence Node | Plain fn | — | — | — |
| Executor | Plain fn | — | — | — |
| Equivalence Gate | Plain fn | — | — | — |

## Project Structure

```
CodeGuard/
├── app/
│   ├── agents/
│   │   ├── architect.py         # Architect Agent (LLM, OpenRouter)
│   │   ├── characterizer.py     # Characterizer - builds the golden master (LLM-assisted, Groq)
│   │   ├── refactor.py          # Refactor Agent (LLM, OpenRouter)
│   │   └── translator.py        # Translator Agent (LLM, Groq)
│   ├── graph/
│   │   ├── __init__.py          # exposes build_graph
│   │   ├── nodes.py             # plain-function nodes + convergence_node + equivalence_node
│   │   ├── routers.py           # conditional-edge routing (+ convergence_router, equivalence_router)
│   │   └── workflow.py          # StateGraph wiring (build_graph)
│   ├── helpers/
│   │   └── config.py            # pydantic-settings
│   ├── prompts/
│   │   ├── architect_prompt.py
│   │   ├── characterize_prompt.py
│   │   ├── refactor_prompt.py
│   │   └── translator_prompt.py
│   ├── schemas/
│   │   └── state.py             # AgentState TypedDict (+ quality_scores, golden_master, behavior_diff, equivalence_report)
│   ├── services/
│   │   ├── complexity.py
│   │   ├── clean_code.py
│   │   ├── executer.py          # Docker sandbox runner
│   │   └── tests/               # calibration tests
│   ├── tools/
│   │   ├── analysis_tool.py
│   │   ├── execute_code_tool.py
│   │   ├── convergence.py       # score_report / compare_reports / ConvergenceController
│   │   └── golden_master.py     # capture / replay / compare engine
│   ├── app.py                   # Streamlit web UI
│   ├── main.py                  # CLI entry point
│   ├── llms.py                  # LLM instantiation (Groq + OpenRouter)
│   ├── requirements.txt
│   └── .env.example
├── LICENSE
└── README.md
```

## Requirements

- Python 3.11+
- Docker Desktop (must be running)
- A Groq API key (free)
- An OpenRouter API key (free)
- A LangSmith API key (optional, for tracing)

## Installation

```bash
git clone https://github.com/AbdallahSabry7/CodeGuard.git
cd CodeGuard/app

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Environment Setup

Copy the example env file (in `app/`) and fill in your keys:

```bash
cp .env.example .env
```

```bash
GROQ_API_KEY=
OPENROUTER_API_KEY=
LANGSMITH_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_PROJECT=CodeGuard

# Groq models
model2=meta-llama/llama-4-scout-17b-16e-instruct   # Characterizer
model3=llama-3.3-70b-versatile                     # Translator

# OpenRouter models
model1=openrouter/owl-alpha                        # Refactor
model4=                                            # Architect (required - set an OpenRouter model)
openai_api_base=https://openrouter.ai/api/v1

# Loop controls
max_iterations=3
max_improvement_loops=3
min_gain=0.05
```

## Usage

Run commands from inside the `app/` directory.

### Web UI (Streamlit)

```bash
streamlit run app.py
```

### CLI

```bash
python main.py --file path/to/your_code.py
cat your_code.py | python main.py --stdin
```

## License

Apache-2.0