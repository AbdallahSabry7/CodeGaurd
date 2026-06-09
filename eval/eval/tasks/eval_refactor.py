"""Task: behavior-preserving refactoring + verification-gate stress test.

This is the heart of the thesis claim ('refactor WITHOUT breaking behavior').
Two parts:

Part 1 - Refactor outcomes per system
    Every refactor is classified into one of:
      * improved_safe   : code actually changed AND behavior preserved (oracle)
      * safe_noop       : system returned the original unchanged (safe but useless)
      * unsafe_escaped  : behavior changed -> a regression slipped through
      * unverified      : original itself could not be executed
    This separates USEFUL work from merely SAFE work -- the original harness
    scored an identity 'refactor' as a perfect pass.

Part 2 - Verification-gate confusion matrix (the gate metric)
    A gate is a binary classifier (accept / block a candidate). To measure it we
    need known-unsafe candidates, so we MUTATE each snippet and keep the mutants
    the oracle confirms change behavior (the positive/unsafe class); the
    untouched original is the safe class. We then compare two gate policies:
      * weak gate   : checks only the declared seed tests (the old behavior)
      * strong gate : also checks generated inputs (the proposed behavior)
    against ground truth (a large generated-input oracle). Headline metric:
      escape_rate = unsafe candidates wrongly ACCEPTED / all unsafe   (-> 0 good)
    plus catch_rate and over_block_rate. The weak-vs-strong gap quantifies why
    generated-input checking matters -- and is the template for scoring your
    real LangGraph gate once wired.
"""
from __future__ import annotations

from adapters import baseline_llm
from adapters import codeguard_adapter as cg
from harness import metrics
from harness.differential import compare, verdict_from, check
from harness.mutation import candidate_mutants
from harness.oracle import build_input_set
from harness.report import append_section, md_table, pct

GT_BUDGET = 120     # ground-truth oracle input budget
STRONG_BUDGET = 30  # strong gate generated-input budget
WEAK_BUDGET = 0     # weak gate: seed tests only
TIMEOUT = 5.0


# --- Part 1 -----------------------------------------------------------------

def _classify(original: str, candidate: str, entry: str, cases: list[dict]) -> str:
    if candidate is None or candidate.strip() == original.strip():
        return "safe_noop"
    res = check(original, candidate, entry, cases, n_generated=STRONG_BUDGET, timeout=TIMEOUT)
    if res["verdict"] == "unverified":
        return "unverified"
    if res["verdict"] == "preserved":
        return "improved_safe"
    return "unsafe_escaped"


def _outcomes(rows, refactor_fn, name):
    counts = {"improved_safe": 0, "safe_noop": 0, "unsafe_escaped": 0, "unverified": 0}
    for r in rows:
        cand = refactor_fn(r["code"])
        counts[_classify(r["code"], cand, r["entry"], r["tests"])] += 1
    n = len(rows)
    return {"name": name, "counts": counts, "n": n,
            "useful_safe_rate": metrics.rate(counts["improved_safe"], n),
            "escape_rate": metrics.rate(counts["unsafe_escaped"], n)}


# --- Part 2 -----------------------------------------------------------------

def _gate_records(rows):
    recs = []
    for r in rows:
        code, entry, cases = r["code"], r["entry"], r["tests"]
        seed_args, gen = build_input_set(cases, GT_BUDGET)
        all_args = seed_args + gen
        n_seed = len(seed_args)
        candidates = [("safe", code)] + [("mut", m) for m in candidate_mutants(code)]
        for kind, cand in candidates:
            matches, orig_runnable = compare(code, cand, entry, all_args, TIMEOUT)
            gt = verdict_from(matches, orig_runnable)
            if kind == "mut" and gt != "changed":
                continue  # mutation did not actually change behavior; discard
            recs.append({
                "unsafe": gt == "changed",
                "weak_block": verdict_from(matches[:n_seed + WEAK_BUDGET], orig_runnable) != "preserved",
                "strong_block": verdict_from(matches[:n_seed + STRONG_BUDGET], orig_runnable) != "preserved",
            })
    return recs


def _confusion(recs, block_key):
    unsafe = [r for r in recs if r["unsafe"]]
    safe = [r for r in recs if not r["unsafe"]]
    caught = sum(1 for r in unsafe if r[block_key])
    over = sum(1 for r in safe if r[block_key])
    return {
        "n_unsafe": len(unsafe), "n_safe": len(safe),
        "caught": caught, "escaped": len(unsafe) - caught, "over_block": over,
        "escape_rate": metrics.rate(len(unsafe) - caught, len(unsafe)),
        "catch_rate": metrics.rate(caught, len(unsafe)),
        "over_block_rate": metrics.rate(over, len(safe)),
    }


def run(rows: list[dict]) -> dict:
    # Part 1
    systems = {"baseline": _outcomes(rows, baseline_llm.refactor, "Raw LLM (no gate)")}
    if cg.pipeline_available():
        def _cg_refactor(code):
            out = cg.refactor_full(code)
            if not out:
                return code
            refactored, _verdict = out
            return refactored or code
        systems["codeguard"] = _outcomes(rows, _cg_refactor, "CodeGuard (full)")

    out_rows = []
    for key, s in systems.items():
        c = s["counts"]
        out_rows.append([s["name"], c["improved_safe"], c["safe_noop"], c["unsafe_escaped"],
                         c["unverified"], pct(s["useful_safe_rate"]), pct(s["escape_rate"])])
    part1 = md_table(
        ["System", "Improved+Safe", "Safe no-op", "Unsafe escaped", "Unverified",
         "Useful&Safe rate", "Escape rate"],
        out_rows,
    )

    # Part 2
    recs = _gate_records(rows)
    weak = _confusion(recs, "weak_block")
    strong = _confusion(recs, "strong_block")

    def grow(name, c):
        return [name, c["n_unsafe"], c["n_safe"], pct(c["catch_rate"]),
                pct(c["escape_rate"]), pct(c["over_block_rate"])]

    part2 = md_table(
        ["Gate policy", "#Unsafe", "#Safe", "Catch rate", "Escape rate (lower=better)", "Over-block rate"],
        [grow("Weak gate (seed tests only)", weak), grow("Strong gate (+generated inputs)", strong)],
    )

    append_section(
        "## Behavior-preserving refactoring\n\n"
        "**Part 1 - refactor outcomes** (useful = code changed AND behavior preserved):\n\n"
        + part1
        + "\n\n**Part 2 - verification-gate confusion matrix** "
        "(unsafe candidates synthesised by mutation; ground truth from a "
        f"{GT_BUDGET}-input oracle):\n\n"
        + part2
        + "\n\n_Escape rate = unsafe candidates wrongly accepted. The strong gate's "
        "lower escape rate is the measurable value of generated-input checking._"
    )

    return {"n": len(rows), "systems": systems,
            "gate": {"weak": weak, "strong": strong}}
