import re
from urllib import response

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from state import AgentState
from prompts import ANALYZER_PROMPT, COMPARATOR_PROMPT, EXECUTER_PROMPT, REFACTOR_SYSTEM_PROMPT
from llms import LLM, LLM2, LLM3

import inspect


def analyzer_agent(state: AgentState) -> AgentState:
    if state.get("refactored_code"):
        code_to_analyze = state["refactored_code"]
    else:
        code_to_analyze = state["original_code"]

    analyzer_messages = state.get("analyzer_messages", [])
    system_msg = SystemMessage(content=ANALYZER_PROMPT)
    messages = [system_msg, HumanMessage(content=code_to_analyze)] + analyzer_messages

    response = LLM.invoke(messages)

    # Only update report if LLM actually generated content (not a tool call)
    new_report = state.get("analyzer_report", "")
    if not response.tool_calls and response.content and response.content.strip():
        new_report = response.content

    update = {
        "messages": [response],
        "analyzer_messages": analyzer_messages + [response],
        "analyzer_report": new_report,
    }

    if (
        state.get("refactor_iterations", 0) == 0
        and new_report
        and not state.get("original_analyzer_report")
    ):
        update["original_analyzer_report"] = new_report

    return update


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
    system_msg = SystemMessage(content=COMPARATOR_PROMPT)
    messages = [
        system_msg,
        HumanMessage(
            content=(
                f"Original Report:\n{state['original_analyzer_report']}\n\n"
                f"Refactored Report:\n{state['analyzer_report']}"
            )
        ),
    ]

    response = LLM3.invoke(messages)

    new_report = state.get("comparator_report", "")
    if response.content:
        new_report = response.content

    return {
        "messages": [response],
        "comparator_report": new_report,
    }


def executer_agent(state: AgentState) -> AgentState:
    system_msg = SystemMessage(content=EXECUTER_PROMPT)
    prior = state.get("executer_messages", [])
    
    print(f"[DEBUG executer_agent] prior messages types: {[type(m).__name__ for m in prior]}")
    print(f"[DEBUG executer_agent] execution_result: {state.get('execution_result')}")
    
    already_executed = any(isinstance(m, ToolMessage) for m in prior)
    print(f"[DEBUG executer_agent] already_executed: {already_executed}")
    
    if already_executed:
        final_prompt = SystemMessage(content=(
            "The tool has already run. "
            "Based on the tool result in the messages, output ONLY the final report. "
            "Do NOT call the tool again."
        ))
        messages = [final_prompt] + prior
    else:
        messages = [system_msg] + prior

    response = LLM3.invoke(messages)
    
    print(f"[DEBUG executer_agent] response tool_calls: {response.tool_calls}")
    print(f"[DEBUG executer_agent] response content: {response.content[:100] if response.content else None}")

    new_result = state.get("execution_result", "")
    if not response.tool_calls and response.content:
        new_result = response.content

    return {
        "messages": [response],
        "executer_messages": [response],
        "execution_result": new_result,
    }