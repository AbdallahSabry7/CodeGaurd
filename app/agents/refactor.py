import re
from urllib import response

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from schemas import AgentState
from prompts import  REFACTOR_SYSTEM_PROMPT , REFACTOR_SYSTEM_PROMPT2
from llms import LLM2

def refactor_agent(state: AgentState) -> AgentState:
    iterations = state.get("refactor_iterations", 0)
    syntax_error = state.get("refactor_syntax_error")

    feedback = (
        f"SyntaxError in your refactored code: {syntax_error}" if syntax_error
        else state.get("comparator_report") if "FAIL" in (state.get("comparator_report") or "")
        else state.get("execution_result") if "FAIL" in (state.get("execution_result") or "")
        else None
    )
    if iterations == 0:
        code = state["original_code"]
        report = state["analyzer_report"]
        prompt = REFACTOR_SYSTEM_PROMPT
    else:
        code = state["refactored_code"]
        report = feedback
        prompt = REFACTOR_SYSTEM_PROMPT2

    system_msg = SystemMessage(content=prompt)
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
