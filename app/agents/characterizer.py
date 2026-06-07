import json

from schemas.state import AgentState
from prompts.characterize_prompt import CHARACTERIZE_SYSTEM_PROMPT
from llms import characterize_llm

import re


def _parse_spec(raw: str) -> dict:
    text = (raw or "").strip()

    fence = re.search(r"(?:```|~~~)(?:json)?\s*\n(.*?)(?:```|~~~)", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    if not text.startswith("{"):
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)

    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        print(f"[characterizer] could not parse spec, got:\n{raw!r}")
        return {"mode": "stdio", "driver": "", "cases": []}

    spec.setdefault("mode", "stdio")
    spec.setdefault("driver", "")
    spec.setdefault("cases", [])
    return spec


def characterize_node(state: AgentState) -> dict:
    """Runs ONCE: ask the LLM to SUGGEST black-box input cases. No execution here."""
    if state.get("test_inputs") is not None:
        return {}                                  

    original = state.get("original_code_converted") or state["original_code"]
    messages = [
        ("system", CHARACTERIZE_SYSTEM_PROMPT),
        ("human", f"{original}"),
    ]
    spec = _parse_spec(characterize_llm.invoke(messages).content)
    return {
        "test_inputs": spec.get("cases", []),
        "test_mode": spec.get("mode", "stdio"),
        "test_driver": spec.get("driver", ""),
    }