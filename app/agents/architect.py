from __future__ import annotations

import json
import re
from typing import Literal, Optional
from schemas import AgentState

from pydantic import BaseModel, Field, ValidationError

from llms import architect_llm
from prompts import ARCHITECT_SYSTEM_PROMPT

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Category = Literal["SOLID", "Clean Code", "Complexity"]


# ======================================================================
# SCHEMAS — define & validate the shape of the LLM's JSON output
# ======================================================================
class SolidViolation(BaseModel):
    principle: Literal["SRP", "OCP", "LSP", "ISP", "DIP"]
    location: str
    reasoning: str
    severity: Severity
    confidence: int = Field(ge=1, le=100)
    refactor_directive: str


class ComplexityFinding(BaseModel):
    type: Literal["time", "space"]
    location: str
    current: str
    improvable: bool
    target: Optional[str] = None
    reasoning: str
    refactor_directive: str = ""


class CleanCodeViolation(BaseModel):
    issue_name: str
    location: str
    reasoning: str
    severity: Severity
    confidence: int = Field(ge=1, le=100)
    refactor_directive: str


class RejectedIssue(BaseModel):
    issue_name: str
    category: Category
    rejection_reason: str


class ArchitectReport(BaseModel):
    language: str
    solid_violations: list[SolidViolation] = []
    complexity_findings: list[ComplexityFinding] = []
    clean_code_violations: list[CleanCodeViolation] = []
    rejected_issues: list[RejectedIssue] = []
    global_verdict: Literal["PROCEED_TO_REFACTOR", "HALT_PERFECT_ENOUGH"]


# ======================================================================
# HELPERS — private utilities that support the node
# ======================================================================
def _extract_json(text: str) -> dict:
    """Strip stray prose / code fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_user_payload(language, code, analyzer_report, previously_rejected):
    return (
        f"LANGUAGE: {language}\n\n"
        f"CODE UNDER REVIEW:\n{code}\n\n"
        f"ANALYZER REPORT:\n{json.dumps(analyzer_report, indent=2)}\n\n"
        f"PREVIOUSLY REJECTED:\n{json.dumps(previously_rejected, indent=2)}"
    )


def _enforce_verdict(report: ArchitectReport) -> ArchitectReport:
    """Derive the verdict in code — never trust the LLM's."""
    actionable = (
        len(report.solid_violations)
        + len(report.clean_code_violations)
        + sum(1 for c in report.complexity_findings if c.improvable)
    )
    report.global_verdict = "PROCEED_TO_REFACTOR" if actionable else "HALT_PERFECT_ENOUGH"
    return report


_SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _flatten_directives(report: ArchitectReport) -> list[dict]:
    """Collapse the report into the numbered, severity-sorted list the
    Refactor Agent consumes (it never sees the raw analyzer report)."""
    items: list[dict] = []
    for v in report.solid_violations:
        items.append({"category": "SOLID", "label": v.principle, "location": v.location,
                    "severity": v.severity, "directive": v.refactor_directive})
    for v in report.clean_code_violations:
        items.append({"category": "Clean Code", "label": v.issue_name, "location": v.location,
                    "severity": v.severity, "directive": v.refactor_directive})
    for c in report.complexity_findings:
        if c.improvable and c.refactor_directive:
            items.append({"category": "Complexity",
                        "label": f"{c.type} {c.current} -> {c.target}",
                        "location": c.location, "severity": "HIGH",
                        "directive": c.refactor_directive})
    items.sort(key=lambda i: _SEVERITY_RANK.get(i["severity"], 4))
    for idx, item in enumerate(items, start=1):
        item["id"] = idx
    return items


def _merge_rejected(existing: list[dict], new: list) -> list[dict]:
    """Accumulate rejected issues across loops, de-duped by (issue_name, category)."""
    seen = {(r["issue_name"], r["category"]) for r in existing}
    merged = list(existing)
    for item in new:
        r = item.model_dump() if hasattr(item, "model_dump") else item
        key = (r["issue_name"], r["category"])
        if key not in seen:
            seen.add(key)
            merged.append(r)
    return merged


def _run_architect(language, code, analyzer_report, previously_rejected=None,
                max_retries=2) -> ArchitectReport:
    """Call the LLM, validate against the schema, retry on malformed output."""
    previously_rejected = previously_rejected or []
    messages = [
        {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_payload(
            language, code, analyzer_report, previously_rejected)},
    ]
    last_err: Optional[Exception] = None
    for _ in range(max_retries + 1):
        raw = architect_llm.invoke(messages).content
        try:
            report = ArchitectReport.model_validate(_extract_json(raw))
            return _enforce_verdict(report)
        except (ValidationError, json.JSONDecodeError) as err:
            last_err = err
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                f"Your previous response failed validation: {err}. "
                "Respond ONLY with the JSON object described. No prose, no fences."})
    raise RuntimeError(f"Architect failed schema validation after retries: {last_err}")


# ======================================================================
# NODE — runs after EVERY analyzer pass:  (state) -> dict
# ======================================================================
def architect_agent(state: "AgentState") -> dict:
    code = state.get("refactored_code") or state["original_code"]
    report = _run_architect(
        language=state.get("language", "python"),
        code=code,
        analyzer_report=state["analyzer_report"],          # latest analyzer output
        previously_rejected=state.get("architect_rejected", []),
    )
    out = {
        "architect_report": report.model_dump(),
        "refactor_directives": _flatten_directives(report),
        "architect_verdict": report.global_verdict,
        "architect_rejected": _merge_rejected(
            state.get("architect_rejected", []), report.rejected_issues),
    }
    
    # vetted baseline = first cleaned report; captured once, never overwritten
    if state.get("architect_baseline_report") is None:
        out["architect_baseline_report"] = report.model_dump()
    return out