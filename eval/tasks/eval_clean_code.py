"""Clean-code / smell task: CodeGuard vs raw-LLM baseline.

Metric: per-smell + macro precision/recall/F1.
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from harness import metrics
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct

LABELS = ["long_method", "long_parameter_list", "magic_number"]


def _table(name: str, scores: dict):
    rows = []
    for p in LABELS:
        s = scores["per_label"][p]
        rows.append([p, pct(s["precision"]), pct(s["recall"]), pct(s["f1"])])
    rows.append(["**macro**", pct(scores["macro"]["precision"]), pct(scores["macro"]["recall"]), pct(scores["macro"]["f1"])])
    return f"### {name}\n\n" + md_table(["Smell", "Precision", "Recall", "F1"], rows)


def run() -> dict:
    data = load_jsonl("datasets/smells.jsonl")
    gold = [r["labels"] for r in data]

    base_pred = [baseline_llm.predict_smells(r["code"], LABELS) for r in data]
    base = metrics.multilabel_scores(base_pred, gold, LABELS)
    result = {"n": len(data), "baseline": base}

    sections = ["## Clean-code / smell detection\n\n" + f"Dataset size: {len(data)}", _table("Raw LLM (baseline)", base)]

    if codeguard_adapter.pipeline_available():
        cg_pred = [codeguard_adapter.analyze(r["code"])["smells"] for r in data]
        cg = metrics.multilabel_scores(cg_pred, gold, LABELS)
        result["codeguard"] = cg
        sections.append(_table("CodeGuard", cg))
    else:
        result["codeguard"] = None
        sections.append("### CodeGuard\n\nn/a — wire the adapter to enable.")

    append_section("\n\n".join(sections))
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
