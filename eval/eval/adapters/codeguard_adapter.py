"""Adapter that wires the eval harness into CodeGuard's REAL pipeline.

The harness talks to CodeGuard ONLY through this file. Point the 4 `# === WIRE`
spots at your real interfaces in app/. Set CODEGUARD_APP_DIR to the folder that
contains services/, graph/, tools/ (defaults to ../app relative to eval/).

Unchanged in spirit from the original adapter; kept here so the improved harness
is self-contained. The refactor probe is now done by the task across snippets
(not just snippet 0), so one unlucky snippet no longer hides the whole column.
"""
from __future__ import annotations

import os
import re
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS))  # eval/ -> repo root
_APP_DIR = os.getenv("CODEGUARD_APP_DIR", os.path.join(_REPO_ROOT, "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

_IMPORT_ERROR = None
_SERVICES = None
_REFACTOR_ERROR = None


def _load_services():
    global _SERVICES, _IMPORT_ERROR
    if _SERVICES is not None:
        return _SERVICES
    try:
        # === WIRE 1 === names come from app/services/__init__.py
        import services as _svc  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on user repo
        _IMPORT_ERROR = exc
        _SERVICES = None
        return None

    def _g(name):
        return getattr(_svc, name, None)

    table = {
        "complexity": _g("estimate_complexity"),
        "SRP": _g("get_srp_report"),
        "OCP": _g("get_ocp_report"),
        "LSP": _g("get_lsp_report"),
        "ISP": _g("get_isp_report"),
        "DIP": _g("get_dip_report"),
        "clean": _g("analyze_code_string"),
    }
    if table["complexity"] is None:
        _IMPORT_ERROR = ImportError("services.estimate_complexity not found")
        _SERVICES = None
        return None
    _SERVICES = table
    return _SERVICES


def pipeline_available() -> bool:
    return _load_services() is not None


def import_error() -> str:
    return "" if _IMPORT_ERROR is None else f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}"


def refactor_error() -> str:
    return "" if _REFACTOR_ERROR is None else f"{type(_REFACTOR_ERROR).__name__}: {_REFACTOR_ERROR}"


_SUPER = {"\u00b2": "^2", "\u00b3": "^3", "\u2074": "^4", "\u207f": "^n"}


def _canon_bigo(s: str) -> str:
    s = str(s or "").strip()
    for k, v in _SUPER.items():
        s = s.replace(k, v)
    s = re.sub(r"O\(\s*\d+\s*\^n\)", "O(2^n)", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _flags_violation(report) -> bool:
    entries = []
    if isinstance(report, dict):
        if report and all(isinstance(v, dict) for v in report.values()):
            entries = list(report.values())
        else:
            entries = [report]
    elif isinstance(report, list):
        entries = report
    elif isinstance(report, bool):
        return report
    else:
        text = str(report).lower()
        return bool(text.strip()) and "violation" in text and "no violation" not in text

    for e in entries:
        if isinstance(e, dict):
            if e.get("is_violation") is True:
                return True
            if str(e.get("status", "")).strip().lower() == "violation":
                return True
        elif isinstance(e, str):
            if e.strip().upper() in ("SRP", "OCP", "LSP", "ISP", "DIP"):
                return True
    return False


def _solid_violations(code: str) -> list:
    svc = _load_services() or {}
    out = []
    for principle in ("SRP", "OCP", "LSP", "ISP", "DIP"):
        fn = svc.get(principle)
        if fn is None:
            continue
        try:
            # === WIRE 2 === one call per principle, all from app/services
            report = fn(code)
        except Exception:
            continue
        if _flags_violation(report):
            out.append(principle)
    return sorted(set(out))


_SMELL_RULE_MAP = (
    ("long_method", ("function_too_long", "method_too_long", "too_long", "long_function")),
    ("long_parameter_list", ("too_many_params", "too_many_arguments", "many_params", "param_count", "too_many_parameters")),
    ("magic_number", ("magic_number", "magic")),
    ("dead_code", ("dead_code", "unused", "unreachable")),
    ("duplicated_code", ("duplicate", "duplicated")),
    ("god_class", ("god_class", "large_class", "too_many_methods")),
)


def _rule_to_smell(rule: str):
    rule = (rule or "").lower()
    for label, needles in _SMELL_RULE_MAP:
        if any(n in rule for n in needles):
            return label
    return None


def _clean_code(code: str):
    svc = _load_services() or {}
    fn = svc.get("clean")
    if fn is None:
        return [], None
    try:
        res = fn(code)
    except Exception:
        return [], None

    score = None
    rules = []
    items = []
    if isinstance(res, dict):
        score = res.get("score")
        items = res.get("fixes") or res.get("smells") or res.get("issues") or res.get("findings") or []
    elif isinstance(res, list):
        items = res

    for item in items:
        if isinstance(item, str):
            parts = item.split(":")
            rules.append(parts[3] if len(parts) > 3 else parts[-1])
        elif isinstance(item, dict):
            rules.append(str(item.get("id") or item.get("rule") or item.get("type") or item.get("name") or ""))

    smells = set()
    for rule in rules:
        label = _rule_to_smell(rule)
        if label:
            smells.add(label)
    return sorted(smells), score


def analyze(code: str) -> dict:
    svc = _load_services()
    if svc is None:
        return {"complexity": "", "solid": [], "smells": [], "clean_score": None, "_stub": True}
    try:
        time_c, _space_c = svc["complexity"](code)
    except Exception:
        time_c = ""
    smells, clean_score = _clean_code(code)
    return {
        "complexity": _canon_bigo(time_c),
        "solid": _solid_violations(code),
        "smells": sorted(set(smells)),
        "clean_score": clean_score,
    }


def refactor_full(code: str):
    """Run the full CodeGuard graph end-to-end.

    Returns (refactored_code|None, equivalence_verdict|None), or None if the
    graph can't be imported (harness then skips this system).
    """
    try:
        # === WIRE 3 === real LangGraph entrypoint + input/output state keys
        from graph import build_graph  # app/graph/__init__.py

        app = build_graph()
        state = app.invoke({
            "messages": [("user", code)],
            "original_code": code,
            "refactor_iterations": 0,
        })
        refactored = state.get("refactored_code")
        if isinstance(refactored, list):
            refactored = refactored[-1] if refactored else None
        verdict = state.get("regression_verdict")
        return refactored, verdict
    except Exception as exc:
        global _REFACTOR_ERROR
        _REFACTOR_ERROR = exc
        print(f"[codeguard-eval] refactor_full failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
