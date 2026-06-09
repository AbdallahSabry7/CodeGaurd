"""Refactor task: does a refactor keep behavior, and does the gate catch breaks?

Compares:
  - Raw LLM (baseline): refactor with no verification.
  - CodeGuard (full): refactor through your graph WITH the equivalence gate
    (only enabled when the adapter wires in build_graph).

Metrics: test-pass rate, behavior-preserved rate, and — for CodeGuard — the
% of unsafe refactors blocked by the gate (your safety win).
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from harness import metrics
from harness.differential import check
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct


def _eval_system(data, refactor_fn, uses_gate: bool) -> dict:
    test_pass = 0
    preserved = 0
    blocked = 0
    total_cases = 0
    n = len(data)
    for r in data:
        original = r["code"]
        entry = r["entry"]
        cases = r["tests"]
        total_cases += len(cases)
        out = refactor_fn(original)
        if isinstance(out, tuple):
            candidate, gate_verdict = out
        else:
            candidate, gate_verdict = out, None
        candidate = candidate or original
        res = check(original, candidate, entry, cases)
        test_pass += res["test_pass"]
        if res["verdict"] == "preserved":
            preserved += 1
        # A gate "blocks" when it reported `changed` and looped/rejected.
        if uses_gate and gate_verdict == "changed":
            blocked += 1
    return {
        "n": n,
        "test_pass_rate": metrics.rate(test_pass, total_cases),
        "behavior_preserved_rate": metrics.rate(preserved, n),
        "gate_blocked_rate": metrics.rate(blocked, n) if uses_gate else None,
    }


def run() -> dict:
    data = load_jsonl("datasets/refactor.jsonl")
    base = _eval_system(data, baseline_llm.refactor, uses_gate=False)
    result = {"baseline": base}

    rows = [[
        "Raw LLM (no verification)",
        pct(base["test_pass_rate"]),
        pct(base["behavior_preserved_rate"]),
        "—",
    ]]

    full = codeguard_adapter.refactor_full
    # Probe whether the full graph is wired in.
    probe = full(data[0]["code"]) if data else None
    if probe is not None:
        cg = _eval_system(data, full, uses_gate=True)
        result["codeguard"] = cg
        rows.append([
            "CodeGuard (full + gate)",
            pct(cg["test_pass_rate"]),
            pct(cg["behavior_preserved_rate"]),
            pct(cg["gate_blocked_rate"]) if cg["gate_blocked_rate"] is not None else "—",
        ])
    else:
        result["codeguard"] = None
        why = codeguard_adapter.refactor_error() or "wire build_graph"
        rows.append([f"CodeGuard (full + gate) — n/a: {why}", "n/a", "n/a", "n/a"])

    append_section(
        "## Refactoring (behavior preservation)\n\n"
        + f"Dataset size: {len(data)} snippets\n\n"
        + md_table(["System", "Test-pass rate", "Behavior-preserved rate", "Gate-blocked rate"], rows)
        + "\n\n_Behavior-preserved = refactored output matches the original on every checked input._"
    )
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
