from langchain.messages import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from state import AgentState
from agents import analyzer_agent, refactor_agent, validator_agent
from tools import analysis_tools, validator_tool


def should_call_tool(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool"
    return "refactor"


def validator_router(state: AgentState) -> str:
    last_message = state["messages"][-1]
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 3:
        return END

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "TOOL_CALL"

    if isinstance(last_message, AIMessage) and "PASS" in last_message.content:
        return END

    return "refactor_agent"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Validator Agent", validator_agent)
    graph.add_node("analysisTool", ToolNode(tools=analysis_tools))
    graph.add_node("validatorTool", ToolNode(tools=validator_tool))

    graph.add_edge(START, "analyzer")

    graph.add_conditional_edges(
        "analyzer",
        should_call_tool,
        {
            "tool": "analysisTool",
            "refactor": "Refactor Agent"
        }
    )

    graph.add_edge("analysisTool", "analyzer")
    graph.add_edge("Refactor Agent", "Validator Agent")

    graph.add_conditional_edges(
        "Validator Agent",
        validator_router,
        {
            "refactor_agent": "Refactor Agent",
            "TOOL_CALL": "validatorTool",
            END: END
        }
    )

    graph.add_edge("validatorTool", "Validator Agent")

    return graph.compile()
