from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from state import AgentState
from prompts import ANALYZER_PROMPT, REFACTOR_SYSTEM_PROMPT, REFACTOR_SYSTEM_PROMPT2, VALIDATOR_PROMPT
from llms import LLM, LLM2, LLM3


def analyzer_agent(state: AgentState) -> AgentState:

    code_to_analyze = state.get("refactored_code") or state["original_code"]
    code_to_analyze = code_to_analyze.replace("\\n", "\n").strip()

    analyzer_messages = state.get("analyzer_messages", [])

    system_msg = SystemMessage(content=ANALYZER_PROMPT)
    messages = [system_msg, HumanMessage(content=code_to_analyze)] + analyzer_messages

    response = LLM.invoke(messages)

    new_report = state.get("analyzer_report", "")
    if not response.tool_calls and response.content:
        new_report = response.content

    update = {
        "messages": [response],
        "analyzer_messages": analyzer_messages + [response],
        "analyzer_report": new_report
    }

    if (
        state.get("refactor_iterations", 0) == 0
        and not response.tool_calls
        and response.content
    ):
        update["original_analyzer_report"] = new_report

    return update


def refactor_agent(state: AgentState) -> AgentState:
    iterations = state.get("refactor_iterations", 0)

    if iterations == 0:
        system_msg = SystemMessage(content=REFACTOR_SYSTEM_PROMPT)
        messages = [
            system_msg,
            HumanMessage(content=f"Original Code:\n{state['original_code']}"),
            HumanMessage(content=f"Analysis Report:\n{state['analyzer_report']}"),
        ]
    else:
        system_msg = SystemMessage(content=REFACTOR_SYSTEM_PROMPT2)
        messages = [
            system_msg,
            HumanMessage(content=f"Original Code:\n{state['original_code']}"),
            HumanMessage(content=f"Analysis Report:\n{state['analyzer_report']}"),
            HumanMessage(content=f"Current Refactored Code:\n{state['refactored_code']}"),
            HumanMessage(content=f"Validator Report:\n{state['validator_report']}"),
        ]

    response = LLM2.invoke(messages)

    return {
        "messages": [response],
        "refactored_code": response.content,
        "refactor_iterations": iterations + 1,
    }


def validator_agent(state: AgentState) -> AgentState:
    system_msg = SystemMessage(content=VALIDATOR_PROMPT)

    base_messages = [
        system_msg,
        HumanMessage(
            content=(
                f"Original Report:\n{state['original_analyzer_report']}\n\n"
                f"Refactored Report:\n{state['analyzer_report']}\n\n"
                f"Refactored Code:\n{state['refactored_code']}"
            )
        ),
    ]

    prior = state.get("validator_messages", [])
    messages = base_messages + prior

    response = LLM3.invoke(messages)

    new_report = state.get("validator_report", "")
    if not response.tool_calls and response.content:
        new_report = response.content

    return {
        "messages": [response],
        "validator_messages": prior + [response],
        "validator_report": new_report,
    }