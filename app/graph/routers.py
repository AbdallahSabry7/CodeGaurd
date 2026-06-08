from schemas import AgentState
from helpers.config import get_settings, Settings
from tools import ConvergenceController

settings = get_settings()

max_iterations = settings.max_iterations
controller = ConvergenceController()

def analyzer_router(state: AgentState) -> str:
    refactor_iterations = state.get("refactor_iterations", 0)

    if refactor_iterations == 0:
        return "refactor"
    else:
        return "comparator"
    
def syntax_check_router(state: AgentState) -> str:
    if state.get("refactor_syntax_error"):
        if state.get("refactor_iterations", 0) < max_iterations:
            return "fix"
        else:
            return "end"
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
    source_language = state.get("source_language").lower()

    if iterations >= max_iterations:
        return "end"

    if "FAIL" in result:
        if "[docker_unavailable]" in result:
            if source_language == "python":
                return "end"
            else:
                return "translate_out"
        else:
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
    if state["architect_verdict"] == "HALT_PERFECT_ENOUGH":
        return 'convergence'
    return "refactor" if not state.get("refactored_code") else "convergence"

def convergence_router(state: AgentState) -> str:
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
