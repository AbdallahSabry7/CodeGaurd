"""Metric primitives shared by every evaluation task (stdlib only).

Key fixes vs the original harness
---------------------------------
* Multi-label macro-F1 is now also reported over labels WITH GOLD SUPPORT only
  (`macro_supported`). The original averaged every label including ones that
  never appear in the gold set; with small datasets those mechanical zeros
  dragged macro-F1 toward 0 even for a perfect system. We keep the naive macro
  for transparency and additionally surface MICRO-F1 (previously computed but
  never shown).
* `wilson_ci` gives a 95% confidence interval for any rate, so a single
  stochastic LLM run is not presented as an exact point estimate.
* `assert`s replaced with explicit ValueErrors (asserts vanish under `python -O`).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Sequence


def _check_len(pred, gold) -> None:
    if len(pred) != len(gold):
        raise ValueError(f"pred/gold length mismatch: {len(pred)} != {len(gold)}")


# ---------------------------------------------------------------------------
# Confidence interval
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (point, low, high) Wilson score interval for k successes of n."""
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


# ---------------------------------------------------------------------------
# Single-label accuracy
# ---------------------------------------------------------------------------

def accuracy(pred: Sequence, gold: Sequence) -> float:
    _check_len(pred, gold)
    if not gold:
        return 0.0
    return sum(1 for p, g in zip(pred, gold) if p == g) / len(gold)


# ---------------------------------------------------------------------------
# Complexity: ordered tiers -> exact + within-one-tier accuracy
# ---------------------------------------------------------------------------

COMPLEXITY_TIERS = [
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
]
_TIER_INDEX = {t: i for i, t in enumerate(COMPLEXITY_TIERS)}


def _tier_idx(label: str):
    return _TIER_INDEX.get((label or "").strip())


def complexity_scores(pred: Sequence[str], gold: Sequence[str]) -> dict:
    _check_len(pred, gold)
    n = len(gold)
    if n == 0:
        return {"exact": 0.0, "within_one_tier": 0.0, "n": 0}
    exact = within = 0
    for p, g in zip(pred, gold):
        pi, gi = _tier_idx(p), _tier_idx(g)
        if pi is None or gi is None:
            if (p or "").strip() == (g or "").strip():
                exact += 1
                within += 1
            continue
        if pi == gi:
            exact += 1
        if abs(pi - gi) <= 1:
            within += 1
    ex_pt, ex_lo, ex_hi = wilson_ci(exact, n)
    return {
        "exact": exact / n,
        "within_one_tier": within / n,
        "exact_ci": [ex_lo, ex_hi],
        "n": n,
    }


# ---------------------------------------------------------------------------
# Multi-label detection (SOLID principles, code smells): precision/recall/F1
# ---------------------------------------------------------------------------

def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,  # number of gold positives for this label
    }


def multilabel_scores(
    pred_sets: Iterable[Iterable[str]],
    gold_sets: Iterable[Iterable[str]],
    labels: Sequence[str],
) -> dict:
    """Per-label + macro/macro_supported/micro precision/recall/F1."""
    pred_sets = [set(p) for p in pred_sets]
    gold_sets = [set(g) for g in gold_sets]
    _check_len(pred_sets, gold_sets)

    per_label: dict[str, dict] = {}
    micro = defaultdict(int)
    for label in labels:
        tp = fp = fn = 0
        for p, g in zip(pred_sets, gold_sets):
            in_p, in_g = label in p, label in g
            if in_p and in_g:
                tp += 1
            elif in_p:
                fp += 1
            elif in_g:
                fn += 1
        per_label[label] = _prf(tp, fp, fn)
        micro["tp"] += tp
        micro["fp"] += fp
        micro["fn"] += fn

    supported = [l for l in labels if per_label[l]["support"] > 0]

    def _macro(keys: Sequence[str]) -> dict:
        if not keys:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "n_labels": 0}
        return {
            "precision": sum(per_label[k]["precision"] for k in keys) / len(keys),
            "recall": sum(per_label[k]["recall"] for k in keys) / len(keys),
            "f1": sum(per_label[k]["f1"] for k in keys) / len(keys),
            "n_labels": len(keys),
        }

    return {
        "per_label": per_label,
        "macro": _macro(list(labels)),         # naive: every label
        "macro_supported": _macro(supported),  # only labels present in gold
        "micro": _prf(micro["tp"], micro["fp"], micro["fn"]),
        "supported_labels": supported,
    }


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def rate(count: int, total: int) -> float:
    return count / total if total else 0.0
