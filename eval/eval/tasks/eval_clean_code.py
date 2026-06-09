"""Task: code-smell multi-label detection (baseline LLM vs CodeGuard)."""
from __future__ import annotations

from adapters import baseline_llm
from adapters import codeguard_adapter as cg
from harness import metrics
from harness.report import append_section, md_table, pct

LABELS = [
    "long_method",
    "long_parameter_list",
    "god_class",
    "dead_code",
    "duplicated_code",
    "magic_number",
]
TITLE = "Code-smell detection"


def _summary_row(name, s):
    if s is None:
        return [name, "n/a - wire adapter", "n/a", "n/a"]
    return [name, pct(s["macro_supported"]["f1"]), pct(s["micro"]["f1"]), pct(s["macro"]["f1"])]


def _per_label_table(name, s):
    rows = []
    for label in LABELS:
        d = s["per_label"][label]
        rows.append([label, pct(d["precision"]), pct(d["recall"]), pct(d["f1"]), d["support"]])
    return f"\n_Per-label ({name}):_\n\n" + md_table(
        ["Label", "Precision", "Recall", "F1", "Support"], rows
    )


def run(rows: list[dict]) -> dict:
    gold = [set(r["labels"]) for r in rows]
    base_pred = [set(baseline_llm.predict_smells(r["code"], LABELS)) for r in rows]
    base = metrics.multilabel_scores(base_pred, gold, LABELS)

    cg_res = None
    if cg.pipeline_available():
        cg_pred = [set(cg.analyze(r["code"]).get("smells", [])) for r in rows]
        cg_res = metrics.multilabel_scores(cg_pred, gold, LABELS)

    table = md_table(
        ["System", "Macro-F1 (supported)", "Micro-F1", "Macro-F1 (all labels)"],
        [_summary_row("Raw LLM baseline", base), _summary_row("CodeGuard", cg_res)],
    )
    body = "## " + TITLE + "\n\n" + table
    body += _per_label_table("CodeGuard" if cg_res else "Raw LLM baseline", cg_res or base)
    append_section(body)
    return {"n": len(rows), "baseline": base, "codeguard": cg_res}
