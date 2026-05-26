import re
from urllib import response

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from state import AgentState
from prompts import  COMPARATOR_PROMPT, REFACTOR_SYSTEM_PROMPT
from llms import LLM2, LLM3

def refactor_agent(state: AgentState) -> AgentState:
    iterations = state.get("refactor_iterations", 0)
    syntax_error = state.get("refactor_syntax_error")

    feedback = (
        f"SyntaxError in your refactored code: {syntax_error}" if syntax_error
        else state.get("comparator_report") if "FAIL" in (state.get("comparator_report") or "")
        else state.get("execution_result") if "FAIL" in (state.get("execution_result") or "")
        else None
    )

    code = state["original_code"] if iterations == 0 else state["refactored_code"]
    report = state["analyzer_report"] if iterations == 0 else feedback

    system_msg = SystemMessage(content=REFACTOR_SYSTEM_PROMPT)
    messages = [
        system_msg,
        HumanMessage(content=f"Code:\n{code}"),
        HumanMessage(content=f"Report:\n{report}"),
    ]

    response = LLM2.invoke(messages)
    if not response.content:
        raise ValueError("LLM2 did not return any content in the response.")

    raw = response.content
    fenced = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    clean_code = fenced.group(1).strip() if fenced else raw.strip()

    return {
        "messages": [response],
        "refactored_code": clean_code,
        "refactor_syntax_error": None,
        "refactor_iterations": iterations + 1,
    }


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
