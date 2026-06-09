"""Complexity task: CodeGuard symbolic analyzer vs raw-LLM baseline.

Metric: exact-tier accuracy + within-one-tier accuracy.
"""
from __future__ import annotations

from adapters import baseline_llm, codeguard_adapter
from harness import metrics
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct


def run() -> dict:
    data = load_jsonl("datasets/complexity.jsonl")
    gold = [r["label"] for r in data]

    base_pred = [baseline_llm.predict_complexity(r["code"]) for r in data]
    base = metrics.complexity_scores(base_pred, gold)

    result = {"n": len(data), "baseline": base}

    rows = [["Raw LLM (baseline)", pct(base["exact"]), pct(base["within_one_tier"])]]

    note = ""
    if codeguard_adapter.pipeline_available():
        import sys
        cg_pred = [codeguard_adapter.analyze(r["code"])["complexity"] for r in data]
        cg = metrics.complexity_scores(cg_pred, gold)
        result["codeguard"] = cg
        result["codeguard_pred"] = cg_pred
        rows.append(["CodeGuard (AST)", pct(cg["exact"]), pct(cg["within_one_tier"])])
        err = codeguard_adapter.complexity_error()
        if err:
            print(f"[codeguard-eval] complexity_error: {err}", file=sys.stderr)
            note += (
                "\n\n> \u26a0\ufe0f CodeGuard complexity tool raised/returned an error: "
                f"`{err}`\n>\n> Common causes: missing `numpy`/`pandas`/`scikit-learn`/`joblib` "
                "in the venv, a missing `services/tests/codeComplexty_test.py` (imported by "
                "`hybrid_time_complexty`), or a scikit-learn version mismatch when loading "
                "`hybrid.joblib`."
            )
        if cg["exact"] < 1.0:
            valid = set(metrics.COMPLEXITY_TIERS)
            brk = []
            for r, p in zip(data, cg_pred):
                g = str(r.get("label", ""))
                ps = "" if p is None else str(p)
                if ps.strip() == g.strip():
                    mark = "\u2705"
                elif ps.strip() in valid:
                    mark = "\u274c wrong tier"
                else:
                    mark = "\u26a0\ufe0f unrecognized label"
                brk.append([str(r.get("id", "?")), g, repr(ps), mark])
                print(f"[codeguard-eval] complexity {r.get('id','?')}: gold={g!r} cg={ps!r}", file=sys.stderr)
            note += (
                "\n\n**CodeGuard per-snippet predictions** (exact strings):\n\n"
                + md_table(["id", "Gold", "CodeGuard predicted", "Match"], brk)
                + "\n\n> The scorer only recognizes these tier strings: "
                + ", ".join(f"`{t}`" for t in metrics.COMPLEXITY_TIERS)
                + ". Any prediction outside this set is wrong (and counts 0 toward within-one-tier). "
                "If the predictions above look like `linear`, `2`, `Unknown`, or `O(N)`, your model's "
                "output labels are not being mapped to these Big-O strings \u2014 fix `_LABEL_TO_BIG_O` "
                "/ `load_and_predict` in `app/services/complexity.py`."
            )
    else:
        result["codeguard"] = None
        rows.append(["CodeGuard (AST)", "n/a — wire adapter", "n/a"])

    append_section(
        "## Complexity (Big-O classification)\n\n"
        + f"Dataset size: {len(data)}\n\n"
        + md_table(["System", "Exact-tier acc", "Within-1-tier acc"], rows)
        + note
    )
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
