"""SOLID task: CodeGuard AST detectors vs raw-LLM baseline.

Metric: per-principle + macro precision/recall/F1 (watch DIP/LSP — your edge).
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from harness import metrics
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct

LABELS = ["SRP", "OCP", "LSP", "ISP", "DIP"]


def _table(name: str, scores: dict):
    rows = []
    for p in LABELS:
        s = scores["per_label"][p]
        rows.append([p, pct(s["precision"]), pct(s["recall"]), pct(s["f1"])])
    rows.append(["**macro**", pct(scores["macro"]["precision"]), pct(scores["macro"]["recall"]), pct(scores["macro"]["f1"])])
    return f"### {name}\n\n" + md_table(["Principle", "Precision", "Recall", "F1"], rows)


def run() -> dict:
    data = load_jsonl("datasets/solid.jsonl")
    gold = [r["labels"] for r in data]

    base_pred = [baseline_llm.predict_solid(r["code"], LABELS) for r in data]
    base = metrics.multilabel_scores(base_pred, gold, LABELS)
    result = {"n": len(data), "baseline": base}

    sections = ["## SOLID violation detection\n\n" + f"Dataset size: {len(data)}", _table("Raw LLM (baseline)", base)]

    if codeguard_adapter.pipeline_available():
        cg_pred = [codeguard_adapter.analyze(r["code"])["solid"] for r in data]
        cg = metrics.multilabel_scores(cg_pred, gold, LABELS)
        result["codeguard"] = cg
        sections.append(_table("CodeGuard (AST detectors)", cg))
    else:
        result["codeguard"] = None
        sections.append("### CodeGuard (AST detectors)\n\nn/a — wire the adapter to enable.")

    append_section("\n\n".join(sections))
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
