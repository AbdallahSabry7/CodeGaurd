"""Differential behavior checking, backed by the isolated executor + oracle.

`check()` keeps the original return keys for backward compatibility, but now:
  * compares candidate-vs-original on SEED + GENERATED inputs (not seed only),
  * runs each side in a separate process with a timeout (infinite loop ->
    'changed', never a hang),
  * keeps test-pass (vs declared gold) and behavior-preserved (vs original)
    strictly separate.

`compare()` is the low-level primitive reused by the gate stress test: it
returns a per-input match list so callers can derive a verdict at any input
budget (seed-only vs +k generated) from a single pair of executions.
"""
from __future__ import annotations

from .executor import observe_many, signature
from .oracle import build_input_set


def compare(original: str, candidate: str, entry: str, all_args: list, timeout: float = 5.0):
    """Return (matches: list[bool], orig_runnable: int) across `all_args`."""
    o = observe_many(original, entry, all_args, timeout)
    c = observe_many(candidate, entry, all_args, timeout)
    matches = [signature(o[i]) == signature(c[i]) for i in range(len(all_args))]
    orig_runnable = sum(1 for ob in o if ob.get("status") in ("ok", "exc"))
    return matches, orig_runnable


def verdict_from(matches_subset: list, orig_runnable: int) -> str:
    if orig_runnable == 0:
        return "unverified"
    return "preserved" if all(matches_subset) else "changed"


def check(original: str, candidate: str, entry: str, cases: list[dict],
          n_generated: int = 30, timeout: float = 5.0) -> dict:
    seed_args, gen_args = build_input_set(cases, n_generated)
    all_args = seed_args + gen_args
    n_seed = len(seed_args)

    o = observe_many(original, entry, all_args, timeout)
    c = observe_many(candidate, entry, all_args, timeout)

    gold_reprs = [repr(case.get("expects")) for case in cases]
    test_pass = 0
    for i in range(n_seed):
        if c[i].get("status") == "ok" and c[i].get("value_repr") == gold_reprs[i]:
            test_pass += 1

    matches = [signature(o[i]) == signature(c[i]) for i in range(len(all_args))]
    orig_runnable = sum(1 for ob in o if ob.get("status") in ("ok", "exc"))
    mismatches = matches.count(False)
    first_div = None
    for i, ok in enumerate(matches):
        if not ok:
            first_div = {"args": all_args[i],
                         "orig": signature(o[i]), "cand": signature(c[i])}
            break

    verdict = verdict_from(matches, orig_runnable)
    return {
        "verdict": verdict,
        "test_pass": test_pass,
        "n_cases": n_seed,
        "behavior_preserved": verdict == "preserved",
        "checked_inputs": len(all_args),
        "mismatches": mismatches,
        "first_divergence": first_div,
    }
