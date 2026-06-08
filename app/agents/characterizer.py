
from schemas.state import AgentState
from prompts.characterize_prompt import CHARACTERIZE_SYSTEM_PROMPT
from llms import characterize_structured
from pydantic import BaseModel



def characterize_node(state: AgentState) -> dict:
    if state.get("test_inputs") is not None:
        return {}
    original = state.get("original_code_converted") or state["original_code"]

    try:
        result = characterize_structured.invoke([
            ("system", CHARACTERIZE_SYSTEM_PROMPT),
            ("human", original),
        ])
        # include_raw=True -> {"raw", "parsed", "parsing_error"}
        parsed = result.get("parsed") if isinstance(result, dict) and "parsed" in result else result
    except Exception as e:
        print(f"[characterizer] generation failed: {e!r}")
        parsed = None

    # Normalize to a plain dict regardless of model-vs-dict
    if isinstance(parsed, BaseModel):
        spec = parsed.model_dump()
    elif isinstance(parsed, dict):
        spec = parsed
    else:
        spec = {}

    cases = spec.get("cases") or []
    if not cases:
        print("[characterizer] WARNING: no cases produced — regression will be INCONCLUSIVE")

    return {
        "test_inputs": cases,                       # list[dict] either way
        "test_mode": spec.get("mode", "stdio"),
        "test_driver": spec.get("driver", ""),
    }