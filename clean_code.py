from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import List

from radon.complexity import cc_visit
from radon.metrics import mi_visit
from radon.raw import analyze as radon_analyze


# ── thresholds ────────────────────────────────────────────────────────────────

MAX_FUNCTION_LINES   = 20   # lines per function before penalty
MAX_NESTING_DEPTH    = 3    # if-for-while nesting levels
MAX_PARAMS           = 4    # parameters per function
MAX_CC               = 5    # cyclomatic complexity per function
MIN_NAME_LENGTH      = 3    # minimum identifier length (excl. loop vars i/j/k/x)
MAGIC_NUMBER_IGNORE  = frozenset({0, 1, -1, 2, 100})  # universally understood
LOOP_VAR_WHITELIST   = frozenset({"i", "j", "k", "x", "y", "z", "n", "m", "_"})


# ── issue dataclass ───────────────────────────────────────────────────────────

@dataclass
class Issue:
    category: str        # e.g. "naming", "complexity", "style"
    rule: str            # short rule id, e.g. "short_name"
    message: str         # human-readable explanation
    line: int | None = None
    penalty: int = 0     # points deducted from 100


# ── individual checks ─────────────────────────────────────────────────────────

def _check_naming(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []
    is_snake  = re.compile(r'^[a-z_][a-z0-9_]*$')
    is_pascal = re.compile(r'^[A-Z][a-zA-Z0-9]*$')

    for node in ast.walk(tree):

        # ── functions ──────────────────────────────────────────────────────
        if isinstance(node, ast.FunctionDef):
            name = node.name
            line = node.lineno

            if len(name) < MIN_NAME_LENGTH:
                issues.append(Issue(
                    "naming", "short_name",
                    f"Function '{name}' is too short ({len(name)} chars). "
                    f"Use a descriptive name that explains what it does.",
                    line, penalty=15
                ))
            elif not is_snake.match(name):
                issues.append(Issue(
                    "naming", "not_snake_case",
                    f"Function '{name}' should be snake_case (e.g. 'validate_password').",
                    line, penalty=10
                ))

            # parameters
            for arg in node.args.args:
                aname = arg.arg
                if aname == "self":
                    continue
                if len(aname) < MIN_NAME_LENGTH and aname not in LOOP_VAR_WHITELIST:
                    issues.append(Issue(
                        "naming", "short_param",
                        f"Parameter '{aname}' in '{name}' is too short. "
                        f"Single-letter params make code unreadable without context.",
                        line, penalty=10
                    ))
                elif not is_snake.match(aname):
                    issues.append(Issue(
                        "naming", "param_not_snake",
                        f"Parameter '{aname}' in '{name}' should be snake_case.",
                        line, penalty=5
                    ))

        # ── classes ────────────────────────────────────────────────────────
        elif isinstance(node, ast.ClassDef):
            if not is_pascal.match(node.name):
                issues.append(Issue(
                    "naming", "not_pascal_case",
                    f"Class '{node.name}' should be PascalCase (e.g. 'OrderProcessor').",
                    node.lineno, penalty=10
                ))

        # ── variables ──────────────────────────────────────────────────────
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                vname = target.id
                if vname.isupper():          # CONSTANT — OK
                    continue
                if vname in LOOP_VAR_WHITELIST:
                    continue
                if len(vname) < MIN_NAME_LENGTH:
                    issues.append(Issue(
                        "naming", "short_variable",
                        f"Variable '{vname}' is too short. "
                        f"Choose a name that reveals intent (e.g. 'total' not 't').",
                        node.lineno, penalty=8
                    ))
                elif not is_snake.match(vname):
                    issues.append(Issue(
                        "naming", "variable_not_snake",
                        f"Variable '{vname}' should be snake_case.",
                        node.lineno, penalty=5
                    ))

    return issues


def _check_function_design(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        name  = node.name
        line  = node.lineno
        length = (node.end_lineno or line) - line + 1

        # ── too long ───────────────────────────────────────────────────────
        if length > MAX_FUNCTION_LINES:
            issues.append(Issue(
                "function_design", "function_too_long",
                f"Function '{name}' is {length} lines long (limit: {MAX_FUNCTION_LINES}). "
                f"Extract logical sub-steps into helper functions.",
                line, penalty=10
            ))

        # ── too many parameters ────────────────────────────────────────────
        params = [a for a in node.args.args if a.arg != "self"]
        if len(params) > MAX_PARAMS:
            issues.append(Issue(
                "function_design", "too_many_params",
                f"Function '{name}' has {len(params)} parameters (limit: {MAX_PARAMS}). "
                f"Consider grouping related params into a dataclass or dict.",
                line, penalty=10
            ))

        # ── missing docstring ──────────────────────────────────────────────
        has_doc = (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        )
        if not has_doc and not name.startswith("_"):
            issues.append(Issue(
                "function_design", "missing_docstring",
                f"Function '{name}' has no docstring. "
                f"Add a one-line summary of what it does and what it returns.",
                line, penalty=5
            ))

        # ── missing type hints ─────────────────────────────────────────────
        untyped = [a.arg for a in params if a.annotation is None]
        if untyped:
            issues.append(Issue(
                "function_design", "missing_type_hints",
                f"Function '{name}' is missing type hints for: {', '.join(untyped)}. "
                f"Type hints improve readability and catch bugs early.",
                line, penalty=5
            ))
        if node.returns is None and not name.startswith("_"):
            issues.append(Issue(
                "function_design", "missing_return_hint",
                f"Function '{name}' has no return type annotation.",
                line, penalty=3
            ))

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
                issues.append(Issue(
                    "complexity", "deep_nesting",
                    f"Function '{node.name}' has {depth} levels of nesting "
                    f"(limit: {MAX_NESTING_DEPTH}). "
                    f"Use early returns, guard clauses, or extract helper functions "
                    f"to flatten the structure.",
                    node.lineno, penalty=12
                ))

    return issues


def _check_cyclomatic_complexity(source: str) -> List[Issue]:
    issues: List[Issue] = []
    try:
        blocks = cc_visit(source)
    except Exception:
        return issues

    for block in blocks:
        if block.complexity > MAX_CC:
            issues.append(Issue(
                "complexity", "high_cyclomatic_complexity",
                f"Function '{block.name}' has cyclomatic complexity {block.complexity} "
                f"(limit: {MAX_CC}). High complexity means many decision paths — "
                f"split into smaller focused functions.",
                block.lineno, penalty=10
            ))

    return issues


def _check_style(tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []

    for node in ast.walk(tree):

        # ── range(len(x)) antipattern ──────────────────────────────────────
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "range":
                if (node.args
                        and isinstance(node.args[0], ast.Call)
                        and isinstance(node.args[0].func, ast.Name)
                        and node.args[0].func.id == "len"):
                    issues.append(Issue(
                        "style", "range_len_antipattern",
                        f"'range(len(...))' at line {getattr(node, 'lineno', '?')} — "
                        f"use 'enumerate()' when you need the index, "
                        f"or iterate directly over the collection.",
                        getattr(node, "lineno", None), penalty=5
                    ))

        # ── x = x + y instead of x += y ───────────────────────────────────
        if isinstance(node, ast.Assign):
            rhs = node.value
            if isinstance(rhs, ast.BinOp) and isinstance(rhs.op, (ast.Add, ast.Sub, ast.Mult)):
                for t in node.targets:
                    if (isinstance(t, ast.Name)
                            and isinstance(rhs.left, ast.Name)
                            and t.id == rhs.left.id):
                        op_sym = {ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*="}[type(rhs.op)]
                        issues.append(Issue(
                            "style", "use_augmented_assign",
                            f"'{t.id} = {t.id} ...' at line {node.lineno} — "
                            f"use '{op_sym}' for clarity.",
                            node.lineno, penalty=3
                        ))

        # ── magic numbers ──────────────────────────────────────────────────
        if isinstance(node, (ast.Compare, ast.BinOp, ast.Assign)):
            # Skip if this is a CONSTANT = value assignment (ALL_CAPS)
            if isinstance(node, ast.Assign):
                is_const_assign = any(
                    isinstance(t, ast.Name) and t.id.isupper()
                    for t in node.targets
                )
                if is_const_assign:
                    continue

            nums = []
            for child in ast.walk(node):
                if (isinstance(child, ast.Constant)
                        and isinstance(child.value, (int, float))
                        and child.value not in MAGIC_NUMBER_IGNORE):
                    nums.append(child.value)
            for num in set(nums):
                issues.append(Issue(
                    "style", "magic_number",
                    f"Magic number '{num}' at line {getattr(node, 'lineno', '?')} — "
                    f"assign it to a named constant (e.g. MIN_VALUE = {num}).",
                    getattr(node, "lineno", None), penalty=4
                ))

        # ── string concatenation with + in print/assign ────────────────────
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for arg in node.args:
                    if _has_string_concat(arg):
                        issues.append(Issue(
                            "style", "string_concat_in_print",
                            f"String concatenation with '+' in print() at line "
                            f"{getattr(node, 'lineno', '?')} — use an f-string instead.",
                            getattr(node, "lineno", None), penalty=3
                        ))

    return issues


def _has_string_concat(node: ast.AST) -> bool:
    """Return True if the node is a BinOp chain that mixes str() calls or Str constants."""
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


def _check_comments(source: str, tree: ast.AST) -> List[Issue]:
    issues: List[Issue] = []
    lines = source.splitlines()
    total_lines = len(lines)
    comment_lines = sum(1 for l in lines if l.strip().startswith("#"))

    if total_lines > 10 and comment_lines == 0:
        issues.append(Issue(
            "documentation", "no_comments",
            f"No inline comments found in {total_lines}-line file. "
            f"Add comments to explain non-obvious logic, not what the code does.",
            penalty=5
        ))

    return issues


def _run_pylint(source: str) -> list:
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".py", mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(source)
            tmp_path = tmp.name

        process = subprocess.run(
            [sys.executable, "-m", "pylint", tmp_path,
             "--output-format=json", "--disable=all", "--enable=C,R,W",
             "--disable=C0114,C0116,C0115"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        os.remove(tmp_path)

        if process.stdout:
            raw = json.loads(process.stdout)
            # Deduplicate and trim to most useful fields
            seen = set()
            cleaned = []
            for msg in raw:
                key = (msg.get("message-id"), msg.get("line"))
                if key not in seen:
                    seen.add(key)
                    cleaned.append({
                        "line": msg.get("line"),
                        "message_id": msg.get("message-id"),
                        "symbol": msg.get("symbol"),
                        "message": msg.get("message"),
                        "type": msg.get("type"),
                    })
            return cleaned
    except Exception:
        pass
    return []


# ── scoring ───────────────────────────────────────────────────────────────────

def _compute_score(issues: List[Issue], mi: float) -> tuple[int, str]:
    """Return (score 0-100, grade letter) factoring in issue penalties and MI."""
    penalty = sum(i.penalty for i in issues)

    # MI contributes up to 10 points bonus/malus
    # MI range: 0 (unmaintainable) – 100 (perfect). Normalize to 0-10.
    mi_bonus = round((min(max(mi, 0), 100) / 100) * 10)

    score = max(0, min(100, 100 - penalty + mi_bonus - 5))  # -5 baseline MI offset

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return score, grade


def _grade_summary(score: int, grade: str, issues: List[Issue]) -> str:
    category_counts: dict[str, int] = {}
    for issue in issues:
        category_counts[issue.category] = category_counts.get(issue.category, 0) + 1

    parts = []
    if not issues:
        parts.append("No issues detected.")
    else:
        for cat, count in category_counts.items():
            parts.append(f"{count} {cat.replace('_', ' ')} issue(s)")

    summary = f"Score {score}/100 (Grade {grade}). " + ", ".join(parts) + "."
    return summary


# ── public API ────────────────────────────────────────────────────────────────

def analyze_code_string(code_string: str) -> dict:
    empty_result = {
        "clean_code_score": 100,
        "grade": "A",
        "summary": "No code provided.",
        "issues": [],
        "radon": {
            "maintainability_index": 100.0,
            "raw_metrics": {"total_lines_of_code": 0, "logical_lines_of_code": 0, "comments": 0}
        },
        "pylint": []
    }

    if not code_string.strip():
        return empty_result

    # Parse once, reuse
    try:
        tree = ast.parse(code_string)
    except SyntaxError as e:
        return {
            **empty_result,
            "clean_code_score": 0,
            "grade": "F",
            "summary": f"Syntax error — code could not be parsed: {e}",
            "issues": [{"category": "syntax", "rule": "syntax_error",
                        "message": str(e), "line": e.lineno, "penalty": 100}]
        }

    # Collect all issues
    all_issues: List[Issue] = []
    all_issues += _check_naming(tree)
    all_issues += _check_function_design(tree)
    all_issues += _check_nesting(tree)
    all_issues += _check_cyclomatic_complexity(code_string)
    all_issues += _check_style(tree)
    all_issues += _check_comments(code_string, tree)

    # Radon
    mi = 100.0
    raw_metrics = {"total_lines_of_code": 0, "logical_lines_of_code": 0, "comments": 0}
    try:
        mi = mi_visit(code_string, multi=True)
        raw = radon_analyze(code_string)
        raw_metrics = {
            "total_lines_of_code": raw.loc,
            "logical_lines_of_code": raw.lloc,
            "comments": raw.comments,
        }
    except Exception:
        pass

    score, grade = _compute_score(all_issues, mi)
    summary = _grade_summary(score, grade, all_issues)

    return {
        "clean_code_score": score,
        "grade": grade,
        "summary": summary,
        "issues": [
            {
                "category": i.category,
                "rule": i.rule,
                "line": i.line,
                "message": i.message,
                "penalty": i.penalty,
            }
            for i in all_issues
        ],
        "radon": {
            "maintainability_index": round(mi, 2),
            "raw_metrics": raw_metrics,
        },
        "pylint": _run_pylint(code_string),
    }


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    snippet1 = '''
def pv(u, p, ul):
    for i in ul:
        if i[0] == u:
            if i[1] == p:
                if len(p) >= 8:
                    if any(c.isupper() for c in p):
                        if any(c.isdigit() for c in p):
                            return True
                        else:
                            return False
                    else:
                        return False
                else:
                    return False
            else:
                return False
    return False

ul = [("ahmed", "Password1"), ("sara", "weakpass")]
print(pv("ahmed", "Password1", ul))
print(pv("sara", "weakpass", ul))
'''

    snippet1_refactored = '''
from typing import List, Tuple

MIN_PASSWORD_LENGTH = 8

def validate_password(password: str) -> bool:
    """Check if password meets minimum security requirements."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return False
    if not any(c.isupper() for c in password):
        return False
    if not any(c.isdigit() for c in password):
        return False
    return True

def find_user(users: List[Tuple[str, str]], username: str, password: str) -> bool:
    """Check if username and password match a registered user."""
    for user, pwd in users:
        if user == username and pwd == password:
            return True
    return False

def authenticate_user(username: str, password: str, users: List[Tuple[str, str]]) -> bool:
    """Validate user credentials against registered users list."""
    if not find_user(users, username, password):
        return False
    return validate_password(password)

users = [("ahmed", "Password1"), ("sara", "weakpass")]
print(authenticate_user("ahmed", "Password1", users))
print(authenticate_user("sara", "weakpass", users))
'''

    for label, code in [("ORIGINAL", snippet1), ("REFACTORED", snippet1_refactored)]:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print('='*60)
        result = analyze_code_string(code)
        print(f"Score  : {result['clean_code_score']}/100  (Grade {result['grade']})")
        print(f"Summary: {result['summary']}")
        print(f"MI     : {result['radon']['maintainability_index']}")
        if result["issues"]:
            print(f"\nIssues ({len(result['issues'])}):")
            for iss in result["issues"]:
                line_str = f"line {iss['line']}" if iss["line"] else "global"
                print(f"  [{iss['category']}] -{iss['penalty']}pt | {line_str} | {iss['message']}")