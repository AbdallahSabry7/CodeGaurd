from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
import ast

from schemas import AgentState
from agents import refactor_agent, translate_from_python , translate_to_python , architect_agent , characterize_node
from tools import analysis_tool, execute_code_tool
from .routers import analyzer_router, syntax_check_router, executer_router, main_router , translator_router , syntax_check_router2 , route_after_architect , convergence_router , equivalence_router
from .nodes import validate_refactored_code,validate_translator_code , analyzer_function, executer_function, detect_language , convergence_node , equivalence_node

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("detect_language", detect_language)
    graph.add_node("analyzer", analyzer_function)
    graph.add_node("architect", architect_agent)
    graph.add_node("executer", executer_function)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Convergence Node", convergence_node)
    graph.add_node("Translate to Python", translate_to_python)
    graph.add_node("Translate from Python", translate_from_python)
    graph.add_node("syntax_check", validate_refactored_code)
    graph.add_node("syntax_check2", validate_translator_code)
    graph.add_node("characterize", characterize_node)
    graph.add_node("equivalence", equivalence_node)

    graph.add_edge(START, "detect_language")

    graph.add_conditional_edges(
        "detect_language",
        main_router,
        {
            "end": END,
            "characterize": "characterize",
            "translator": "Translate to Python"
        }
    )
    graph.add_conditional_edges(
        "Translate to Python",
        translator_router,
        {
            "characterize": "syntax_check2",
            "end": END,
        }
    )

    graph.add_conditional_edges(
        "syntax_check2",
        syntax_check_router2,
        {
            "fix": "Translate to Python",
            "proceed": "characterize",
            'end': END
        }
    )

    graph.add_edge("characterize", "analyzer")

    graph.add_edge("analyzer", "architect")

    graph.add_conditional_edges(
        "architect",
        route_after_architect,
        {
            'END': END,
            "refactor": "Refactor Agent",
            "convergence": "Convergence Node",
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
        "Convergence Node",
        convergence_router,
        {
            "continue": "Refactor Agent",
            "finalize": "executer"
        },
    )

    graph.add_conditional_edges(
        "executer",
        executer_router,
        {
            "refactor": "Refactor Agent",
            "equivalence": "equivalence",
            "end": END,
        }
    )

    graph.add_conditional_edges(
        "equivalence",
        equivalence_router,
        {
            "refactor": "Refactor Agent",  
            "translate_out": "Translate from Python", 
            "done": END,                   
        },
    )


    graph.add_edge("Translate from Python", END)

    return graph.compile()