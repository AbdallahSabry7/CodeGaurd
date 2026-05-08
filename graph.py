from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from state import AgentState
from agents import analyzer_agent, refactor_agent, validator_agent
from tools import analysis_tools, validator_tool
from langchain_core.messages import ToolMessage

analysis_tools_by_name = {
    tool.name: tool
    for tool in analysis_tools
}

def analyzer_tool_node(state: AgentState):

    last_message = state["analyzer_messages"][-1]

    outputs = []

    for tool_call in last_message.tool_calls:

        tool = analysis_tools_by_name[tool_call["name"]]

        result = tool.invoke(tool_call["args"])

        outputs.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
        )

    return {
        "analyzer_messages": outputs
    }

validator_tools_by_name = {
    tool.name: tool
    for tool in validator_tool
}

def validator_tool_node(state: AgentState):

    last_message = state["validator_messages"][-1]

    outputs = []

    for tool_call in last_message.tool_calls:

        tool = validator_tools_by_name[tool_call["name"]]

        result = tool.invoke(tool_call["args"])

        outputs.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
        )

    return {
        "validator_messages": list(state.get("validator_messages", [])) + outputs
    }


def should_call_tool(state: AgentState) -> str:
    last_message = state["analyzer_messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool"
    return "refactor"


def validator_router(state: AgentState) -> str:
    last_message = state["validator_messages"][-1]
    iterations = state.get("refactor_iterations", 0)

    if iterations >= 3:
        return "end"

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "TOOL_CALL"
    
    if not last_message.content or not last_message.content.strip():
        return "end"

    if isinstance(last_message, AIMessage) and last_message.content and "PASS" in last_message.content:
        return "end"

    return "refactor_agent"

def clear_validator_memory(state):

    return {
        "validator_messages": []
    }


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("analyzer", analyzer_agent)
    graph.add_node("Refactor Agent", refactor_agent)
    graph.add_node("Validator Agent", validator_agent)
    graph.add_node("analysisTool", analyzer_tool_node)
    graph.add_node("validatorTool", validator_tool_node)
    graph.add_node("clear_validator_memory", clear_validator_memory)

    graph.add_edge(START, "analyzer")

    graph.add_conditional_edges(
        "analyzer",
        should_call_tool,
        {
            "tool": "analysisTool",
            "refactor": "Refactor Agent",
        },
    )

    graph.add_edge("analysisTool", "analyzer")
    graph.add_edge("Refactor Agent", "Validator Agent")

    graph.add_conditional_edges(
        "Validator Agent",
        validator_router,
        {
            "refactor_agent": "clear_validator_memory",
            "TOOL_CALL": "validatorTool",
            "end": END,
        },
    )
    graph.add_edge("clear_validator_memory", "Refactor Agent")

    graph.add_edge("validatorTool", "Validator Agent")

    return graph.compile()