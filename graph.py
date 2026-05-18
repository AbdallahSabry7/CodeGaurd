from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
import ast

from state import AgentState
from agents import analyzer_agent, refactor_agent, comparator_agent, executer_agent
from tools import analysis_tools, validator_tool

analysis_tools_by_name = {tool.name: tool for tool in analysis_tools}
executer_tools_by_name = {tool.name: tool for tool in validator_tool}


# ---------------------------------------------------------------------------
# Tool nodes
# ---------------------------------------------------------------------------

def analyzer_tool_node(state: AgentState) -> dict:
    last_message = state["analyzer_messages"][-1]
    code = state.get("refactored_code") or state.get("original_code", "")

    outputs = [
        ToolMessage(
            content=str(analysis_tools_by_name[tool_call["name"]].invoke({"code": code})),
            tool_call_id=tool_call["id"],
        )
        for tool_call in last_message.tool_calls
    ]
    return {"analyzer_messages": list(state.get("analyzer_messages", [])) + outputs}


def executer_tool_node(state: AgentState) -> dict:
    last_message = state["executer_messages"][-1]
    code = state.get("refactored_code") or state.get("original_code", "")
    
    print(f"[DEBUG executer_tool_node] tool_calls: {[tc['name'] for tc in last_message.tool_calls]}")

    outputs = [
        ToolMessage(
            content=str(executer_tools_by_name[tool_call["name"]].invoke({"code": code})),
            tool_call_id=tool_call["id"],
        )
        for tool_call in last_message.tool_calls
    ]
    
    return {"executer_messages": outputs}


# ---------------------------------------------------------------------------
# Syntax check node
# ---------------------------------------------------------------------------

def validate_refactored_code(state: AgentState) -> dict:
    code = state.get("refactored_code", "")
    try:
        ast.parse(code)
        return {"refactor_syntax_error": None}
    except SyntaxError as e:
        return {"refactor_syntax_error": f"SyntaxError at line {e.lineno}: {e.msg}"}


# ---------------------------------------------------------------------------
# Memory clear nodes
# ---------------------------------------------------------------------------

def clear_analyzer_memory(state: AgentState) -> dict:
    return {
        "analyzer_messages": [],
        "analyzer_report": "", 
    }


def clear_executer_memory(state: AgentState) -> dict:
    return {"executer_messages": []}


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

def should_call_tool(state: AgentState) -> str:
    last_message = state["analyzer_messages"][-1]
    refactor_iterations = state.get("refactor_iterations", 0)

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool"
    
    if isinstance(last_message, AIMessage) and not last_message.content.strip():
        return "tool"

    if refactor_iterations == 0:
        return "refactor"
    else:
        return "comparator"


def syntax_check_router(state: AgentState) -> str:
    if state.get("refactor_syntax_error"):
        if state.get("refactor_iterations", 0) < 3:
            return "fix"
        else:
            return "end"
    return "proceed"


def comparator_router(state: AgentState) -> str:
    report = state.get("comparator_report", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 3:
        return "end"
    if "FAIL" in report:
        return "refactor"
    return "executer"


def executer_router(state: AgentState) -> str:
    last_message = state["executer_messages"][-1]
    result = state.get("execution_result", "")
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 3:
        return "end"

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool"

    if "FAIL" in result:
        return "refactor"

    return "end"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Comparator Agent", comparator_agent)
    graph.add_node("Executer Agent", executer_agent)
    graph.add_node("analysisTool", analyzer_tool_node)
    graph.add_node("executerTool", executer_tool_node)
    graph.add_node("syntax_check", validate_refactored_code)
    graph.add_node("clear_analyzer_memory", clear_analyzer_memory)
    graph.add_node("clear_executer_memory", clear_executer_memory)

    # Entry
    graph.add_edge(START, "analyzer")

    # Analyzer → tool or next stage
    graph.add_conditional_edges(
        "analyzer",
        should_call_tool,
        {
            "tool": "analysisTool",
            "refactor": "Refactor Agent",
            "comparator": "Comparator Agent",
        },
    )

    graph.add_edge("analysisTool", "analyzer")

    # Refactor → syntax check
    graph.add_edge("Refactor Agent", "syntax_check")

    graph.add_conditional_edges(
        "syntax_check",
        syntax_check_router,
        {
            "fix": "Refactor Agent",
            "proceed": "clear_analyzer_memory",
            "end": END,
        },
    )

    graph.add_edge("clear_analyzer_memory", "analyzer")

    # Comparator → executer or back to refactor
    graph.add_conditional_edges(
        "Comparator Agent",
        comparator_router,
        {
            "refactor": "Refactor Agent",
            "executer": "Executer Agent",
            "end": END,
        },
    )

    # Executer → tool, refactor, or end
    graph.add_conditional_edges(
        "Executer Agent",
        executer_router,
        {
            "tool": "executerTool",
            "refactor": "clear_executer_memory",
            "end": END,
        }
    )

    graph.add_edge("executerTool", "Executer Agent")
    graph.add_edge("clear_executer_memory", "Refactor Agent")

    return graph.compile()