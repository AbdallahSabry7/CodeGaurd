import re

from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AgentState
from prompts import (
    REFACTOR_SYSTEM_PROMPT,
    REFACTOR_SYSTEM_PROMPT2,
    REFACTOR_SYNTAX_PROMPT,
)
from llms import LLM2


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


def refactor_agent(state: AgentState) -> AgentState:
    iterations = state.get("refactor_iterations", 0)
    syntax_error = state.get("refactor_syntax_error")
    comparator_report = state.get("comparator_report") or ""
    execution_result = state.get("execution_result") or ""

    if iterations == 0:
        # First pass: apply the architect's vetted, prioritized directives.
        code = state["original_code"]
        report = _format_directives(state.get("refactor_directives") or [])
        prompt = REFACTOR_SYSTEM_PROMPT
    else:
        # Re-entry: pick the prompt that matches WHY we were sent back.
        code = state["refactored_code"]
        if syntax_error:
            report = f"SyntaxError in your refactored code:\n{syntax_error}"
            prompt = REFACTOR_SYNTAX_PROMPT
        elif "FAIL" in execution_result:
            report = execution_result
            prompt = REFACTOR_SYNTAX_PROMPT
        else:
            report = comparator_report
            prompt = REFACTOR_SYSTEM_PROMPT2

    messages = [
        SystemMessage(content=prompt),
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