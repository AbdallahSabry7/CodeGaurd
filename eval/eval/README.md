# CodeGuard - Evaluation Harness (v2)

A self-contained, **standard-library-only** harness that measures what CodeGuard
actually claims: better static analysis than a raw LLM, and **refactoring that
does not change behavior**. It runs end-to-end offline; columns it cannot truly
measure are shown as `n/a` rather than faked.

```bash
cd eval
python run_all.py                       # offline-safe smoke run
OPENROUTER_API_KEY=sk-... python run_all.py     # real LLM baseline
CODEGUARD_APP_DIR=/abs/path/to/app python run_all.py   # real pipeline
```

Outputs: `results/REPORT.md` (human) and `results/results.json` (machine).

## What each task measures

| Task | Metric | File |
|---|---|---|
| Time complexity | Exact + within-1-tier accuracy, 95% CI | `tasks/eval_complexity.py` |
| SOLID violations | Per-label P/R/F1 + macro(supported)/micro | `tasks/eval_solid.py` |
| Code smells | Per-label P/R/F1 + macro(supported)/micro | `tasks/eval_clean_code.py` |
| Refactoring | Outcome split + **verification-gate confusion matrix** | `tasks/eval_refactor.py` |
| Ablation | Layer-by-layer contribution | `ablation/run_ablation.py` |

## The gate metric (headline)

The verification gate is a binary classifier: **accept** or **block** a
candidate refactor. We score it with a confusion matrix:

| | Truly safe | Truly unsafe |
|---|---|---|
| Gate accepts | correct | **escape** (regression shipped) |
| Gate blocks | over-block (useful work lost) | catch (correct) |

* **Escape rate** = unsafe accepted / all unsafe -> the number to drive toward 0.
* **Catch rate** = unsafe blocked / all unsafe.
* **Over-block rate** = safe blocked / all safe.

Unsafe candidates are synthesised by **mutating** each snippet (kept only when
the oracle confirms the behavior changed), so the gate can be measured even with
no LLM and no wired pipeline.

## Why you were getting 0 in most cells

1. **Offline + unwired run.** With no LLM key the baseline used heuristic stubs
   that predict almost nothing, and with no `CODEGUARD_APP_DIR` the CodeGuard
   columns were `n/a`. Most zeros were "nothing was actually being measured".
2. **Macro-F1 zero-support artifact.** The old macro-F1 averaged in labels that
   have no gold positives, mechanically pinning the average near 0 on tiny data.
   Fixed via `macro_supported` + micro-F1 + per-label support.
3. **Structurally impossible labels.** A function-level smell detector cannot
   emit class-level smells (`god_class`, `dead_code`, `duplicated_code`),
   guaranteeing 0 recall there. Now visible per-label and documented.
4. **No-op scored as success.** An identity "refactor" passed the old check; it
   is now classified as `safe_noop`, separating useful work from safe work.

## Wiring your real pipeline

Edit the 3 `# === WIRE` spots in `adapters/codeguard_adapter.py` and set
`CODEGUARD_APP_DIR` to the folder containing `services/`, `graph/`, `tools/`.
Nothing else in the harness needs to change.

## Scaling the datasets

The bundled datasets are intentionally tiny smoke sets. Swap in public
benchmarks for defensible n: CodeComplex / CoRCoD (complexity), the
"Are We SOLID Yet?" benchmark (SOLID), and an established smell corpus. Keep the
same JSONL shapes (`datasets/*.jsonl`).

## Layout

```
eval/
  run_all.py            orchestrator + run-mode banner
  eval_config.yaml      config (also via env vars)
  adapters/             baseline_llm.py, codeguard_adapter.py
  harness/              metrics, executor (isolated+timeout), oracle, mutation,
                        differential, report, io_utils
  tasks/                one module per task
  ablation/             run_ablation.py
  datasets/             *.jsonl
  results/              REPORT.md, results.json, logs/ (generated)
```
