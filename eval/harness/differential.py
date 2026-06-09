"""A self-contained differential behavior checker (mirrors CodeGuard's gate).

Given original + candidate source and a list of {args, expects} cases, it:
  - runs the candidate's `entry` function on each case and records the observation
    (return value OR exception type name),
  - compares candidate-vs-gold (test-pass) AND candidate-vs-original (behavior
    preserved),
  - returns a verdict: preserved / changed / unverified.

Execution is in-process with a restricted namespace. This is a smoke test, not a
sandbox — only run code you trust (your own datasets). For untrusted code, route
through your Docker executor instead.
"""
from __future__ import annotations

import traceback
from typing import Any


def _observe(code: str, entry: str, args: list) -> tuple[str, Any]:
    """Return ('ok', value) or ('exc', ExceptionTypeName)."""
    ns: dict = {}
    try:
        exec(compile(code, "<cand>", "exec"), ns)
        fn = ns.get(entry)
        if fn is None:
            return ("exc", "MissingEntry")
        val = fn(*args)
        return ("ok", val)
    except Exception as exc:  # noqa: BLE001 - we intentionally capture all
        return ("exc", type(exc).__name__)


def check(original: str, candidate: str, entry: str, cases: list[dict]) -> dict:
    test_pass = 0
    behavior_preserved = True
    any_ran = False
    details = []
    for case in cases:
        args = case.get("args", [])
        gold = case.get("expects")
        o_kind, o_val = _observe(original, entry, args)
        c_kind, c_val = _observe(candidate, entry, args)
        if o_kind == "ok":
            any_ran = True
        # test-pass: candidate matches the declared gold
        passed = (c_kind == "ok" and c_val == gold)
        test_pass += int(passed)
        # behavior preserved: candidate matches the ORIGINAL on the same input
        same = (o_kind == c_kind) and (o_val == c_val if o_kind == "ok" else True)
        if not same:
            behavior_preserved = False
        details.append({"args": args, "orig": [o_kind, o_val], "cand": [c_kind, c_val], "passed": passed, "same": same})

    if not any_ran:
        verdict = "unverified"
    elif behavior_preserved:
        verdict = "preserved"
    else:
        verdict = "changed"
    return {
        "verdict": verdict,
        "test_pass": test_pass,
        "n_cases": len(cases),
        "behavior_preserved": behavior_preserved,
        "details": details,
    }
