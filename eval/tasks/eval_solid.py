"""SOLID task: compare 3 systems.

1) Raw-LLM baseline
2) CodeGuard AST detectors (services/*)
3) CodeGuard AST + Architect (architect_report)

Metric: per-principle + macro precision/recall/F1.
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from adapters import codeguard_architect_adapter
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

    # 1) Raw LLM baseline
    base_pred = [baseline_llm.predict_solid(r["code"], LABELS) for r in data]
    base = metrics.multilabel_scores(base_pred, gold, LABELS)

    sections = ["## SOLID violation detection\n\n" + f"Dataset size: {len(data)}", _table("Raw LLM (baseline)", base)]
    result = {"n": len(data), "baseline": base}

    # 2) AST-only
    if codeguard_adapter.pipeline_available():
        ast_pred = [codeguard_adapter.analyze(r["code"])["solid"] for r in data]
        ast_scores = metrics.multilabel_scores(ast_pred, gold, LABELS)
        result["codeguard_ast"] = ast_scores
        sections.append(_table("CodeGuard (AST detectors)", ast_scores))
    else:
        result["codeguard_ast"] = None
        sections.append("### CodeGuard (AST detectors)\n\nn/a — wire adapters/codeguard_adapter.py")

    # 3) AST + Architect
    if codeguard_architect_adapter.pipeline_available():
        arch_pred = [codeguard_architect_adapter.analyze_with_architect(r["code"])["solid"] for r in data]
        arch_scores = metrics.multilabel_scores(arch_pred, gold, LABELS)
        result["codeguard_ast_architect"] = arch_scores
        sections.append(_table("CodeGuard (AST + Architect)", arch_scores))
    else:
        result["codeguard_ast_architect"] = None
        sections.append(
            "### CodeGuard (AST + Architect)\n\n"
            "n/a — set CODEGUARD_APP_DIR and ensure OPENROUTER_API_KEY is available for Architect.\n\n"
            f"Import error: `{codeguard_architect_adapter.import_error()}`"
        )

    append_section("\n\n".join(sections))
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))