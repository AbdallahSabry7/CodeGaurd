import ast

from schemas import AgentState
from tools import analysis_tool, execute_code_tool

def validate_refactored_code(state: AgentState) -> dict:
    code = state.get("refactored_code", "")
    try:
        ast.parse(code)
        return {"refactor_syntax_error": None}
    except SyntaxError as e:
        return {"refactor_syntax_error": f"SyntaxError at line {e.lineno}: {e.msg}"}


def clear_executer_memory(state: AgentState) -> dict:
    return {"executer_messages": []}

def analyzer_function(state: AgentState) -> str:
    if state.get("refactored_code"):
        code_to_analyze = state["refactored_code"]
    else:
        code_to_analyze = state["original_code"]

    iterations = state.get("refactor_iterations", 0)
    response = analysis_tool.invoke({"code": code_to_analyze})
    if iterations == 0:
        return {"analyzer_report": response, "original_analyzer_report": response}
    else:
        return {"analyzer_report": response }
    
def executer_function(state: AgentState) -> str:
    code_to_execute = state.get("refactored_code", "")
    response = execute_code_tool.invoke({"code": code_to_execute})
    return {"execution_result": response}

