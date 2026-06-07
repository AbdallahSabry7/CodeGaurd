import re

from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AgentState
from prompts import REFACTOR_SYSTEM_PROMPT, REFACTOR_SYNTAX_PROMPT
from llms import refactor_llm


def _format_directives(directives: list[dict]) -> str:
    """Render the architect's vetted directives as a numbered, prioritized list."""
    if not directives:
        return "No actionable directives — return the code unchanged."
    lines = []
    for d in directives:
        lines.append(
            f"{d['id']}. [{d['severity']}] ({d['category']}) {d['label']} @ {d['location']}\n"
            f"   -> {d['directive']}"
        )
    return "\n".join(lines)


def refactor_agent(state: AgentState) -> dict:
    syntax_error = state.get("refactor_syntax_error")
    execution_result = state.get("execution_result") or ""

    code = state.get("refactored_code") or state["original_code"]

    if syntax_error:
        report = f"SyntaxError in your refactored code:\n{syntax_error}"
        prompt = REFACTOR_SYNTAX_PROMPT
    elif "FAIL" in execution_result:
        report = execution_result
        prompt = REFACTOR_SYNTAX_PROMPT
    else:
        report = _format_directives(state.get("refactor_directives") or [])
        prompt = REFACTOR_SYSTEM_PROMPT

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"Code:\n{code}"),
        HumanMessage(content=f"Report:\n{report}"),
    ]

    response = refactor_llm.invoke(messages)
    if not response.content:
        raise ValueError("refactor_llm did not return any content in the response.")

    raw = response.content
    fenced = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    clean_code = fenced.group(1).strip() if fenced else raw.strip()

    return {
        "messages": [response],
        "refactored_code": clean_code,
        "refactor_syntax_error": None,
        "refactor_iterations": state.get("refactor_iterations", 0) + 1,
    }