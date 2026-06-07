import json

from schemas.state import AgentState
from prompts.characterize_prompt import CHARACTERIZE_SYSTEM_PROMPT
from tools import capture
from llms import characterize_llm

import re


def _parse_spec(raw: str) -> dict:
    text = (raw or "").strip()

    # 1) strip ``` / ```json / ~~~ fences if the model added them
    fence = re.search(r"(?:```|~~~)(?:json)?\s*\n(.*?)(?:```|~~~)", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 2) if there's leading/trailing prose, grab the first {...} block
    if not text.startswith("{"):
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)

    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        # surface it instead of silently disabling the gate
        print(f"[characterizer] could not parse spec, got:\n{raw!r}")
        return {"mode": "stdio", "driver": "", "cases": []}

    spec.setdefault("mode", "stdio")
    spec.setdefault("driver", "")
    spec.setdefault("cases", [])
    return spec


def characterize_node(state: AgentState) -> dict:
    """Runs ONCE: build the golden master from the (Python) original.
    Idempotent - if one already exists, it is a no-op, so loop re-entry is cheap."""
    if state.get("golden_master"):
        return {}

    # Equivalence is checked in PYTHON space, so characterize the post-translation original.
    original = state.get("original_code_converted") or state["original_code"]
    messages = [
        ("system", CHARACTERIZE_SYSTEM_PROMPT),
        ("human", f"{original}"),
    ]
    spec = _parse_spec(characterize_llm.invoke(messages).content)
    gm = capture(original, spec)
    return {"golden_master": gm.to_json()}