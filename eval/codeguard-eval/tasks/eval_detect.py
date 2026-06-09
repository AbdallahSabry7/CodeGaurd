"""Language-detection sanity check (CodeGuard's regex-scoring front door).

This is a guardrail, not a headline metric — it just confirms the router sends
code to the right branch. Wire `detect` to your real detector to enable.
"""
from __future__ import annotations

from harness.report import append_section, md_table, pct

SAMPLES = [
    ("python", "def f(x):\n    return x + 1\n"),
    ("python", "import os\nprint(os.getcwd())\n"),
    ("java", "public class A { public static void main(String[] a){} }\n"),
    ("cpp", "#include <iostream>\nint main(){ std::cout << 1; }\n"),
]


_DETECT_ERROR = None


def _detect(code: str):
    global _DETECT_ERROR
    try:
        # === WIRE === point at your real detect-language function.
        import sys, os
        sys.path.insert(0, os.getenv("CODEGUARD_APP_DIR", "../app"))
        from graph.nodes import detect_language  # app/graph/nodes.py
        # the node reads state['original_code'] and returns state['source_language']
        state = detect_language({"original_code": code})
        return state.get("source_language") if isinstance(state, dict) else state
    except Exception as exc:
        _DETECT_ERROR = exc
        import sys
        print(f"[codeguard-eval] detect_language failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def run() -> dict:
    available = _detect(SAMPLES[0][1]) is not None
    if not available:
        why = f"{type(_DETECT_ERROR).__name__}: {_DETECT_ERROR}" if _DETECT_ERROR else "wire `detect_language`"
        append_section("## Language detection\n\nn/a — " + why)
        return {"available": False}
    hits = 0
    rows = []
    for gold, code in SAMPLES:
        pred = _detect(code)
        ok = (str(pred).lower() == gold)
        hits += int(ok)
        rows.append([gold, str(pred), "✅" if ok else "❌"])
    acc = hits / len(SAMPLES)
    append_section("## Language detection\n\n" + md_table(["Expected", "Predicted", ""], rows) + f"\n\nAccuracy: {pct(acc)}")
    return {"available": True, "accuracy": acc}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
