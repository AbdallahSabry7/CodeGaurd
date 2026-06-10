"""Native clean-code metrics: CodeGuard's clean-code tool vs the raw-LLM baseline.

This is NOT classification F1. It reports the kind of numbers your tool actually
produces (score / grade / pass-rate / severity counts / lloc), and asks the raw
LLM to produce the same kind of numbers, so you can compare them head-to-head.
"""
from __future__ import annotations

import os
import re
import statistics as stats
import sys

from adapters import baseline_llm
from harness.io_utils import load_jsonl
from harness.report import append_section, md_table, pct

# Import CodeGuard services directly so we read the FULL clean-code dict.
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

_GRADES = ["A", "B", "C", "D", "F"]


def _parse_counts(s) -> tuple[int, int, int]:
	"""Parse '2E/3W/5H' -> (2, 3, 5)."""
	if not s:
		return 0, 0, 0
	m = re.match(r"\s*(\d+)\s*E\s*/\s*(\d+)\s*W\s*/\s*(\d+)\s*H\s*", str(s))
	if not m:
		return 0, 0, 0
	return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _summarize(reports: list) -> dict:
	scores: list[float] = []
	llocs: list[int] = []
	passed = 0
	grade_counts = {g: 0 for g in _GRADES}
	e_sum = w_sum = h_sum = 0
	n_used = 0

	for res in reports:
		if not isinstance(res, dict):
			continue
		n_used += 1
		sc = res.get("score")
		if isinstance(sc, (int, float)):
			scores.append(float(sc))
		if res.get("passed") is True:
			passed += 1
		g = str(res.get("grade") or "").strip().upper()
		if g in grade_counts:
			grade_counts[g] += 1
		e, w, h = _parse_counts(res.get("counts"))
		e_sum += e
		w_sum += w
		h_sum += h
		if isinstance(res.get("lloc"), int):
			llocs.append(res["lloc"])

	def _mean(xs):
		return (sum(xs) / len(xs)) if xs else 0.0

	def _median(xs):
		return stats.median(xs) if xs else 0.0

	return {
		"n": n_used,
		"avg_score": _mean(scores),
		"median_score": _median(scores),
		"pass_rate": (passed / n_used if n_used else 0.0),
		"grade_counts": grade_counts,
		"avg_E": (e_sum / n_used if n_used else 0.0),
		"avg_W": (w_sum / n_used if n_used else 0.0),
		"avg_H": (h_sum / n_used if n_used else 0.0),
		"avg_lloc": _mean(llocs),
		"median_lloc": _median(llocs),
		"has_lloc": bool(llocs),
	}


def run() -> dict:
	data = load_jsonl("datasets/smells.jsonl")  # reuse the smell corpus
	n = len(data)

	if services is None:
		append_section(
			"## Clean-code tool metrics (CodeGuard vs Raw LLM)\n\n"
			"n/a — could not import CodeGuard services.\n\n"
			f"Import error: `{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}`"
		)
		return {"n": n, "codeguard": None}

	cg_reports = []
	llm_reports = []
	for r in data:
		code = r["code"]
		cg_reports.append(services.analyze_code_string(code))
		llm_reports.append(baseline_llm.predict_clean_metrics(code))

	cg = _summarize(cg_reports)
	llm = _summarize(llm_reports)

	def _grades_str(gc):
		return "/".join(str(gc[g]) for g in _GRADES)

	rows = [
		["Snippets (N)", str(cg["n"]), str(llm["n"])],
		["Avg score", f"{cg['avg_score']:.1f}", f"{llm['avg_score']:.1f}"],
		["Median score", f"{cg['median_score']:.1f}", f"{llm['median_score']:.1f}"],
		["Pass rate (>=75)", pct(cg["pass_rate"]), pct(llm["pass_rate"])],
		["Grades A/B/C/D/F", _grades_str(cg["grade_counts"]), _grades_str(llm["grade_counts"])],
		["Avg E per snippet", f"{cg['avg_E']:.2f}", f"{llm['avg_E']:.2f}"],
		["Avg W per snippet", f"{cg['avg_W']:.2f}", f"{llm['avg_W']:.2f}"],
		["Avg H per snippet", f"{cg['avg_H']:.2f}", f"{llm['avg_H']:.2f}"],
		["Avg lloc", f"{cg['avg_lloc']:.1f}", ("n/a" if not llm["has_lloc"] else f"{llm['avg_lloc']:.1f}")],
	]

	append_section(
		"## Clean-code tool metrics (CodeGuard vs Raw LLM)\n\n"
		f"Dataset size: {n}\n\n"
		+ md_table(["Metric", "CodeGuard", "Raw LLM"], rows)
	)
	return {"n": n, "codeguard": cg, "baseline": llm}


if __name__ == "__main__":
	import json
	print(json.dumps(run(), indent=2))