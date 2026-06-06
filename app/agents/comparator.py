from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AgentState
from prompts import COMPARATOR_PROMPT
from llms import LLM3


def comparator_agent(state: AgentState) -> AgentState:
    messages = [
        SystemMessage(content=COMPARATOR_PROMPT),
        HumanMessage(content=(
            "<original_report>\n"
            f"{state['architect_baseline_report']}\n"
            "</original_report>\n\n"
            "<refactored_report>\n"
            f"{state['architect_report']}\n"
            "</refactored_report>"
        )),
    ]
    response = LLM3.invoke(messages)
    if not response.content:
        raise ValueError("LLM3 did not return any content in the response.")
    return {
        "messages": [response],
        "comparator_report": response.content,
    }