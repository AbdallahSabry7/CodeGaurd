import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_AI_ROOT = _HERE.parent.parent

sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_AI_ROOT))

from complexity1 import analyze

_MODEL_PATH = _HERE / "hybrid.joblib"

_LABEL_TO_BIG_O = {
    "constant":  "O(1)",
    "logn":      "O(log n)",
    "linear":    "O(n)",
    "nlogn":     "O(n log n)",
    "quadratic": "O(n²)",
    "cubic":     "O(n³)",
    "np":        "O(2ⁿ)",
    "unknown":   "Unknown",
}


def estimate_complexity(code_str: str):
    try:
        from hybrid_time_complexty import load_and_predict

        result = analyze(code_str)
        label = load_and_predict(str(_MODEL_PATH), code_str)[0]
        time_complexity = _LABEL_TO_BIG_O.get(label, label)
        return time_complexity, result.space_complexity
    except Exception as exc:
        return "Error", f"{type(exc).__name__}: {exc}"

if __name__ == "__main__":
    code = """from math import *
a, vm = map(int, input().split())
l, d, vd = map(int, input().split())
if vm <= vd or sqrt(2 * a * d) <= vd:
    if vm ** 2 / (2 * a) >= l:
        ans = sqrt(2 * l / a)
    else:
        ans = vm / a + (l - vm ** 2 / (2 * a)) / vm
else:
    s1 = (vm ** 2 - vd ** 2) / (2 * a)
    if s1 >= (l - d):
        ans = (sqrt(4 * (vd ** 2) + 8 * a * (l - d)) - 2 * vd) / (2 * a)
    else:
        ans = (vm - vd) / a + (l - d - s1) / vm
    v1 = sqrt((2 * a * d + vd ** 2) / 2)
    if v1 <= vm:
        ans = ans + v1 / a + (v1 - vd) / a
    else:
        s1 = d - (vm ** 2 - vd ** 2) / (2 * a) - (vm ** 2) / (2 * a)
        ans = ans + vm / a + (vm - vd) / a + s1 / vm
print('%.12f' % ans)
"""
    time_complexity, space_complexity = estimate_complexity(code)
    print(f"Time Complexity: {time_complexity}")
    print(f"Space Complexity: {space_complexity}")