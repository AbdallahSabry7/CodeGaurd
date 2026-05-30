import re
from urllib import response

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from schemas import AgentState
from prompts import  COMPARATOR_PROMPT
from llms import LLM3


def comparator_agent(state: AgentState) -> AgentState:
    messages = [
        SystemMessage(content=COMPARATOR_PROMPT),
        HumanMessage(content=(
            "<original_report>\n"
            f"{state['original_analyzer_report']}\n"
            "</original_report>\n\n"
            "<refactored_report>\n"
            f"{state['analyzer_report']}\n"
            "</refactored_report>"
        )),
    ]

    response = LLM3.invoke(messages)

    new_report = state.get("comparator_report", "")
    if response.content:
        new_report = response.content

    return {
        "messages": [response],
        "comparator_report": new_report,
    }