"""Ablation: attribute results to CodeGuard's layers using ALREADY-computed
results, so rungs are real measurements rather than fabricated numbers.

Rungs
-----
  Rung 1  Raw LLM only          : analysis = baseline columns;
                                   refactor safety = WEAK gate (seed tests only).
  Rung 2  LLM + AST detectors    : analysis = CodeGuard columns (deterministic
                                   AST analyzers); refactor safety still WEAK gate.
  Rung 3  LLM + AST + Gate (full): analysis = CodeGuard columns;
                                   refactor safety = STRONG gate (generated inputs).

Reading it
----------
  * Rung 1 -> 2 isolates the AST detectors' effect on ANALYSIS accuracy.
  * Rung 2 -> 3 isolates the GATE's effect on REFACTOR escape rate
    (same candidates, only the verification policy changes).
When the real pipeline is unwired, analysis CodeGuard cells show 'n/a' but the
gate rungs are still real, because the gate stress test needs no LLM/app.
"""
from __future__ import annotations

from harness.report import append_section, md_table, pct


def _f1(res_block):
    if not res_block:
        return None
    return res_block["macro_supported"]["f1"]


def _fmt(x):
    return pct(x) if isinstance(x, (int, float)) else "n/a"


def run(results: dict) -> dict:
    solid = results.get("solid", {})
    smells = results.get("smells", {})
    complexity = results.get("complexity", {})
    refactor = results.get("refactor", {})

    base_solid = _f1(solid.get("baseline"))
    cg_solid = _f1(solid.get("codeguard"))
    base_smell = _f1(smells.get("baseline"))
    cg_smell = _f1(smells.get("codeguard"))
    base_cx = (complexity.get("baseline") or {}).get("exact")
    cg_cx = (complexity.get("codeguard") or {}).get("exact")

    gate = refactor.get("gate", {})
    weak_escape = gate.get("weak", {}).get("escape_rate")
    strong_escape = gate.get("strong", {}).get("escape_rate")

    rows = [
        ["Rung 1: LLM only", _fmt(base_solid), _fmt(base_smell), _fmt(base_cx), _fmt(weak_escape)],
        ["Rung 2: LLM + AST detectors", _fmt(cg_solid), _fmt(cg_smell), _fmt(cg_cx), _fmt(weak_escape)],
        ["Rung 3: + Verification gate", _fmt(cg_solid), _fmt(cg_smell), _fmt(cg_cx), _fmt(strong_escape)],
    ]
    table = md_table(
        ["Configuration", "SOLID Macro-F1", "Smell Macro-F1", "Complexity Exact", "Refactor Escape rate"],
        rows,
    )
    append_section(
        "## Ablation study\n\n"
        "Each rung adds one CodeGuard layer. Rung1->2 isolates the AST detectors "
        "(analysis columns); rung2->3 isolates the gate (escape rate, same candidates).\n\n"
        + table
    )
    return {"rungs": rows}
