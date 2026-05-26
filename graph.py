from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
import ast

from state import AgentState
from agents import refactor_agent, comparator_agent
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


def analyzer_router(state: AgentState) -> str:
    refactor_iterations = state.get("refactor_iterations", 0)

    if refactor_iterations == 0:
        return "refactor"
    else:
        return "comparator"

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

def syntax_check_router(state: AgentState) -> str:
    if state.get("refactor_syntax_error"):
        if state.get("refactor_iterations", 0) < 5:
            return "fix"
        else:
            return "end"
    return "proceed"


def comparator_router(state: AgentState) -> str:
    report = state.get("comparator_report", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 5:
        return "end"
    if "FAIL" in report:
        return "refactor"
    return "executer"


def executer_router(state: AgentState) -> str:
    result = state.get("execution_result", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 5:
        return "end"

    if "FAIL" in result:
        return "refactor"

    return "end"

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("analyzer", analyzer_function)
    graph.add_node("executer", executer_function)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Comparator Agent", comparator_agent)
    graph.add_node("syntax_check", validate_refactored_code)
    graph.add_node("clear_executer_memory", clear_executer_memory)

    graph.add_edge(START, "analyzer")

    graph.add_conditional_edges(
        "analyzer",
        analyzer_router,
        {
            "refactor": "Refactor Agent",
            "comparator": "Comparator Agent",
        },
    )

    graph.add_edge("Refactor Agent", "syntax_check")

    graph.add_conditional_edges(
        "syntax_check",
        syntax_check_router,
        {
            "fix": "Refactor Agent",
            "proceed": "analyzer",
            "end": END,
        },
    )

    graph.add_conditional_edges(
        "Comparator Agent",
        comparator_router,
        {
            "refactor": "Refactor Agent",
            "executer": "executer",
            "end": END,
        },
    )

    graph.add_conditional_edges(
        "executer",
        executer_router,
        {
            "refactor": "Refactor Agent",
            "end": END,
        }
    )

    return graph.compile()