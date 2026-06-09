"""Isolated, timed execution of a single function from source code.

Why this exists
---------------
The original differential checker ran candidate code with a bare in-process
`exec` and NO timeout. An infinite loop, a process-killing call, or global-state
contamination would hang or corrupt the whole evaluation instead of being scored
as a behavior change. Here every snippet runs in a SEPARATE python process
(`-I` isolated mode) with a wall-clock timeout. A timeout/crash becomes an
observable behavior, not a hang.

Behavior signature
------------------
For each call we record `(status, value_repr | exc_type, stdout)`:
  * return value via `repr()` (stable, avoids float/`==`/ordering foot-guns),
  * the raised exception TYPE name,
  * captured stdout (so some side-effect changes are observable).
This is intentionally richer than the original (return value only).
"""
from __future__ import annotations

import json
import subprocess
import sys

_MARKER = "\x00R\x00"

_WORKER = r'''
import json, sys, io, contextlib
data = json.loads(sys.stdin.read())
code, entry, arglist = data["code"], data["entry"], data["args_list"]
results = []
try:
    compiled = compile(code, "<candidate>", "exec")
    compile_err = None
except Exception as e:
    compiled, compile_err = None, type(e).__name__
for args in arglist:
    if compiled is None:
        results.append({"status": "exc", "exc": "CompileError:" + str(compile_err), "stdout": ""})
        continue
    ns = {}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compiled, ns)
            fn = ns.get(entry)
            if fn is None:
                results.append({"status": "exc", "exc": "MissingEntry", "stdout": buf.getvalue()})
                continue
            val = fn(*args)
        results.append({"status": "ok", "value_repr": repr(val), "stdout": buf.getvalue()})
    except Exception as e:
        results.append({"status": "exc", "exc": type(e).__name__, "stdout": buf.getvalue()})
sys.stdout.write("\x00R\x00" + json.dumps(results))
'''


def _run(payload: str, timeout: float):
    return subprocess.run(
        [sys.executable, "-I", "-c", _WORKER],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse(raw: str, n: int):
    i = raw.rfind(_MARKER)
    if i == -1:
        return None
    try:
        res = json.loads(raw[i + len(_MARKER):])
    except json.JSONDecodeError:
        return None
    return res if len(res) == n else None


def _observe_one(code: str, entry: str, args: list, timeout: float) -> dict:
    payload = json.dumps({"code": code, "entry": entry, "args_list": [args]})
    try:
        proc = _run(payload, timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": ""}
    parsed = _parse(proc.stdout or "", 1)
    if parsed is None:
        return {"status": "crash", "exc": (proc.stderr or "").strip()[-200:], "stdout": ""}
    return parsed[0]


def observe_many(code: str, entry: str, args_list: list, timeout: float = 5.0) -> list[dict]:
    """Run `entry` on every arg-list inside ONE subprocess (fast). On a batch
    timeout, fall back to per-input runs so we can localise the offending input.
    """
    if not args_list:
        return []
    payload = json.dumps({"code": code, "entry": entry, "args_list": args_list})
    try:
        proc = _run(payload, timeout)
    except subprocess.TimeoutExpired:
        per_to = max(1.0, timeout / 4)
        return [_observe_one(code, entry, a, per_to) for a in args_list]
    parsed = _parse(proc.stdout or "", len(args_list))
    if parsed is None:
        err = (proc.stderr or "").strip()[-200:]
        return [{"status": "crash", "exc": err, "stdout": ""} for _ in args_list]
    return parsed


def signature(obs: dict) -> tuple:
    """Comparable behavior signature for an observation."""
    st = obs.get("status")
    if st == "ok":
        return ("ok", obs.get("value_repr"), obs.get("stdout", ""))
    if st == "exc":
        return ("exc", obs.get("exc"), obs.get("stdout", ""))
    return (st, None, obs.get("stdout", ""))
