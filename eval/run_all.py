#!/usr/bin/env python3
"""One command to evaluate every part of CodeGuard against its baseline.

Usage (from the eval/ folder):
    python run_all.py

Outputs:
    results/REPORT.md   — human-readable tables, per component
    results/results.json — machine-readable raw numbers

No API key needed to smoke-test the harness (offline stubs kick in). To run the
REAL raw-LLM baseline, set GROQ_API_KEY or OPENROUTER_API_KEY (and optionally
BASELINE_MODEL). To enable the CodeGuard columns, wire adapters/codeguard_adapter.py.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters import baseline_llm, codeguard_adapter  # noqa: E402
from harness.report import reset_report, append_section  # noqa: E402
from harness.io_utils import write_json  # noqa: E402
from tasks import (  # noqa: E402
    eval_detect,
    eval_complexity,
    eval_solid,
    eval_clean_code,
    eval_refactor,
)
from ablation import run_ablation  # noqa: E402


def _status_banner() -> str:
    llm = baseline_llm._provider_config()
    llm_mode = "REAL ({})".format(llm[2]) if llm else "OFFLINE STUB (set GROQ/OPENROUTER key)"
    cg = "WIRED" if codeguard_adapter.pipeline_available() else "NOT WIRED (" + (codeguard_adapter.import_error() or "adapter returns stub") + ")"
    return (
        "## Run configuration\n\n"
        f"- Baseline LLM: **{llm_mode}**\n"
        f"- CodeGuard pipeline: **{cg}**\n"
    )


def main() -> int:
    reset_report()
    append_section(_status_banner())

    results = {}
    print("[1/5] language detection ...")
    results["detect"] = eval_detect.run()
    print("[2/5] complexity ...")
    results["complexity"] = eval_complexity.run()
    print("[3/5] SOLID ...")
    results["solid"] = eval_solid.run()
    print("[4/5] clean code / smells ...")
    results["clean_code"] = eval_clean_code.run()
    print("[5/5] refactoring + behavioral gate ...")
    results["refactor"] = eval_refactor.run()

    print("[ablation] aggregating ...")
    run_ablation.run(precomputed=results)

    path = write_json("results.json", results)
    print("\nDone.")
    print("  - Markdown report: results/REPORT.md")
    print(f"  - Raw JSON:        {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
