import json

from schemas.state import AgentState
from prompts.characterize_prompt import CHARACTERIZE_SYSTEM_PROMPT
from tools import capture
from llms import characterize_llm


def _parse_spec(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("~~~"):                      
        raw = raw.strip("~")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
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