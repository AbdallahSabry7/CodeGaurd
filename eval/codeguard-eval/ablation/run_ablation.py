"""Ablation: quantify each layer's contribution to the thesis claim.

Configurations (the classic 3-rung ablation from the evaluation plan):
  1. LLM-only            — raw LLM, no AST detectors, no verification gate.
  2. LLM + AST           — your symbolic detectors, still no verification.
  3. LLM + AST + gate    — full CodeGuard (the headline system).

For analysis tasks (SOLID/smells/complexity) rungs 2 and 3 are identical
(the gate only affects refactoring), so the analyzer columns show the AST
contribution and the refactor column shows the gate contribution.

This reuses the per-task runners and just reads their result dicts.
"""
from __future__ import annotations

from harness.report import append_section, md_table, pct
from tasks import eval_solid, eval_clean_code, eval_complexity, eval_refactor


def _f1(task_result, system):
    block = task_result.get(system)
    if not block:
        return None
    return block.get("macro", {}).get("f1")


def run(precomputed: dict | None = None) -> dict:
    r = precomputed or {}
    solid = r.get("solid") or eval_solid.run()
    smells = r.get("clean_code") or eval_clean_code.run()
    comp = r.get("complexity") or eval_complexity.run()
    refac = r.get("refactor") or eval_refactor.run()

    def cell(v):
        return pct(v) if isinstance(v, (int, float)) else "n/a"

    # Macro-F1 for detection tasks; exact-acc for complexity; preserved-rate for refactor.
    base_solid = _f1(solid, "baseline")
    cg_solid = _f1(solid, "codeguard")
    base_smell = _f1(smells, "baseline")
    cg_smell = _f1(smells, "codeguard")
    base_comp = (comp.get("baseline") or {}).get("exact")
    cg_comp = (comp.get("codeguard") or {}).get("exact")
    base_ref = (refac.get("baseline") or {}).get("behavior_preserved_rate")
    cg_ref = (refac.get("codeguard") or {}).get("behavior_preserved_rate")

    rows = [
        ["1. LLM-only", cell(base_solid), cell(base_smell), cell(base_comp), cell(base_ref)],
        ["2. LLM + AST", cell(cg_solid), cell(cg_smell), cell(cg_comp), cell(base_ref)],
        ["3. LLM + AST + gate (full)", cell(cg_solid), cell(cg_smell), cell(cg_comp), cell(cg_ref)],
    ]
    append_section(
        "## Ablation — contribution of each layer\n\n"
        + md_table(
            ["Configuration", "SOLID macro-F1", "Smell macro-F1", "Complexity exact-acc", "Refactor behavior-preserved"],
            rows,
        )
        + "\n\n_Rows 2→3 isolate the verification gate; rows 1→2 isolate the AST detectors._"
    )
    return {"solid": solid, "clean_code": smells, "complexity": comp, "refactor": refac}


if __name__ == "__main__":
    run()
