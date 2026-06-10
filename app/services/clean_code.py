"""
clean_code_analyzer.py
────────────────────────────────────────────────────────────────────────────────
Python code quality analyzer with two output modes:

  analyze(source)              → compact mode  (agent-facing, ~85% fewer tokens)
  analyze(source, verbose=True)→ full mode     (human/debug use)

────────────────────────────────────────────────────────────────────────────────
COMPACT output schema (default — pass to Refactor Agent):

  score    int        0-100
  grade    str        A/B/C/D/F
  passed   bool       True when score >= 75
  counts   str        "{E}E/{W}W/{H}H"  e.g. "2E/3W/5H"
  fixes    list[str]  one repair token per issue, sorted by severity
  lloc     int        logical lines of code (proxy for refactor cost)
  error    str|None   set only on SyntaxError

Fix token format:  {SEV}:{line}:{target}:{rule}[:{detail}]
  SEV    = E / W / H
  line   = line number or 0 if unknown
  target = function/class/variable name, or empty string
  rule   = rule id
  detail = optional short value (e.g. depth=5, lines=67, params=a,b)

Example fixes list:
  ["E:12:calc:deep_nesting:depth=5",
   "W:45:process_data:function_too_long:lines=67",
   "W:12:a:param_too_short",
   "H:12:calc:missing_docstring"]

────────────────────────────────────────────────────────────────────────────────
VERBOSE output schema (verbose=True — for humans and debugging):

  score, grade, passed         same as compact
  blocker_count                int
  warning_count                int
  hint_count                   int
  issues   list[dict]          full issue objects (id, cat, sev, line, target, msg, penalty)
  metrics  dict                loc, lloc, comments, maintainability_index, cc_max
  pylint   list[dict]          raw pylint output (line, symbol, msg, type)
  parse_error  str|None
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional


# ── thresholds ────────────────────────────────────────────────────────────────

MAX_FUNCTION_LINES  = 40
MAX_NESTING_DEPTH   = 4
MAX_PARAMS          = 5
MAX_CC              = 10
MIN_NAME_LENGTH     = 2
MAGIC_IGNORE        = frozenset({0, 1, -1, 2, 100})
LOOP_VAR_OK         = frozenset({"i", "j", "k", "x", "y", "z", "n", "m", "_"})

# Penalty → severity mapping
def _sev(penalty: int) -> str:
    if penalty >= 12:
        return "error"
    if penalty >= 6:
        return "warning"
    return "hint"


# ── issue dataclass ───────────────────────────────────────────────────────────

@dataclass
class Issue:
    cat:     str
    id:      str
    msg:     str
    penalty: int
    line:    Optional[int] = None
    target:  Optional[str] = None

    @property
    def sev(self) -> str:
        return _sev(self.penalty)

    def to_fix_token(self) -> str:
        """
        Compact repair token for the Refactor Agent.
        Format: {SEV}:{line}:{target}:{rule}[:{detail}]
        """
        sev_char = {"error": "E", "warning": "W", "hint": "H"}[self.sev]
        line     = self.line or 0
        target   = self.target or ""
        detail   = self._detail()
        if detail:
            return f"{sev_char}:{line}:{target}:{self.id}:{detail}"
        return f"{sev_char}:{line}:{target}:{self.id}"

    def _detail(self) -> str:
        """Extract the single most useful numeric/name value from the message."""
        import re
        # depth=N  (nesting)
        m = re.search(r"(\d+) nesting", self.msg)
        if m: return f"depth={m.group(1)}"
        # lines=N  (function length or file lines)
        m = re.search(r"(\d+) lines", self.msg)
        if m: return f"lines={m.group(1)}"
        # count=N  (params)
        m = re.search(r"(\d+) params", self.msg)
        if m: return f"count={m.group(1)}"
        # CC value
        m = re.search(r"CC=(\d+)", self.msg)
        if m: return f"cc={m.group(1)}"
        # missing type hints param list
        m = re.search(r"hints on: (.+)\.", self.msg)
        if m: return m.group(1).replace(", ", ",")
        # magic number value
        m = re.search(r"Magic number ([^\s;]+)", self.msg)
        if m: return f"val={m.group(1)}"
        # augmented assign operator
        m = re.search(r"use '(\S+)'", self.msg)
        if m: return f"use={m.group(1)}"
        return ""

    def to_dict(self) -> dict:
        """Full verbose dict for human/debug output."""
        return {
            "id":      self.id,
            "cat":     self.cat,
            "sev":     self.sev,
            "line":    self.line,
            "target":  self.target,
            "msg":     self.msg,
            "penalty": self.penalty,
        }


# ── helpers ───────────────────────────────────────────────────────────────────

_is_snake  = re.compile(r"^[a-z_][a-z0-9_]*$")
_is_pascal = re.compile(r"^[A-Z][a-zA-Z0-9]*$")


def _has_string_concat(node: ast.AST) -> bool:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
        return False

    def _has_str(n: ast.AST) -> bool:
        for child in ast.walk(n):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                return True
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "str"):
                return True
        return False

    return _has_str(node.left) or _has_str(node.right)


# ── checks ────────────────────────────────────────────────────────────────────

def _check_naming(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    for node in ast.walk(tree):

        if isinstance(node, ast.FunctionDef):
            name, line = node.name, node.lineno
            if len(name) < MIN_NAME_LENGTH:
                issues.append(Issue("naming", "name_too_short",
                    f"Function name '{name}' is too short; use a descriptive verb phrase.",
                    15, line, name))
            elif not _is_snake.match(name):
                issues.append(Issue("naming", "func_not_snake_case",
                    f"Function '{name}' must be snake_case.",
                    10, line, name))

            for arg in node.args.args:
                a = arg.arg
                if a == "self":
                    continue
                if len(a) < MIN_NAME_LENGTH and a not in LOOP_VAR_OK:
                    issues.append(Issue("naming", "param_too_short",
                        f"Param '{a}' in '{name}' is too short; single-letter params obscure intent.",
                        10, line, a))
                elif not _is_snake.match(a):
                    issues.append(Issue("naming", "param_not_snake_case",
                        f"Param '{a}' in '{name}' must be snake_case.",
                        5, line, a))

        elif isinstance(node, ast.ClassDef):
            if not _is_pascal.match(node.name):
                issues.append(Issue("naming", "class_not_pascal_case",
                    f"Class '{node.name}' must be PascalCase.",
                    10, node.lineno, node.name))

        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                v = t.id
                if v.isupper() or v in LOOP_VAR_OK:
                    continue
                if len(v) < MIN_NAME_LENGTH:
                    issues.append(Issue("naming", "var_too_short",
                        f"Variable '{v}' is too short; choose a name that reveals intent.",
                        8, node.lineno, v))
                elif not _is_snake.match(v):
                    issues.append(Issue("naming", "var_not_snake_case",
                        f"Variable '{v}' must be snake_case.",
                        5, node.lineno, v))

    return issues


def _check_functions(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        name  = node.name
        line  = node.lineno
        length = (node.end_lineno or line) - line + 1
        params = [a for a in node.args.args if a.arg != "self"]

        if length > MAX_FUNCTION_LINES:
            issues.append(Issue("function_design", "function_too_long",
                f"'{name}' is {length} lines (limit {MAX_FUNCTION_LINES}); extract helpers.",
                10, line, name))

        if len(params) > MAX_PARAMS:
            issues.append(Issue("function_design", "too_many_params",
                f"'{name}' has {len(params)} params (limit {MAX_PARAMS}); group into dataclass.",
                10, line, name))

        has_doc = (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        )
        if not has_doc and not name.startswith("_"):
            issues.append(Issue("docs", "missing_docstring",
                f"'{name}' has no docstring.",
                5, line, name))

        untyped = [a.arg for a in params if a.annotation is None]
        if untyped:
            issues.append(Issue("types", "missing_param_types",
                f"'{name}' missing type hints on: {', '.join(untyped)}.",
                5, line, name))

        if node.returns is None and not name.startswith("_"):
            issues.append(Issue("types", "missing_return_type",
                f"'{name}' has no return type annotation.",
                3, line, name))

    return issues


def _check_nesting(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    def _depth(node: ast.AST, current: int = 0) -> int:
        max_d = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                max_d = max(max_d, _depth(child, current + 1))
            else:
                max_d = max(max_d, _depth(child, current))
        return max_d

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            depth = _depth(node)
            if depth > MAX_NESTING_DEPTH:
                issues.append(Issue("complexity", "deep_nesting",
                    f"'{node.name}' has {depth} nesting levels (limit {MAX_NESTING_DEPTH}); use early returns.",
                    12, node.lineno, node.name))

    return issues


def _check_cc(source: str) -> List[Issue]:
    issues: List[Issue] = []
    try:
        from radon.complexity import cc_visit
        for block in cc_visit(source):
            if block.complexity > MAX_CC:
                issues.append(Issue("complexity", "high_cyclomatic_complexity",
                    f"'{block.name}' CC={block.complexity} (limit {MAX_CC}); split into smaller functions.",
                    10, block.lineno, block.name))
    except Exception:
        pass
    return issues


def _check_style(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    for node in ast.walk(tree):

        # range(len(...)) antipattern
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "range":
                if (node.args
                        and isinstance(node.args[0], ast.Call)
                        and isinstance(node.args[0].func, ast.Name)
                        and node.args[0].func.id == "len"):
                    issues.append(Issue("style", "range_len_antipattern",
                        "Use enumerate() or iterate directly instead of range(len(...)).",
                        5, getattr(node, "lineno", None)))

        # x = x + y  →  x += y
        if isinstance(node, ast.Assign):
            rhs = node.value
            if isinstance(rhs, ast.BinOp) and isinstance(rhs.op, (ast.Add, ast.Sub, ast.Mult)):
                for t in node.targets:
                    if (isinstance(t, ast.Name)
                            and isinstance(rhs.left, ast.Name)
                            and t.id == rhs.left.id):
                        op = {ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*="}[type(rhs.op)]
                        issues.append(Issue("style", "use_augmented_assign",
                            f"Replace '{t.id} = {t.id} ...' with '{op}'.",
                            3, node.lineno, t.id))

        # magic numbers
        if isinstance(node, (ast.Compare, ast.BinOp, ast.Assign)):
            if isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets):
                    continue
            seen_nums: set = set()
            for child in ast.walk(node):
                if (isinstance(child, ast.Constant)
                        and isinstance(child.value, (int, float))
                        and child.value not in MAGIC_IGNORE):
                    seen_nums.add(child.value)
            for num in seen_nums:
                issues.append(Issue("style", "magic_number",
                    f"Magic number {num}; assign to a named constant.",
                    4, getattr(node, "lineno", None)))

        # string concat in print()
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for arg in node.args:
                    if _has_string_concat(arg):
                        issues.append(Issue("style", "string_concat_in_print",
                            "Use an f-string instead of '+' concatenation in print().",
                            3, getattr(node, "lineno", None)))

    return issues


def _check_comments(source: str) -> List[Issue]:
    lines = source.splitlines()
    total = len(lines)
    comments = sum(1 for l in lines if l.strip().startswith("#"))
    if total > 10 and comments == 0:
        return [Issue("docs", "no_inline_comments",
            f"File has {total} lines but zero inline comments; document non-obvious logic.",
            5)]
    return []


def _run_pylint(source: str) -> tuple:
    """Run pylint once and return (messages, score_out_of_10).

    Uses a parseable message template so we can recover both the individual
    findings AND the global 0-10 rating from a single invocation.
    """
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".py", mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(source)
            path = tmp.name

        proc = subprocess.run(
            [sys.executable, "-m", "pylint", path,
             "--output-format=text", "--reports=n", "--score=y",
             "--disable=all", "--enable=C,R,W",
             "--disable=C0114,C0116,C0115",
             "--msg-template={line}:::{symbol}:::{category}:::{msg}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        os.remove(path)

        messages, seen = [], set()
        score = None
        for raw in (proc.stdout or "").splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            m = re.search(r"rated at (-?\d+(?:\.\d+)?)/10", stripped)
            if m:
                score = float(m.group(1))
                continue
            parts = raw.split(":::", 3)
            if len(parts) == 4:
                ln_raw, symbol, category, msg = parts
                try:
                    ln = int(ln_raw.strip())
                except ValueError:
                    ln = None
                key = (symbol.strip(), ln)
                if key not in seen:
                    seen.add(key)
                    messages.append({
                        "line":   ln,
                        "symbol": symbol.strip(),
                        "msg":    msg.strip(),
                        "type":   category.strip(),
                    })
        return messages, score
    except Exception:
        pass
    return [], None


# ── scoring ───────────────────────────────────────────────────────────────────

def _score(issues: List[Issue], mi: float) -> tuple[int, str]:
    """
    Category-capped scoring
    ───────────────────────
    Each issue category has a ceiling — the maximum points it can ever deduct,
    regardless of how many individual violations exist.  This prevents docs/type
    issues from drowning out real structural problems and makes the score stable
    as a codebase grows.

    Category ceilings (points deducted from 100):
      complexity  → up to 30   deep nesting, CC, long functions
      naming      → up to 15   snake_case, short names
      function    → up to 15   too many params, too long
      docs        → up to 10   missing docstrings (presence, not count)
      types       → up to 10   missing type hints  (presence, not count)
      style       → up to 10   magic numbers, augmented assign, range(len)
      syntax      → 100        parse error = instant F

    Grade thresholds:
      A  90-100   clean, production-ready
      B  75-89    minor issues, mostly docs/style
      C  55-74    real structural issues present
      D  35-54    significant problems
      F   0-34    broken or heavily flawed

    A single error-severity issue (nesting/CC) caps the grade at B.
    Two or more error issues cap at C.
    """
    CATEGORY_CAPS = {
        "syntax":          100,
        "complexity":       30,
        "function_design":  15,
        "naming":           15,
        "style":            10,
        "docs":             10,
        "types":            10,
    }

    # Sum raw penalties per category, then clamp each to its ceiling
    cat_raw: dict[str, int] = {}
    for iss in issues:
        cat_raw[iss.cat] = cat_raw.get(iss.cat, 0) + iss.penalty

    total_deduction = sum(
        min(raw, CATEGORY_CAPS.get(cat, 10))
        for cat, raw in cat_raw.items()
    )

    mi_bonus = round((min(max(mi, 0), 100) / 100) * 5)   # 0-5 pts
    score    = max(0, min(100, 100 - total_deduction + mi_bonus))

    error_count = sum(1 for i in issues if i.sev == "error")

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 55:
        grade = "C"
    elif score >= 35:
        grade = "D"
    else:
        grade = "F"

    # Structural errors cap the grade regardless of numeric score
    if error_count >= 2 and grade in ("A", "B"):
        grade = "C"
    elif error_count == 1 and grade == "A":
        grade = "B"

    return score, grade


# ── public API ────────────────────────────────────────────────────────────────

def analyze(source: str, verbose: bool = False) -> dict:
    """
    Analyze Python source and return a quality report.

    Parameters
    ----------
    source  : str   Raw Python source code.
    verbose : bool  False (default) → compact agent output (~85% fewer tokens).
                    True            → full output for humans and debugging.
    """
    _empty_metrics = {
        "loc": 0, "lloc": 0, "comments": 0,
        "maintainability_index": 100.0, "cc_max": 0,
    }

    if not source.strip():
        if verbose:
            return {
                "score": 100, "grade": "A", "passed": True,
                "blocker_count": 0, "warning_count": 0, "hint_count": 0,
                "issues": [], "metrics": _empty_metrics,
                "pylint": [], "parse_error": None,
            }
        return {"score": 100, "grade": "A", "passed": True,
                "counts": "0E/0W/0H", "fixes": [], "lloc": 0, "error": None}

    # Parse
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        err = f"SyntaxError:{e.lineno}:{e.msg}"
        if verbose:
            return {
                "score": 0, "grade": "F", "passed": False,
                "blocker_count": 1, "warning_count": 0, "hint_count": 0,
                "issues": [{"id": "syntax_error", "cat": "syntax", "sev": "error",
                            "line": e.lineno, "target": None,
                            "msg": f"SyntaxError: {e.msg}", "penalty": 100}],
                "metrics": _empty_metrics, "pylint": [], "parse_error": str(e),
            }
        return {"score": 0, "grade": "F", "passed": False,
                "counts": "1E/0W/0H", "fixes": [err], "lloc": 0, "error": str(e)}

    # Collect issues, then deduplicate by (id, line, target)
    all_issues: List[Issue] = []
    all_issues += _check_naming(tree)
    all_issues += _check_functions(tree)
    all_issues += _check_nesting(tree)
    all_issues += _check_cc(source)
    all_issues += _check_style(tree)
    all_issues += _check_comments(source)

    seen_keys: set = set()
    deduped: List[Issue] = []
    for iss in all_issues:
        key = (iss.id, iss.line, iss.target)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(iss)
    all_issues = deduped

    # Radon metrics
    mi = 100.0
    cc_max = 0
    raw_loc = raw_lloc = raw_comments = 0
    try:
        from radon.metrics import mi_visit
        from radon.raw import analyze as radon_raw
        from radon.complexity import cc_visit
        mi       = mi_visit(source, multi=True)
        raw      = radon_raw(source)
        raw_loc, raw_lloc, raw_comments = raw.loc, raw.lloc, raw.comments
        cc_max   = max((b.complexity for b in cc_visit(source)), default=0)
    except Exception:
        pass

    score, grade = _score(all_issues, mi)

    # Sort: errors first, then warnings, then hints; ties broken by penalty desc
    _sev_order = {"error": 0, "warning": 1, "hint": 2}
    sorted_issues = sorted(
        all_issues,
        key=lambda i: (_sev_order[i.sev], -i.penalty)
    )

    e_count = sum(1 for i in sorted_issues if i.sev == "error")
    w_count = sum(1 for i in sorted_issues if i.sev == "warning")
    h_count = sum(1 for i in sorted_issues if i.sev == "hint")

    if verbose:
        pylint_msgs, pylint_score = _run_pylint(source)
        return {
            "score":         score,
            "grade":         grade,
            "passed":        score >= 75,
            "blocker_count": e_count,
            "warning_count": w_count,
            "hint_count":    h_count,
            "issues":        [i.to_dict() for i in sorted_issues],
            "metrics": {
                "loc":                   raw_loc,
                "lloc":                  raw_lloc,
                "comments":              raw_comments,
                "maintainability_index": round(mi, 1),
                "cc_max":                cc_max,
                "pylint_score":          pylint_score,
            },
            "pylint":      pylint_msgs,
            "parse_error": None,
        }

    # ── compact mode ──────────────────────────────────────────────────────────
    return {
        "score":  score,
        "grade":  grade,
        "passed": score >= 75,
        "counts": f"{e_count}E/{w_count}W/{h_count}H",
        "fixes":  [i.to_fix_token() for i in sorted_issues],
        "lloc":   raw_lloc,
        "error":  None,
    }


# ── backward-compat alias ─────────────────────────────────────────────────────

def analyze_code_string(code_string: str, verbose: bool = False) -> dict:
    return analyze(code_string, verbose=verbose)