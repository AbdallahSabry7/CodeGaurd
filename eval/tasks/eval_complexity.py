"""Complexity task: CodeGuard symbolic analyzer vs raw-LLM baseline.

Metric: exact-tier accuracy + within-one-tier accuracy.
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from harness import metrics
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct


def run() -> dict:
    data = load_jsonl("datasets/complexity.jsonl")
    gold = [r["label"] for r in data]

    base_pred = [baseline_llm.predict_complexity(r["code"]) for r in data]
    base = metrics.complexity_scores(base_pred, gold)

    result = {"n": len(data), "baseline": base}

    rows = [["Raw LLM (baseline)", pct(base["exact"]), pct(base["within_one_tier"])]]

    if codeguard_adapter.pipeline_available():
        cg_pred = [codeguard_adapter.analyze(r["code"])["complexity"] for r in data]
        cg = metrics.complexity_scores(cg_pred, gold)
        result["codeguard"] = cg
        rows.append(["CodeGuard (AST)", pct(cg["exact"]), pct(cg["within_one_tier"])])
    else:
        result["codeguard"] = None
        rows.append(["CodeGuard (AST)", "n/a — wire adapter", "n/a"])

    append_section(
        "## Complexity (Big-O classification)\n\n"
        + f"Dataset size: {len(data)}\n\n"
        + md_table(["System", "Exact-tier acc", "Within-1-tier acc"], rows)
    )
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
