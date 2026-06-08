# app/services/convergence.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from helpers.config import get_settings, Settings

settings = get_settings()


SEVERITY_WEIGHT = {"CRITICAL": 8.0, "HIGH": 4.0, "MEDIUM": 2.0, "LOW": 1.0}
COMPLEXITY_WEIGHT = 4.0  


def _as_dict(report) -> dict:
    """Accept a Pydantic ArchitectReport OR its .model_dump() dict."""
    if report is None:
        return {}
    return report.model_dump() if hasattr(report, "model_dump") else report


@dataclass(frozen=True)
class QualityScore:
    total: float          
    solid: float
    clean_code: float
    complexity: float
    counts: dict

    def is_clean(self) -> bool:
        return self.total == 0.0


def score_report(report, *, use_confidence: bool = True) -> QualityScore:
    """Collapse an ArchitectReport into one comparable number."""
    r = _as_dict(report)

    def w(v: dict) -> float:
        weight = SEVERITY_WEIGHT.get(v.get("severity", "LOW"), 1.0)
        if use_confidence:
            weight *= v.get("confidence", 100) / 100.0
        return weight

    solid = sum(w(v) for v in r.get("solid_violations", []))
    clean = sum(w(v) for v in r.get("clean_code_violations", []))
    improvable = [c for c in r.get("complexity_findings", []) if c.get("improvable")]
    complexity = COMPLEXITY_WEIGHT * len(improvable)

    return QualityScore(
        total=round(solid + clean + complexity, 4),
        solid=round(solid, 4),
        clean_code=round(clean, 4),
        complexity=round(complexity, 4),
        counts={
            "solid": len(r.get("solid_violations", [])),
            "clean_code": len(r.get("clean_code_violations", [])),
            "complexity_improvable": len(improvable),
        },
    )


@dataclass(frozen=True)
class ComparisonResult:
    passed: bool            # True = clean OR improved enough
    reason: str
    baseline_total: float
    latest_total: float
    gain: float             # baseline - latest (positive = better)


def compare_reports(baseline, latest, *, min_gain: float = 0.05,
                    use_confidence: bool = True) -> ComparisonResult:
    """Deterministic stand-in for the LLM Comparator: baseline vs latest."""
    base = score_report(baseline, use_confidence=use_confidence)
    new = score_report(latest, use_confidence=use_confidence)
    gain = round(base.total - new.total, 4)

    if new.is_clean():
        passed, reason = True, "Clean — no actionable findings remain."
    elif new.total > base.total:
        passed, reason = False, f"Regression — score rose {base.total} -> {new.total}."
    elif gain < min_gain:
        passed, reason = False, f"Plateau — gain {gain} < {min_gain}."
    else:
        passed, reason = True, f"Improved — {base.total} -> {new.total} (gain {gain})."
    return ComparisonResult(passed, reason, base.total, new.total, gain)


@dataclass
class ConvergenceController:
    """Owns every stop decision for the improvement loop. No LLM. Fully testable."""
    max_improvement_loops: int = settings.max_improvement_loops
    min_gain: float = settings.min_gain

    def decide(self, *, history: list[float],
		    loops: int) -> Literal["continue", "finalize", "finalize and destroy last refactor"]:
        latest = history[-1]
        if latest == 0.0:
            return "finalize"
        if loops >= self.max_improvement_loops:
            return "finalize"
        if len(history) >= 2 and (history[-2] - history[-1]) < self.min_gain:
            if history[-1] > history[-2]:
                return "finalize and destroy last refactor"   
            return "finalize"                                 
        return "continue"