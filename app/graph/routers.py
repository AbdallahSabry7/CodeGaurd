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

def syntax_check_router2(state: AgentState) -> str:
    iterations = state.get("syntax_iterations", 0)
    if iterations >= max_iterations:
        return "end"
    else:
        if state.get("translator_syntax_error"):
            return "fix"
        else:
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
    source_language = state.get("source_language")

    if iterations >= max_iterations:
        if source_language != "python":
            return "translator"
        return "end"

    if "FAIL" in result:
        return "refactor"
    
    if source_language != "python":
        return "translator"
    return "end"

def main_router(state: AgentState) -> str:
    source_language = state.get("source_language", "unsupported")
    if source_language == "unsupported" or source_language == "unknown":
        return "end"
    elif source_language == "python":
        return "analyzer"
    else:
        return "translator"
    
def translator_router(state: AgentState) -> str:
    iterations = state.get("refactor_iterations", 0)
    if iterations == 0:
        return "analyzer"
    else:   
        return "end"
    
def route_after_architect(state):
    if state["architect_verdict"] == "HALT_PERFECT_ENOUGH":
        return 'END'
    return "refactor" if not state.get("refactored_code") else "comparator"