
"""
Lightweight behavioral regression check.

Run the ORIGINAL and the REFACTORED code on the SAME inputs, live, and diff
their observable behavior (stdout + exception kind). No stored snapshot, so
nothing can go stale. The LLM only SUGGESTS inputs; the comparison is ==.
"""
from __future__ import annotations
import subprocess, sys
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class RunOutcome:
    stdout: str
    kind: str        # "" on clean exit, else the exception type name
    ok: bool

def _classify(stderr: str) -> str:
    lines = stderr.strip().splitlines()
    if not lines:
        return "Error"
    return lines[-1].split(":", 1)[0].strip() or "Error"

def _local_runner(code: str, stdin: str, *, timeout: float = 10.0) -> RunOutcome:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input=stdin, capture_output=True, text=True, timeout=timeout,
        )
        kind = "" if proc.returncode == 0 else _classify(proc.stderr)
        return RunOutcome(proc.stdout.strip(), kind, proc.returncode == 0)
    except subprocess.TimeoutExpired:
        return RunOutcome("", "Timeout", False)

Runner = Callable[[str, str], RunOutcome]

def _script_for(code: str, mode: str, driver: str) -> str:
    return code if mode == "stdio" else f"{code}\n\n{driver}"

@dataclass
class RegressionResult:
    verdict: str = "SAME"             # "SAME" | "DIFFERENT" | "INCONCLUSIVE"
    checked: list[str] = field(default_factory=list)
    counterexample: str = ""
    expected: str = ""
    got: str = ""
    reason: str = ""

    @property
    def report(self) -> str:
        if self.verdict == "SAME":
            return f"Behavior preserved across {len(self.checked)} case(s)."
        if self.verdict == "INCONCLUSIVE":
            return f"Behavior UNVERIFIED — {self.reason}"
        return (f"Behavior CHANGED on case '{self.counterexample}': "
                f"expected {self.expected!r}, got {self.got!r}")

def differential_check(original: str, refactored: str, cases: list[dict],
                       mode: str = "stdio", driver: str = "",
                       *, runner: Runner = _local_runner) -> RegressionResult:
    """Run BOTH versions live on the same inputs and compare."""
    if not cases:
        return RegressionResult(verdict="INCONCLUSIVE", reason="no test inputs generated")

    res = RegressionResult()
    ran_any = False
    for case in cases:
        name, stdin = case["name"], case.get("stdin", "")
        before = runner(_script_for(original, mode, driver), stdin)
        if not before.ok:
            continue                       # only pin cases the original handled cleanly
        ran_any = True
        after = runner(_script_for(refactored, mode, driver), stdin)
        res.checked.append(name)
        if before.stdout != after.stdout or before.kind != after.kind:
            res.verdict = "DIFFERENT"
            res.counterexample = name
            res.expected = before.stdout if before.kind == "" else f"<{before.kind}>"
            res.got = after.stdout if after.kind == "" else f"<{after.kind}>"
            return res

    if not ran_any:
        return RegressionResult(verdict="INCONCLUSIVE",
                                reason="original produced no clean run on any input")
    return res