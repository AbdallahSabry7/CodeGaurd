from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
import ast

from schemas import AgentState
from agents import refactor_agent, comparator_agent
from tools import analysis_tool, execute_code_tool
from .routers import analyzer_router, syntax_check_router, comparator_router, executer_router
from .nodes import validate_refactored_code, clear_executer_memory, analyzer_function, executer_function

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