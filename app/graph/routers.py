from schemas import AgentState
from helpers.config import get_settings, Settings
from tools import ConvergenceController

settings = get_settings()

max_iterations = settings.max_iterations
controller = ConvergenceController()
    
def syntax_check_router(state: AgentState) -> str:
	if state.get("refactor_syntax_error"):
		if state.get("refactor_iterations", 0) < max_iterations:
			return "fix"
		lang = state.get("source_language", "").lower()
		return "translate_out" if lang in ("java", "cpp") else "end"
	return "proceed"

def syntax_check_router2(state: AgentState) -> str:
    iterations = state.get("syntax_iterations", 0)
    if iterations >= max_iterations:
        return "end"
    else:
        if state.get("translator_syntax_error"):
            return "fix"
        else:
            return "proceed"


def executer_router(state: AgentState) -> str:
	result = state.get("execution_result", "")
	iterations = state.get("refactor_iterations", 0)
	source_language = state.get("source_language", "").lower()

	if "FAIL" in result:
		if "[docker_unavailable]" in result:
			return "end" if source_language == "python" else "translate_out"
		if iterations >= max_iterations:
			return "translate_out" if source_language in ("java", "cpp") else "end"
		return "refactor"

	return "equivalence"

def main_router(state: AgentState) -> str:
    source_language = state.get("source_language", "unsupported")
    if source_language == "unsupported" or source_language == "unknown":
        return "end"
    elif source_language == "python":
        return "characterize"
    else:
        return "translator"
    
def translator_router(state: AgentState) -> str:
    iterations = state.get("refactor_iterations", 0)
    if iterations == 0:
        return "characterize"
    else:   
        return "end"
    
def route_after_architect(state):
	if state.get("architect_verdict") == "HALT_PERFECT_ENOUGH":
		return "convergence"
	return "refactor" if not state.get("refactored_code") else "convergence"

def architect_gate(state):
	"""First pass only: reuse a pre-seeded Alt+Enter SOLID opinion instead of re-running the Architect (so the SOLID card and Optimize agree). Otherwise run the Architect normally."""
	first_pass = not state.get("refactor_iterations") and not state.get("refactored_code")
	seeded = state.get("architect_report") is not None
	is_python = (state.get("source_language") or "").lower() == "python"
	if first_pass and seeded and is_python:
		if state.get("architect_verdict") == "HALT_PERFECT_ENOUGH":
			return "convergence"
		return "refactor"
	return "architect"

def convergence_router(state: AgentState) -> str:
	if state.get("architect_verdict") == "HALT_PERFECT_ENOUGH":
		return "finalize"
	if state.get("refactor_iterations", 0) >= max_iterations: 
		return "finalize"
	return controller.decide(
		history=state.get("quality_scores", []),
		loops=state.get("improvement_loops", 0),
	)

def regression_router(state: AgentState) -> str:
    if state.get("regression_verdict") == "DIFFERENT" and \
        state.get("refactor_iterations", 0) < settings.max_iterations:
        return "refactor"
    lang = state.get("source_language").lower()
    return "translate_out" if lang in ("java", "cpp") else "done"
