"""Hybrid time-complexity classifier.

Idea: the hand-written analyzer is a strong *feature extractor*, not a final
classifier. We feed its signal vector (loop depth, sort/halving/recursion/
two-pointer flags, ...) + its own Big-O guess + cheap token counts into a
gradient-boosted tree that LEARNS the residual structure the rules can't
resolve (partition-of-input, amortized, bit-length loops, ...).

Layout (same as eval_codecomplex.py):
    repo/
      complexity.py                 <- the analyzer module
      <subdir>/eval_codecomplex.py
      <subdir>/hybrid_model.py      <- this file

Quickstart:
    import pandas as pd
    from hybrid_model import build_features, cross_validate, train_and_save, load_and_predict

    df = ...                       # columns: 'code' and 'true_time'
    X, y = build_features(df)
    cross_validate(X, y)           # stratified 5-fold: accuracy + HC-Score
    train_and_save(X, y, 'hybrid.joblib')
    preds = load_and_predict('hybrid.joblib', df_new)   # df_new needs only 'code'

Deps: scikit-learn, pandas, numpy, joblib (all ship with sklearn).
"""
import re
import sys
from pathlib import Path
from dataclasses import fields

import numpy as np
import pandas as pd
from sklearn.ensemble import  HistGradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import joblib

# analyzer module (complexity.py) lives one directory above this script
sys.path.append(str(Path(__file__).resolve().parent.parent))
from complexity import analyze
# reuse the exact mapping + HC-Score already used by your eval harness
from services.tests.codeComplexty_test import (
    to_benchmark_class, COMPLEXITY_ORDER, _RANK, hc_score, CODE_COL, TRUE_COL,
)

# --------------------------------------------------------------------------
# Feature extraction
# --------------------------------------------------------------------------
_TOKEN_PATTERNS = {
    "tok_for":          r"\bfor\b",
    "tok_while":        r"\bwhile\b",
    "tok_def":          r"\bdef\b",
    "tok_return":       r"\breturn\b",
    "tok_sort":         r"\.sort\(|\bsorted\(",
    "tok_range":        r"\brange\(",
    "tok_len":          r"\blen\(",
    "tok_input":        r"\binput\(",
    "tok_floordiv":     r"//",
    "tok_rshift":       r">>",
    "tok_pow":          r"\*\*",
    "tok_bin":          r"\bbin\(",
    "tok_perm_prod":    r"permutations|product|combinations",
    "tok_comprehension":r"\[[^\]]*\bfor\b[^\]]*\]",
    "tok_memo":         r"\b(memo|cache|dp)\b",
    "tok_in_op":        r"\bin\b",
    "tok_heapq":        r"\bheapq\b|heappush|heappop",
    "tok_bisect":       r"\bbisect\b",
    "tok_recursionish": r"\bdef\s+(\w+)",   # placeholder; refined below
}


def _token_features(code: str) -> dict:
    feats = {}
    for name, pat in _TOKEN_PATTERNS.items():
        feats[name] = len(re.findall(pat, code))
    lines = code.splitlines() or [""]
    feats["loc"] = len(lines)
    feats["len_chars"] = len(code)
    feats["max_indent"] = max((len(l) - len(l.lstrip()) for l in lines), default=0)
    # crude self-recursion hint: a def name that is also called elsewhere
    names = re.findall(r"\bdef\s+(\w+)", code)
    feats["tok_self_recursion"] = int(any(
        len(re.findall(r"\b" + re.escape(n) + r"\s*\(", code)) > 1 for n in names
    ))
    return feats


def _signal_features(code: str) -> dict:
    feats: dict = {}
    pred = "unknown"
    try:
        r = analyze(code)
        s = r.signals
        for f in fields(s):
            if f.name == "function_name":
                continue
            v = getattr(s, f.name)
            if isinstance(v, bool):
                feats["sig_" + f.name] = int(v)
            elif isinstance(v, (int, float)):
                feats["sig_" + f.name] = float(v)
        pred = to_benchmark_class(r.time_complexity)
    except Exception:
        pass
    # the analyzer's OWN guess is the single strongest feature: pass it as both
    # an ordinal rank and a one-hot so the tree can trust or override it.
    feats["analyzer_rank"] = _RANK.get(pred, -1)
    for c in COMPLEXITY_ORDER:
        feats["analyzer_is_" + c] = int(pred == c)
    return feats


def build_features(df: pd.DataFrame, code_col: str = None, label_col: str = None):
    """Return (X DataFrame, y array-or-None). y is None when no label column."""
    code_col = code_col or CODE_COL
    rows = [{**_signal_features(c), **_token_features(c)}
            for c in df[code_col].astype(str)]
    X = pd.DataFrame(rows).fillna(0.0)
    y = None
    lc = label_col or TRUE_COL
    if lc in df.columns:
        y = df[lc].astype(str).values
    return X, y


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def make_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=500,
        learning_rate=0.07,
        max_leaf_nodes=63,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=0,
    )



def train_and_save(X, y, path: str = "hybrid.joblib"):
    clf = make_model()
    clf.fit(X, y)
    joblib.dump({"model": clf, "columns": list(X.columns)}, path)
    print("saved ->", path)
    return clf


def load_and_predict(path: str, df: pd.DataFrame, code_col: str = None):
    bundle = joblib.load(path)
    clf, cols = bundle["model"], bundle["columns"]
    X, _ = build_features(df, code_col=code_col, label_col="__none__")
    X = X.reindex(columns=cols, fill_value=0.0)   # align to training columns
    return clf.predict(X)


def feature_importance(clf, X, y, n_repeats: int = 5, top: int = 25):
    """Permutation importance (compute on a held-out split for honest numbers)."""
    from sklearn.inspection import permutation_importance
    r = permutation_importance(clf, X, y, n_repeats=n_repeats,
                                random_state=0, n_jobs=-1)
    order = np.argsort(r.importances_mean)[::-1]
    print("top features by permutation importance:")
    for i in order[:top]:
        print(f"  {r.importances_mean[i]:+.4f}  {X.columns[i]}")
    return [(X.columns[i], r.importances_mean[i]) for i in order]


if __name__ == "__main__":
    print("Import this module:")
    print("  X, y = build_features(df)")
    print("  cross_validate(X, y)")
    print("  train_and_save(X, y, 'hybrid.joblib')")
