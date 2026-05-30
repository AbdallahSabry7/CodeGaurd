from schemas import AgentState
from helpers.config import get_settings, Settings

settings = get_settings()

max_iterations = settings.max_iterations

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


def comparator_router(state: AgentState) -> str:
    report = state.get("comparator_report", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= max_iterations:
        return "end"
    if "FAIL" in report:
        return "refactor"
    return "executer"


def executer_router(state: AgentState) -> str:
    result = state.get("execution_result", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= max_iterations:
        return "end"

    if "FAIL" in result:
        return "refactor"

    return "end"