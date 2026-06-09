"""Evaluate the complexity analyzer against CodeComplex.

Layout assumed:
    repo/
      complexity.py             <- the analyzer module
      <subdir>/eval_codecomplex.py   <- this file (one directory below)

Usage:
    from eval_codecomplex import evaluate
    df = evaluate(df)   # df needs columns CODE_COL and TRUE_COL

Adjust CODE_COL / TRUE_COL below if your dataframe columns differ.
"""
import re
import sys
from pathlib import Path
from collections import Counter
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

# analyzer module (complexity.py) lives one directory above this script
sys.path.append(str(Path(__file__).resolve().parent.parent))
from complexity1 import analyze, estimate_complexity

CODE_COL = "code"          # <-- column with the source code
TRUE_COL = "true_time"     # <-- column with the gold label (straight quotes!)

# --------------------------------------------------------------------------
# 1) map analyzer Big-O string -> CodeComplex label
# --------------------------------------------------------------------------
COMPLEXITY_ORDER = ["constant", "logn", "linear", "nlogn", "quadratic", "cubic", "np"]
_RANK = {c: i for i, c in enumerate(COMPLEXITY_ORDER)}
_SUP = str.maketrans({
    "\u00b2": "2", "\u00b3": "3", "\u2074": "4", "\u2075": "5",
    "\u2076": "6", "\u2077": "7", "\u2078": "8", "\u2079": "9",
    "\u00b9": "1", "\u2070": "0",
})


def to_benchmark_class(time_str: str) -> str:
    if not time_str or time_str == "Error":
        return "unknown"
    if "\u207f" in time_str or re.search(r"\d\s*(?:\^|\*\*)\s*n", time_str):
        return "np"
    s = time_str.translate(_SUP)
    s = re.sub(r"n\s*([0-9])", r"n^\1", s).lower()
    has_log = "log" in s
    m = re.search(r"n\s*\^\s*([0-9]+)", s)
    if m:
        degree = int(m.group(1))
    elif re.search(r"\bn\b", s.replace("log n", "")):
        degree = 1
    else:
        degree = 0
    if degree == 0:
        return "logn" if has_log else "constant"
    if degree == 1:
        return "nlogn" if has_log else "linear"
    if degree == 2:
        return "quadratic"
    return "cubic"


def predict_label(code_str: str) -> str:
    t, _ = estimate_complexity(code_str)
    return to_benchmark_class(t)


def predict_with_trace(code_str: str):
    """Return (label, raw_bigO, reason, fired_signals_str) for logging."""
    try:
        r = analyze(code_str)
        return to_benchmark_class(r.time_complexity), r.time_complexity, r.time_reason, r.trace
    except Exception as exc:
        return "unknown", "Error", f"{type(exc).__name__}: {exc}", ""


# --------------------------------------------------------------------------
# 2) HC-Score
# --------------------------------------------------------------------------
def hc_score(y_true, y_pred, window=None):
    w = len(COMPLEXITY_ORDER) if window is None else window
    total, n = 0.0, 0
    for t, p in zip(y_true, y_pred):
        n += 1
        if t not in _RANK or p not in _RANK:
            continue
        total += max(1.0 - abs(_RANK[p] - _RANK[t]) / w, 0.0)
    return total / n if n else 0.0


# --------------------------------------------------------------------------
# 3) run
# --------------------------------------------------------------------------
def evaluate(df: pd.DataFrame, debug_csv: str = "predictions_debug.csv",
             breakdown_cells=(("linear", "quadratic"), ("nlogn", "quadratic"),
                              ("np", "quadratic"), ("logn", "linear"))) -> pd.DataFrame:
    df = df.copy()
    traced = df[CODE_COL].apply(predict_with_trace)
    df["pred"] = [t[0] for t in traced]
    df["bigO"] = [t[1] for t in traced]
    df["reason"] = [t[2] for t in traced]
    df["signals"] = [t[3] for t in traced]

    print("accuracy      :", accuracy_score(df[TRUE_COL], df["pred"]))
    print("HC-Score      :", hc_score(df[TRUE_COL], df["pred"]))
    print("HC-Score (w=2):", hc_score(df[TRUE_COL], df["pred"], window=2))
    print("HC-Score (w=1):", hc_score(df[TRUE_COL], df["pred"], window=1))
    print("\nClassification Report:")
    print(classification_report(df[TRUE_COL], df["pred"]))
    print("Confusion Matrix (rows=true, cols=pred, order = COMPLEXITY_ORDER):")
    print(confusion_matrix(df[TRUE_COL], df["pred"], labels=COMPLEXITY_ORDER))

    # ---- per-prediction logging ------------------------------------------
    df.to_csv(debug_csv, index=False)
    print(f"\nWrote per-prediction log -> {debug_csv}")

    # ---- which signals drive the worst error cells -----------------------
    for true_lbl, pred_lbl in breakdown_cells:
        sub = df[(df[TRUE_COL] == true_lbl) & (df["pred"] == pred_lbl)]
        print(f"\n=== {true_lbl} -> {pred_lbl}  ({len(sub)} cases) ===")
        if len(sub) == 0:
            continue
        print("  top fired-signal sets:")
        for sig, c in Counter(sub["signals"]).most_common(6):
            print(f"    {c:4d}  |  {sig or '(none)'}")
        print("  top reasons:")
        for rs, c in Counter(sub["reason"]).most_common(4):
            print(f"    {c:4d}  |  {rs}")
    return df


