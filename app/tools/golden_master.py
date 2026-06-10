# app/services/golden_master.py
"""
Boundary-level behavioral equivalence via a golden master (characterization test).

Principle: measure behavior at the *boundary*, never inside. Snapshot what the
ORIGINAL does on a suite of inputs ONCE, then replay the same inputs against each
refactor and compare. Internal renames / splits / additions are invisible.

One primitive: "run a script with stdin, capture stdout".
  - stdio mode : script == the analyzed code;        stdin == a sample input
  - api   mode : script == code + an LLM driver that reads JSON args from stdin,
                 calls the PUBLIC functions, and prints results
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable


# --------------------------------------------------------------------------- #
# Result types (pure data)
# --------------------------------------------------------------------------- #
@dataclass
class Divergence:
    case: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return (f"  - case '{self.case}': expected {self.expected!r}, "
                f"got {self.actual!r}")


@dataclass
class EquivalenceResult:
    status: str = "preserved"          # "preserved" | "changed" | "unverified"
    checked: list[str] = field(default_factory=list)
    divergences: list[Divergence] = field(default_factory=list)
    reason: str = ""                    # why unverified, when applicable

    @property
    def preserved(self) -> bool:
        return self.status == "preserved"

    @property
    def report(self) -> str:
        if self.status == "preserved":
            return (f"Behavior preserved across {len(self.checked)} case(s): "
                    f"{', '.join(self.checked)}.")
        if self.status == "unverified":
            return f"Behavior UNVERIFIED - {self.reason}"
        lines = ["Behavior CHANGED - the refactor is not equivalent:"]
        lines += [str(d) for d in self.divergences]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Runner: the one I/O primitive. Deterministic, swappable for the Docker sandbox.
# --------------------------------------------------------------------------- #
@dataclass
class RunOutcome:
    stdout: str
    kind: str        # "" on clean exit, else the exception type name
    ok: bool


def _classify(stderr: str) -> str:
    """Reduce a traceback to its exception type, so we compare *kind* not message
    text (messages embed line numbers / names that legitimately change)."""
    lines = stderr.strip().splitlines()
    if not lines:
        return "Error"
    return lines[-1].split(":", 1)[0].strip() or "Error"


def _local_runner(code: str, stdin: str, *, timeout: float = 10.0) -> RunOutcome:
    """Reference runner: a fresh, isolated python subprocess.
    For untrusted input, pass your Docker-backed runner instead (see `Runner`)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            input=stdin, capture_output=True, text=True, timeout=timeout,
        )
        kind = "" if proc.returncode == 0 else _classify(proc.stderr)
        return RunOutcome(proc.stdout.strip(), kind, proc.returncode == 0)
    except subprocess.TimeoutExpired:
        return RunOutcome("", "Timeout", False)


# A runner takes (code, stdin) -> RunOutcome. Inject the Docker sandbox here.
Runner = Callable[[str, str], RunOutcome]


# --------------------------------------------------------------------------- #
# Golden master
# --------------------------------------------------------------------------- #
@dataclass
class GoldenMaster:
    mode: str                  # "stdio" | "api"
    driver: str                # api-mode harness suffix; "" for stdio
    cases: list[dict]          # [{"name": str, "stdin": str}]
    observations: dict         # name -> {"stdout": str, "kind": str, "ok": bool}

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @staticmethod
    def from_json(s: str) -> "GoldenMaster":
        return GoldenMaster(**json.loads(s))


def _script_for(code: str, mode: str, driver: str) -> str:
    return code if mode == "stdio" else f"{code}\n\n{driver}"


def capture(original_code: str, spec: dict, *, runner: Runner = _local_runner) -> GoldenMaster:
    """Run the ORIGINAL once per case and freeze its observations."""
    mode = spec.get("mode", "stdio")
    driver = spec.get("driver", "") or ""
    cases = spec.get("cases", []) or []
    observations: dict = {}
    for case in cases:
        name, stdin = case["name"], case.get("stdin", "")
        out = runner(_script_for(original_code, mode, driver), stdin)
        observations[name] = {"stdout": out.stdout, "kind": out.kind, "ok": out.ok}
    return GoldenMaster(mode, driver, cases, observations)


def replay(refactored_code: str, gm: GoldenMaster, *, runner: Runner = _local_runner) -> EquivalenceResult:
    """Replay the frozen cases against the refactored code and compare."""
    if not gm.cases:
        return EquivalenceResult(status="unverified",
                                 reason="no behavioral cases could be generated.")
    runnable = [c for c in gm.cases if gm.observations.get(c["name"], {}).get("ok")]
    if not runnable:
        return EquivalenceResult(status="unverified",
                                 reason="the original produced no successful run on any case.")

    result = EquivalenceResult()
    for case in gm.cases:
        name = case["name"]
        gold = gm.observations[name]
        if not gold["ok"]:
            continue                       # only pin cases the original handled cleanly
        out = runner(_script_for(refactored_code, gm.mode, gm.driver), case.get("stdin", ""))
        result.checked.append(name)
        if out.stdout != gold["stdout"] or out.kind != gold["kind"]:
            exp = gold["stdout"] if gold["kind"] == "" else f"<{gold['kind']}>"
            act = out.stdout if out.kind == "" else f"<{out.kind}>"
            result.divergences.append(Divergence(name, exp, act))

    result.status = "changed" if result.divergences else "preserved"
    return result