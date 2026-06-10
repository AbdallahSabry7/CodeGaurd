"""Native clean-code metrics: summarize CodeGuard's clean-code tool outputs.
This is NOT classification F1. It's a direct report of what your tool measures:
- score/grade/pass rates
- severity counts (E/W/H)
- lloc (proxy for refactor cost)
"""
from __future__ import annotations
import os
import re
import statistics as stats
import sys
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct
# Import CodeGuard services directly so we can read the FULL clean-code dict.
_THIS = os.path.dirname(os.path.abspath(__file__))
_EVAL_DIR = os.path.dirname(_THIS)          # eval/tasks -> eval
_REPO_ROOT = os.path.dirname(_EVAL_DIR)     # eval -> repo root
_APP_DIR = os.getenv("CODEGUARD_APP_DIR", os.path.join(_REPO_ROOT, "app"))
if _APP_DIR not in sys.path:
	sys.path.insert(0, _APP_DIR)
try:
	import services
except Exception as exc:  # pragma: no cover
	services = None
	_IMPORT_ERROR = exc
else:
	_IMPORT_ERROR = None
def _parse_counts(s: str) -> tuple[int, int, int]:
	"""Parse '2E/3W/5H' -> (2, 3, 5)."""
	if not s:
		return 0, 0, 0
	m = re.match(r"\s*(\d+)E\s*/\s*(\d+)W\s*/\s*(\d+)H\s*", s)
	if not m:
		return 0, 0, 0
	return int(m.group(1)), int(m.group(2)), int(m.group(3))
def run() -> dict:
	data = load_jsonl("datasets/smells.jsonl")  # reuse the same corpus as smell eval
	n = len(data)
	if services is None:
		append_section(
			"## Clean-code tool metrics (CodeGuard)\n\n"
			"n/a — could not import CodeGuard services.\n\n"
			f"Import error: `{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}`"
		)
		return {"n": n, "codeguard": None}
	scores: list[float] = []
	passed = 0
	grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
	e_sum = w_sum = h_sum = 0
	llocs: list[int] = []
	for r in data:
		res = services.analyze_code_string(r["code"])
		if not isinstance(res, dict):
			continue
		if isinstance(res.get("score"), (int, float)):
			scores.append(float(res["score"]))
		if res.get("passed") is True:
			passed += 1
		g = str(res.get("grade") or "").strip().upper()
		if g in grade_counts:
			grade_counts[g] += 1
		e, w, h = _parse_counts(str(res.get("counts") or ""))
		e_sum += e
		w_sum += w
		h_sum += h
		if isinstance(res.get("lloc"), int):
			llocs.append(int(res["lloc"]))
	def _mean(xs): return (sum(xs) / len(xs)) if xs else 0.0
	def _median(xs): return stats.median(xs) if xs else 0.0
	rows = [
		["N", str(n)],
		["Avg score", f"{_mean(scores):.1f}"],
		["Median score", f"{_median(scores):.1f}"],
		["Pass rate", pct(passed / n if n else 0.0)],
		["Grades (A/B/C/D/F)", f'{grade_counts["A"]}/{grade_counts["B"]}/{grade_counts["C"]}/{grade_counts["D"]}/{grade_counts["F"]}'],
		["Avg E per snippet", f"{(e_sum / n if n else 0.0):.2f}"],
		["Avg W per snippet", f"{(w_sum / n if n else 0.0):.2f}"],
		["Avg H per snippet", f"{(h_sum / n if n else 0.0):.2f}"],
		["Avg lloc", f"{_mean(llocs):.1f}"],
		["Median lloc", f"{_median(llocs):.1f}"],
	]
	append_section(
		"## Clean-code tool metrics (CodeGuard)\n\n"
		+ md_table(["Metric", "Value"], rows)
	)
	return {
		"n": n,
		"avg_score": _mean(scores),
		"median_score": _median(scores),
		"pass_rate": (passed / n if n else 0.0),
		"grade_counts": grade_counts,
		"avg_E": (e_sum / n if n else 0.0),
		"avg_W": (w_sum / n if n else 0.0),
		"avg_H": (h_sum / n if n else 0.0),
		"avg_lloc": _mean(llocs),
		"median_lloc": _median(llocs),
	}
if __name__ == "__main__":
	import json
	print(json.dumps(run(), indent=2))