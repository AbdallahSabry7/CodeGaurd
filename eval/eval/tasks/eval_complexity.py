"""Task: time-complexity classification (baseline LLM vs CodeGuard)."""
from __future__ import annotations

from adapters import baseline_llm
from adapters import codeguard_adapter as cg
from harness import metrics
from harness.report import append_section, md_table, pct, pct_ci


def _score(pred, gold):
    return metrics.complexity_scores(pred, gold)


def run(rows: list[dict]) -> dict:
    gold = [r["label"] for r in rows]
    base_pred = [baseline_llm.predict_complexity(r["code"]) for r in rows]
    base = _score(base_pred, gold)

    cg_res = None
    if cg.pipeline_available():
        cg_pred = [cg.analyze(r["code"]).get("complexity", "") for r in rows]
        cg_res = _score(cg_pred, gold)

    def row(name, s):
        if s is None:
            return [name, "n/a - wire adapter", "n/a", "-"]
        ci = s.get("exact_ci", [0, 0])
        return [name, pct_ci(s["exact"], ci[0], ci[1]), pct(s["within_one_tier"]), s["n"]]

    table = md_table(
        ["System", "Exact [95% CI]", "Within 1 tier", "n"],
        [row("Raw LLM baseline", base), row("CodeGuard", cg_res)],
    )
    append_section("## Time-complexity classification\n\n" + table)
    return {"n": len(rows), "baseline": base, "codeguard": cg_res}
