# 🛡️ CodeGuard — Drop-in Evaluation Harness

Evaluate **every part** of CodeGuard against baselines with **one command**.
Drop this `eval/` folder at the **root of your repo** (next to `app/`).

```
CodeGaurd/
├── app/        ← your pipeline
└── eval/       ← this folder
```

## TL;DR — run it now

```bash
cd eval
python run_all.py
```

That's it. No keys, no Docker, no setup required to **smoke-test the harness** —
it ships with tiny bundled datasets and offline fallbacks, and writes:

- `results/REPORT.md`  — readable tables, one section per component
- `results/results.json` — raw numbers

Then turn on the real comparison in two steps (below): **(1)** add an LLM key for
the real baseline, **(2)** wire the adapter to your pipeline.

---

## What it evaluates (every part → its baseline)

| Component (in your pipeline) | Baseline it's measured against | Metric |
|---|---|---|
| Detect Language | — (sanity check only) | accuracy |
| Analyzer · Complexity | raw-LLM big-O guess | exact-tier + within-1-tier accuracy |
| Analyzer · SOLID (SRP/OCP/LSP/ISP/DIP) | raw LLM | per-principle + macro **F1** |
| Analyzer · Clean code / smells | raw LLM | per-smell + macro **F1** |
| Refactor + Regression check | raw LLM (no verification) | test-pass %, **behavior-preserved %**, gate-blocked % |
| **Whole system** | LLM-only → +AST → +gate | **ablation table** |

The three systems compared (straight from your Rebuild & Evaluation Plan):
1. **Raw LLM** — one naive prompt, no AST, no verification.
2. **CodeGuard** — your full hybrid pipeline.
3. **Ablations** — LLM-only / LLM+AST / LLM+AST+gate, to show each layer's contribution.

---

## Step 1 — real baseline (30 seconds)

The offline stub is **not** a real baseline; it only proves the harness runs.
For real numbers, export a key (reuses the same ones your repo already uses):

```bash
export OPENROUTER_API_KEY=sk-...      # or: export GROQ_API_KEY=gsk_...
export BASELINE_MODEL=openai/gpt-oss-120b   # optional
python run_all.py
```

Set `CODEGUARD_EVAL_REQUIRE_LLM=1` to make a missing key a hard error (so you
never accidentally report stub numbers in the thesis).

## Step 2 — wire in YOUR pipeline (5 minutes)

Everything repo-specific lives in **one file**: `adapters/codeguard_adapter.py`.
Search it for `# === WIRE ===` (4 spots) and point them at your real code:

1. **`analysis_tool` import** — your merged analyzer (complexity + SOLID + clean code).
2. **`_normalize()`** — map your analyzer's report keys → `{complexity, solid, smells, clean_score}`.
   Run your analyzer on one snippet, look at the dict it returns, and adjust the field names.
3. **`refactor_full()`** — your `build_graph()` + the state keys for refactored code & verdict.
4. (optional) `tasks/eval_detect.py` → your `detect_language` node.

Until wired, CodeGuard columns print `n/a — wire adapter`; the baseline columns
still work. Wire them one at a time and re-run `python run_all.py` after each.

---

## Scaling up to thesis-grade datasets

The bundled `datasets/*.jsonl` are intentionally tiny (just enough to validate the
pipeline). Same format, just add lines:

- **Complexity** → [CodeComplex] / [CoRCoD] — append `{"id", "label", "code"}` rows.
- **SOLID** → *"Are We SOLID Yet?"* benchmark — `{"id", "labels": [...], "code"}`.
- **Smells** → public code-smell datasets — `{"id", "labels": [...], "code"}`.
- **Refactor** → ClassEval + your own held-out snippets — `{"id", "entry", "code", "tests": [{"args", "expects"}]}`.

If a dataset is large, take a **stratified sample** (by language/difficulty/complexity
class) and note the sampling method in your write-up.

## Run a single component

```bash
python -m tasks.eval_solid       # just SOLID
python -m tasks.eval_complexity  # just complexity
python -m tasks.eval_refactor    # just refactoring + gate
python -m ablation.run_ablation  # just the ablation table
```

## Layout

```
eval/
├── run_all.py              # one-command entry point
├── eval_config.yaml        # paths + toggles (env vars override)
├── requirements-eval.txt   # optional extras (core needs only stdlib)
├── adapters/
│   ├── baseline_llm.py     # raw-LLM baseline (OpenAI-compatible; offline stub)
│   └── codeguard_adapter.py# << the only file you wire to your repo (# === WIRE ===)
├── datasets/               # tiny bundled labeled sets (expand these)
├── harness/
│   ├── metrics.py          # F1 / accuracy / tier-tolerant / rates
│   ├── differential.py     # original-vs-refactored behavior diff (mirrors your gate)
│   ├── io_utils.py
│   └── report.py           # Markdown table rendering
├── tasks/                  # one runner per component
├── ablation/               # 3-rung ablation aggregator
└── results/                # REPORT.md + results.json (generated)
```

## Safety note

`harness/differential.py` runs dataset code **in-process** for speed. Only point it
at code you trust (your own eval snippets). For untrusted input, route the refactor
task through your existing Docker executor instead.

## Notes for the defense

- The harness recomputes every verdict in code (no LLM judges) — same philosophy as
  CodeGuard's deterministic control plane, so the evaluation itself is reproducible.
- Report **where you beat both baselines** (expect DIP/LSP detection + refactor safety),
  and include a **failure-case analysis** + threats to validity (dataset size, Python-only scope).
