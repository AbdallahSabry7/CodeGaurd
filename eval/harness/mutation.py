"""Behavior-changing mutation injection -- to STRESS-TEST the verification gate.

A gate is a classifier; you cannot measure its catch/escape rate without
genuinely unsafe candidates to catch. Natural LLM refactors rarely break tiny
snippets, so we synthesise candidate 'refactors' by mutating the source. The
caller keeps only mutants the oracle CONFIRMS actually change behavior, giving a
controlled positive class for an honest confusion matrix.
"""
from __future__ import annotations

import re

# (pattern, replacement) -- first occurrence only, applied to a copy each time.
_OP_SWAPS = [
    ("==", "!="),
    (">=", ">"),
    ("<=", "<"),
    (" + ", " - "),
    (" > ", " < "),
    ("%", "//"),
]


def candidate_mutants(code: str) -> list[str]:
    """Return a list of plausibly behavior-changing variants of `code`."""
    mutants: list[str] = []

    for needle, repl in _OP_SWAPS:
        idx = code.find(needle)
        if idx != -1:
            mutants.append(code[:idx] + repl + code[idx + len(needle):])

    # off-by-one on the first range(...) bound
    m = re.search(r"range\(([^)]*)\)", code)
    if m:
        mutants.append(code.replace(m.group(0), f"range({m.group(1)} + 1)", 1))

    # flip a boolean return
    if "return True" in code:
        mutants.append(code.replace("return True", "return False", 1))
    elif "return False" in code:
        mutants.append(code.replace("return False", "return True", 1))

    # de-duplicate and drop no-ops
    seen = set()
    out = []
    for mut in mutants:
        if mut != code and mut not in seen:
            seen.add(mut)
            out.append(mut)
    return out
