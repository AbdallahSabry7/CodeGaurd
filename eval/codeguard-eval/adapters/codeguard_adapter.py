"""Adapter that wires the eval harness into CodeGuard's REAL pipeline.

The harness talks to CodeGuard ONLY through this file. Everything below is
wired to the actual interfaces found in your repo (app/):

  app/services/__init__.py exports the symbolic analyzers:
      estimate_complexity(code)   -> (time_str, space_str)   e.g. ('O(n\u00b2)', 'O(1)')
      get_srp_report(code)        -> per-class SRP report (is_violation / status)
      get_ocp_report(code)        -> OCP report
      get_lsp_report(code)        -> LSP report
      get_isp_report(code)        -> ISP report
      get_dip_report(code)        -> DIP report
      analyze_code_string(code)   -> clean-code findings
  app/graph/__init__.py  exports build_graph()  (the full LangGraph pipeline)
  app/graph/nodes.py     exports detect_language(state)

Set CODEGUARD_APP_DIR to the folder that contains services/, graph/, tools/
(defaults to ../app relative to this eval folder).

There are 4 spots marked `# === WIRE N ===`. They are already pointed at the
real interfaces; the `# === VERIFY ===` notes flag the two shapes you should
confirm once by printing a real report (see README).
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
_COMPLEXITY_ERROR = None


def _load_services():
    """Import CodeGuard's symbolic analyzers from app/services. Returns dict or None."""
    global _SERVICES, _IMPORT_ERROR
    if _SERVICES is not None:
        return _SERVICES
    try:
        # === WIRE 1 === names come straight from app/services/__init__.py
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
    if table["complexity"] is None:  # core analyzer missing -> treat as unwired
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


def complexity_error() -> str:
    return "" if _COMPLEXITY_ERROR is None else str(_COMPLEXITY_ERROR)


# ---------------------------------------------------------------------------
# Big-O normalization.
# estimate_complexity returns UNICODE forms: 'O(n\u00b2)', 'O(n\u00b3)', 'O(2\u207f)', 'O(log n)'.
# The gold labels in datasets/complexity.jsonl use ASCII tiers:
#   O(1)  O(log n)  O(n)  O(n log n)  O(n^2)  O(n^3)  O(2^n)
# Convert superscripts -> ^k and bucket any exponential base into O(2^n).
# ---------------------------------------------------------------------------

_SUPER = {"\u00b2": "^2", "\u00b3": "^3", "\u2074": "^4", "\u207f": "^n"}


def _canon_bigo(s: str) -> str:
    s = str(s or "").strip()
    for k, v in _SUPER.items():
        s = s.replace(k, v)
    # collapse 'O(3^n)', 'O(b^n)'... into the canonical exponential bucket
    s = re.sub(r"O\(\s*\d+\s*\^n\)", "O(2^n)", s)
    # tidy double spaces but keep the single spaces in 'O(n log n)'
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------------------
# SOLID: ask each detector, mark a principle violated if its report says so.
# ---------------------------------------------------------------------------


def _flags_violation(report) -> bool:
    """True if a SOLID detector's report indicates at least one violation.

    === VERIFY === get_srp_report returns per-class entries with
    is_violation: bool and status in {'Violation','Review','Pass'}. The other
    four detectors follow a similar convention. If one returns a different
    shape, print it once and extend this function.
    """
    entries = []
    if isinstance(report, dict):
        # dict keyed by class name -> entry dict, OR a single entry dict
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


# ---------------------------------------------------------------------------
# Clean code.
# ---------------------------------------------------------------------------


# Map CodeGuard clean_code rule ids -> harness smell labels.
# Each fix token is "{SEV}:{line}:{target}:{rule}[:{detail}]"; we read the rule.
# clean_code only targets function-level smells, so god_class / dead_code /
# duplicated_code have no matching rule and legitimately stay empty.
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
    """Return (smells:list[str], clean_score:float|None).

    services.analyze_code_string(code) returns a compact dict:
      {score, grade, passed, counts, fixes: [...], lloc, error}
    where each fix token is "{SEV}:{line}:{target}:{rule}[:{detail}]".
    We pull the rule id (4th field) and map it to the harness smell labels.
    """
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
            # "{SEV}:{line}:{target}:{rule}[:{detail}]" -> rule is index 3
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
    """Run CodeGuard's symbolic analyzers and return the harness's normalized shape:
    {'complexity': str, 'solid': [..], 'smells': [..], 'clean_score': float|None}.
    """
    svc = _load_services()
    if svc is None:
        return {"complexity": "", "solid": [], "smells": [], "clean_score": None, "_stub": True}
    global _COMPLEXITY_ERROR
    try:
        res = svc["complexity"](code)
        if isinstance(res, (tuple, list)):
            time_c = res[0] if res else ""
            space_c = res[1] if len(res) > 1 else ""
        else:
            time_c, space_c = res, ""
        # The ML-based estimate_complexity catches its own exceptions and
        # returns ("Error", "<ExceptionType>: <message>"). Surface that message
        # instead of silently scoring "Error" as a wrong tier.
        if str(time_c).strip().lower() == "error":
            _COMPLEXITY_ERROR = str(space_c) or "estimate_complexity returned 'Error'"
            print(f"[codeguard-eval] complexity failed: {_COMPLEXITY_ERROR}", file=sys.stderr)
    except Exception as exc:
        _COMPLEXITY_ERROR = f"{type(exc).__name__}: {exc}"
        print(f"[codeguard-eval] complexity raised: {_COMPLEXITY_ERROR}", file=sys.stderr)
        time_c = ""
    smells, clean_score = _clean_code(code)
    return {
        "complexity": _canon_bigo(time_c),
        "solid": _solid_violations(code),
        "smells": sorted(set(smells)),
        "clean_score": clean_score,
    }


# ---------------------------------------------------------------------------
# Full-pipeline refactor (used by the refactor task + ablation).
# ---------------------------------------------------------------------------


def refactor_full(code: str):
    """Run the full CodeGuard graph end-to-end.

    Returns (refactored_code:str|None, equivalence_verdict:str|None), or None if
    the graph can't be imported (harness then skips this system).
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
        if isinstance(refactored, list):  # AgentState stores a list; take the latest
            refactored = refactored[-1] if refactored else None
        verdict = state.get("regression_verdict")
        return refactored, verdict
    except Exception as exc:
        global _REFACTOR_ERROR
        _REFACTOR_ERROR = exc
        print(
            f"[codeguard-eval] refactor_full failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
