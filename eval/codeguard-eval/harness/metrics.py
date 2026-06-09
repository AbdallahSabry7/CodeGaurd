"""Metric primitives shared by every evaluation task.

Pure-Python, no heavy deps. Everything returns plain dicts so the report layer
can dump them straight to JSON / Markdown / CSV.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Classification (single-label): accuracy
# ---------------------------------------------------------------------------


def accuracy(pred: Sequence, gold: Sequence) -> float:
    assert len(pred) == len(gold)
    if not gold:
        return 0.0
    hits = sum(1 for p, g in zip(pred, gold) if p == g)
    return hits / len(gold)


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
]
_TIER_INDEX = {t: i for i, t in enumerate(COMPLEXITY_TIERS)}


def _tier_idx(label: str):
    return _TIER_INDEX.get((label or "").strip())


def complexity_scores(pred: Sequence[str], gold: Sequence[str]) -> dict:
    assert len(pred) == len(gold)
    n = len(gold)
    if n == 0:
        return {"exact": 0.0, "within_one_tier": 0.0, "n": 0}
    exact = 0
    within = 0
    for p, g in zip(pred, gold):
        pi, gi = _tier_idx(p), _tier_idx(g)
        if pi is None or gi is None:
            # Unknown tier label -> only an exact string match can count.
            if (p or "").strip() == (g or "").strip():
                exact += 1
                within += 1
            continue
        if pi == gi:
            exact += 1
        if abs(pi - gi) <= 1:
            within += 1
    return {"exact": exact / n, "within_one_tier": within / n, "n": n}


# ---------------------------------------------------------------------------
# Multi-label detection (SOLID principles, code smells): precision/recall/F1
# ---------------------------------------------------------------------------


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def multilabel_scores(
    pred_sets: Iterable[Iterable[str]],
    gold_sets: Iterable[Iterable[str]],
    labels: Sequence[str],
) -> dict:
    """Per-label and macro/micro precision/recall/F1 for multi-label detection."""
    pred_sets = [set(p) for p in pred_sets]
    gold_sets = [set(g) for g in gold_sets]
    assert len(pred_sets) == len(gold_sets)

    per_label = {}
    micro = defaultdict(int)
    for label in labels:
        tp = fp = fn = 0
        for p, g in zip(pred_sets, gold_sets):
            in_p, in_g = label in p, label in g
            if in_p and in_g:
                tp += 1
            elif in_p and not in_g:
                fp += 1
            elif (not in_p) and in_g:
                fn += 1
        per_label[label] = _prf(tp, fp, fn)
        micro["tp"] += tp
        micro["fp"] += fp
        micro["fn"] += fn

    macro = {
        "precision": sum(v["precision"] for v in per_label.values()) / len(labels) if labels else 0.0,
        "recall": sum(v["recall"] for v in per_label.values()) / len(labels) if labels else 0.0,
        "f1": sum(v["f1"] for v in per_label.values()) / len(labels) if labels else 0.0,
    }
    return {
        "per_label": per_label,
        "macro": macro,
        "micro": _prf(micro["tp"], micro["fp"], micro["fn"]),
    }


# ---------------------------------------------------------------------------
# Refactor task rates
# ---------------------------------------------------------------------------


def rate(count: int, total: int) -> float:
    return count / total if total else 0.0
