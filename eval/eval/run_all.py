#!/usr/bin/env python3
"""Run every CodeGuard evaluation task and write results/REPORT.md + results.json.

Usage:
    python run_all.py                      # offline-safe; stub baseline if no key
    OPENROUTER_API_KEY=... python run_all.py
    CODEGUARD_APP_DIR=/path/to/app python run_all.py
    CODEGUARD_EVAL_REQUIRE_LLM=1 python run_all.py   # fail instead of stubbing

The harness core is standard-library only. It ALWAYS runs end-to-end; columns it
cannot really measure are shown as 'n/a' and the run mode is printed loudly so
stub numbers are never mistaken for real results.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters import baseline_llm  # noqa: E402
from adapters import codeguard_adapter as cg  # noqa: E402
from harness.io_utils import load_jsonl, write_json, RESULTS_DIR  # noqa: E402
from harness.report import append_section, reset_report  # noqa: E402
from tasks import eval_complexity, eval_solid, eval_clean_code, eval_refactor  # noqa: E402
from ablation import run_ablation  # noqa: E402


def _baseline_mode() -> str:
    return "LIVE LLM" if baseline_llm._provider_config() else "OFFLINE STUB (heuristic, NOT a baseline)"


def _banner() -> str:
    cg_ok = cg.pipeline_available()
    lines = [
        "## Run configuration",
        "",
        f"- Baseline mode: **{_baseline_mode()}**",
        f"- CodeGuard pipeline: **{'WIRED' if cg_ok else 'NOT WIRED'}**",
    ]
    if not cg_ok:
        lines.append(f"  - import status: {cg.import_error() or 'services not found'}")
        lines.append("  - CodeGuard analysis columns will show 'n/a'. Set CODEGUARD_APP_DIR and wire adapters/codeguard_adapter.py.")
    if _baseline_mode().startswith("OFFLINE"):
        lines.append("  - No LLM key set: baseline uses deterministic stubs. Set OPENROUTER_API_KEY or GROQ_API_KEY for a real baseline.")
    lines.append("")
    lines.append("> The verification-gate confusion matrix (refactor Part 2) is fully measured even offline.")
    return "\n".join(lines)


def main() -> int:
    reset_report()
    append_section(_banner())

    results = {}
    results["complexity"] = eval_complexity.run(load_jsonl("datasets/complexity.jsonl"))
    results["solid"] = eval_solid.run(load_jsonl("datasets/solid.jsonl"))
    results["smells"] = eval_clean_code.run(load_jsonl("datasets/smells.jsonl"))
    results["refactor"] = eval_refactor.run(load_jsonl("datasets/refactor.jsonl"))
    results["ablation"] = run_ablation.run(results)

    write_json("results.json", results)

    print("=" * 64)
    print(f" Baseline mode    : {_baseline_mode()}")
    print(f" CodeGuard wired  : {cg.pipeline_available()}")
    print(f" Report           : {os.path.join(RESULTS_DIR, 'REPORT.md')}")
    print(f" Machine results  : {os.path.join(RESULTS_DIR, 'results.json')}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
