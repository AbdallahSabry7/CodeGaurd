from langchain.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from state import AgentState
from prompts import ANALYZER_PROMPT, REFACTOR_SYSTEM_PROMPT, REFACTOR_SYSTEM_PROMPT2, VALIDATOR_PROMPT
from tools import extract_code
from llms import LLM, LLM2, LLM3


def analyzer_agent(state: AgentState) -> AgentState:
    system_msg = SystemMessage(content=ANALYZER_PROMPT)
    response = LLM.invoke([system_msg] + state["messages"])

    new_report = state.get("analyzer_report", "")
    if not response.tool_calls and response.content:
        new_report = response.content

    return {
        "messages": [response],
        "analyzer_report": new_report
    }


def refactor_agent(state: AgentState) -> AgentState:
    iterations = state.get("refactor_iterations", 0)

    if iterations == 0:
        system_msg = SystemMessage(content=REFACTOR_SYSTEM_PROMPT)
        messages = [
            system_msg,
            HumanMessage(content=f"Analysis Report:\n{state['analyzer_report']}"),
            HumanMessage(content=f"Original Code:\n{state['original_code']}")
        ]
    else:
        system_msg = SystemMessage(content=REFACTOR_SYSTEM_PROMPT2)
        messages = [
            system_msg,
            HumanMessage(content=f"Validator Report:\n{state['validator_report']}"),
            HumanMessage(content=f"Current Refactored Code:\n{state['refactored_code']}")
        ]

    response = LLM2.invoke(messages)

    extracted = extract_code(response.content)
    refactored = extracted if extracted else response.content

    return {
        "messages": [response],
        "refactored_code": refactored,
        "refactor_iterations": iterations + 1
    }


def validator_agent(state: AgentState) -> AgentState:
    system_msg = SystemMessage(content=VALIDATOR_PROMPT)

    messages = [
        system_msg,
        HumanMessage(content=f"Analysis Report:\n{state['analyzer_report']}"),
        HumanMessage(content=f"Refactored Code:\n{state['refactored_code']}"),
    ] + state["messages"][-5:]

    response = LLM3.invoke(messages)

    new_report = state.get("validator_report", "")
    if not response.tool_calls and response.content:
        new_report = response.content

    return {
        "messages": [response],
        "validator_report": new_report
    }
