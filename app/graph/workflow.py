from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
import ast

from schemas import AgentState
from agents import refactor_agent, comparator_agent , translate_from_python , translate_to_python , architect_agent
from tools import analysis_tool, execute_code_tool
from .routers import analyzer_router, syntax_check_router, comparator_router, executer_router, main_router , translator_router , syntax_check_router2 , route_after_architect
from .nodes import validate_refactored_code,validate_translator_code , analyzer_function, executer_function, detect_language 

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("detect_language", detect_language)
    graph.add_node("analyzer", analyzer_function)
    graph.add_node("architect", architect_agent)
    graph.add_node("executer", executer_function)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Comparator Agent", comparator_agent)
    graph.add_node("Translate to Python", translate_to_python)
    graph.add_node("Translate from Python", translate_from_python)
    graph.add_node("syntax_check", validate_refactored_code)
    graph.add_node("syntax_check2", validate_translator_code)

    graph.add_edge(START, "detect_language")

    graph.add_conditional_edges(
        "detect_language",
        main_router,
        {
            "end": END,
            "analyzer": "analyzer",
            "translator": "Translate to Python"
        }
    )
    graph.add_conditional_edges(
        "Translate to Python",
        translator_router,
        {
            "analyzer": "syntax_check2",
            "end": END,
        }
    )

    graph.add_conditional_edges(
        "syntax_check2",
        syntax_check_router2,
        {
            "fix": "Translate to Python",
            "proceed": "analyzer",
            'end': END
        }
    )

    graph.add_edge("analyzer", "architect")

    graph.add_conditional_edges(
        "architect",
        route_after_architect,
        {
            'END': END,
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
            "end": "Translate from Python",
        },
    )

    graph.add_conditional_edges(
        "executer",
        executer_router,
        {
            "refactor": "Refactor Agent",
            "translator": "Translate from Python",
            "end": END,
        }
    )

    graph.add_edge("Translate from Python", END)

    return graph.compile()