"""Adapter: AST analyzers + Architect Agent output → eval harness labels.

This lets the eval compare:
- raw LLM baseline
- AST-only detectors (codeguard_adapter.analyze)
- AST + Architect (this file)

Key idea:
- Build an analyzer_report using the same services your pipeline uses.
- Call app/agents/architect.architect_agent(state) to produce architect_report.
- Convert architect_report to harness labels (SOLID + smell labels).

Environment:
- CODEGUARD_APP_DIR should point to the folder containing services/, agents/, schemas/, llms.py, prompts/.
"""

from __future__ import annotations

import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS))  # eval/ -> repo root
_APP_DIR = os.getenv("CODEGUARD_APP_DIR", os.path.join(_REPO_ROOT, "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

_IMPORT_ERROR = None


def import_error() -> str:
    return "" if _IMPORT_ERROR is None else f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}"


def pipeline_available() -> bool:
    """Return true if we can import services + architect agent."""
    try:
        import services  # noqa: F401
        from agents.architect import architect_agent  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover
        global _IMPORT_ERROR
        _IMPORT_ERROR = exc
        return False


# ---------------------------------------------------------------------------
# Analyzer report builder (must match what Architect expects)
# ---------------------------------------------------------------------------

def _build_analyzer_report(code: str) -> dict:
    """Build the analyzer_report shape consumed by the Architect.

    Your Architect prompt expects `ANALYZER REPORT` as JSON. In the app pipeline,
    state["analyzer_report"] is created upstream.

    For eval, we recreate a minimal but compatible dict using services.
    """
    import services

    time_c, space_c = services.estimate_complexity(code)

    solid = {
        "SRP": services.get_srp_report(code),
        "OCP": services.get_ocp_report(code),
        "LSP": services.get_lsp_report(code),
        "ISP": services.get_isp_report(code),
        "DIP": services.get_dip_report(code),
    }

    clean = services.analyze_code_string(code)

    return {
        "complexity": {"time": time_c, "space": space_c},
        "solid": solid,
        "clean_code": clean,
    }


# ---------------------------------------------------------------------------
# Architect report → eval labels
# ---------------------------------------------------------------------------

# Eval labels (same as eval/tasks files)
SOLID_LABELS = ["SRP", "OCP", "LSP", "ISP", "DIP"]
SMELL_LABELS = ["long_method", "long_parameter_list", "magic_number"]


def _map_clean_code_issue_name_to_smell(issue_name: str) -> str | None:
    """Map architect clean-code issue names to the eval harness smell labels.

    IMPORTANT: This is intentionally conservative.
    You should extend these mappings to match whatever `issue_name` values your
    Architect produces.
    """
    s = (issue_name or "").strip().lower()

    # long_method
    if any(k in s for k in ["long method", "long_function", "function too long", "too long"]):
        return "long_method"

    # long_parameter_list
    if any(k in s for k in ["long parameter", "too many parameters", "too many args", "too many arguments"]):
        return "long_parameter_list"

    # magic_number
    if "magic" in s and "number" in s:
        return "magic_number"

    return None


def analyze_with_architect(code: str) -> dict:
    """Return normalized eval shape: {solid:[...], smells:[...], complexity:str}.

    Complexity here is optional; SOLID + smells are the main comparison.
    """
    try:
        from agents.architect import architect_agent

        analyzer_report = _build_analyzer_report(code)

        # Minimal AgentState fields needed by architect_agent()
        state = {
            "refactor_iterations": 0,
            "original_code": code,
            "original_code_converted": "",
            "refactored_code": "",
            "analyzer_report": analyzer_report,
            "architect_rejected": [],
            "architect_baseline_report": None,
        }

        out = architect_agent(state)
        report = out.get("architect_report") or {}

        # SOLID
        solid = []
        for v in report.get("solid_violations", []) or []:
            p = (v or {}).get("principle")
            if p in SOLID_LABELS:
                solid.append(p)
        solid = sorted(set(solid))

        # Smells
        smells = set()
        for v in report.get("clean_code_violations", []) or []:
            name = (v or {}).get("issue_name")
            mapped = _map_clean_code_issue_name_to_smell(name)
            if mapped in SMELL_LABELS:
                smells.add(mapped)

        # Complexity (optional, not used by current eval tables)
        time_c = (analyzer_report.get("complexity", {}) or {}).get("time", "")

        return {
            "solid": solid,
            "smells": sorted(smells),
            "complexity": str(time_c),
            "_architect": True,
        }

    except Exception as exc:
        global _IMPORT_ERROR
        _IMPORT_ERROR = exc
        return {"solid": [], "smells": [], "complexity": "", "_error": str(exc)}