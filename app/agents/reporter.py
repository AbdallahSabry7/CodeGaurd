import json

from schemas import AgentState
from llms import report_llm
from prompts import REPORT_PROMPT

from helpers.config import get_settings

settings = get_settings()
max_iterations = settings.max_iterations


def _build_verdict(state: AgentState) -> dict:
	exec_result = state.get("execution_result", "") or ""
	execution_ok = "FAIL" not in exec_result
	docker_unavailable = "[docker_unavailable]" in exec_result

	behavior = state.get("regression_verdict", "INCONCLUSIVE")  # SAME / DIFFERENT / INCONCLUSIVE

	scores = state.get("quality_scores") or []
	baseline = scores[0] if scores else None
	final = scores[-1] if scores else None
	improved = baseline is not None and final is not None and final < baseline
	clean = final == 0.0

	syntax_unresolved = bool(
		state.get("refactor_syntax_error") or state.get("translator_syntax_error")
	)
	hit_cap = state.get("refactor_iterations", 0) >= max_iterations

	# Remaining problems come straight from the latest architect report.
	report = state.get("architect_report")
	r = report.model_dump() if hasattr(report, "model_dump") else (report or {})
	remaining = {
		"solid": r.get("solid_violations", []),
		"clean_code": r.get("clean_code_violations", []),
		"complexity": [c for c in r.get("complexity_findings", []) if c.get("improvable")],
	}

	# Overall verdict
	if not execution_ok or behavior == "DIFFERENT" or syntax_unresolved:
		status = "FAILED"
	elif clean or (improved and behavior == "SAME" and not any(remaining.values())):
		status = "SOLVED"
	else:
		status = "PARTIAL"

	return {
		"status": status,
		"source_language": state.get("source_language", ""),
		"destination_language": state.get("destination_language", ""),
		"execution_ok": execution_ok,
		"docker_unavailable": docker_unavailable,
		"behavior": behavior,
		"behavior_report": state.get("regression_report", ""),
		"baseline_score": baseline,
		"final_score": final,
		"improved": improved,
		"clean": clean,
		"remaining": remaining,
		"refactor_iterations": state.get("refactor_iterations", 0),
		"improvement_loops": state.get("improvement_loops", 0),
		"hit_cap": hit_cap,
		"syntax_unresolved": syntax_unresolved,
	}

def _render_template(f: dict) -> str:
	lines = [f"# CodeGuard Report — {f['status']}", ""]

	if f["source_language"] and f["source_language"] != "python":
		lines.append(f"- Translated {f['source_language']} → python and back.")

	if f["docker_unavailable"]:
		lines.append("- Execution: not verified (sandbox unavailable).")
	elif f["execution_ok"]:
		lines.append("- Execution: PASS.")
	else:
		lines.append("- Execution: FAIL — the refactored code did not run successfully.")

	lines.append({
		"SAME": "- Behavior: preserved (regression check passed).",
		"DIFFERENT": "- Behavior: CHANGED — output differs from the original.",
		"INCONCLUSIVE": "- Behavior: not verified (no usable test cases).",
	}.get(f["behavior"], f"- Behavior: {f['behavior']}."))

	if f["baseline_score"] is not None:
		lines.append(
			f"- Quality score: {f['baseline_score']} → {f['final_score']}"
			f"{' (clean)' if f['clean'] else ''}."
		)

	total_remaining = sum(len(v) for v in f["remaining"].values())
	if total_remaining:
		lines.append(f"- Problems still present ({total_remaining}):")
		for kind, items in f["remaining"].items():
			for v in items:
				desc = v.get("description") or v.get("name") or kind
				lines.append(f"\t- [{kind}] {desc}")
	else:
		lines.append("- No actionable findings remain.")

	lines.append(
		f"- Effort: {f['refactor_iterations']} refactor iteration(s), "
		f"{f['improvement_loops']} improvement loop(s)"
		f"{' (hit the cap)' if f['hit_cap'] else ''}."
	)
	if f["syntax_unresolved"]:
		lines.append("- ⚠️ Ended with an unresolved syntax error.")

	return "\n".join(lines)

def report_agent(state: AgentState) -> dict:
	facts = _build_verdict(state)            # deterministic verdict (node layer)
	skeleton = _render_template(facts)       # deterministic bullet report

	# LLM prose layer — small model, facts only.
	prose = report_llm.invoke(
		REPORT_PROMPT.format(facts=json.dumps(facts, default=str))
	).content.strip()

	return {"final_report": f"{prose}\n\n{skeleton}"}