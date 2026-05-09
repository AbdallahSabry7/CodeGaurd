from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DetectionSignals:
    """Raw signals extracted from the AST / source text."""
    function_name: Optional[str] = None
    max_loop_depth: int = 0
    loop_count: int = 0
    recursive_calls: int = 0
    recursive_branches: int = 0        
    halving_detected: bool = False
    memoization_detected: bool = False
    growing_structures: bool = False
    divide_and_conquer: bool = False


@dataclass
class ComplexityResult:
    time_complexity: str
    space_complexity: str
    time_reason: str
    space_reason: str
    signals: DetectionSignals = field(repr=False)

    def __str__(self) -> str:
        return (
            f"Time  : {self.time_complexity}  — {self.time_reason}\n"
            f"Space : {self.space_complexity}  — {self.space_reason}"
        )


class _SignalDetector(ast.NodeVisitor):
    """Walk the AST and populate a DetectionSignals instance."""

    def __init__(self) -> None:
        self._signals = DetectionSignals()
        self._current_loop_depth = 0

    @property
    def signals(self) -> DetectionSignals:
        return self._signals


    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Record the outermost function name only
        if self._signals.function_name is None:
            self._signals.function_name = node.name

        # Memoization: mutable default argument (e.g. memo={})
        for default in node.args.defaults:
            if isinstance(default, (ast.Dict, ast.List, ast.Set)):
                self._signals.memoization_detected = True

        self.generic_visit(node)

    def _enter_loop(self, node: ast.AST) -> None:
        self._signals.loop_count += 1
        self._current_loop_depth += 1
        self._signals.max_loop_depth = max(
            self._signals.max_loop_depth, self._current_loop_depth
        )
        self.generic_visit(node)
        self._current_loop_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._enter_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._enter_loop(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self._signals.function_name
        if name and isinstance(node.func, ast.Name) and node.func.id == name:
            self._signals.recursive_calls += 1
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            # dict/list subscript assignment: memo[n] = …
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                self._signals.growing_structures = True
                # memo/cache/dp subscript write → memoization
                if target.value.id in {"memo", "cache", "dp"}:
                    self._signals.memoization_detected = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        # `if x in memo / cache / dp / seen / visited`
        test = node.test
        if isinstance(test, ast.Compare):
            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, ast.Name):
                    if comp.id in {"memo", "cache", "dp", "seen", "visited"}:
                        self._signals.memoization_detected = True
        self.generic_visit(node)

    # Growing structures via method calls
    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr in {"append", "extend", "add", "push", "insert"}:
                    self._signals.growing_structures = True
        self.generic_visit(node)


_HALVING_PATTERNS = [
    re.compile(r"(lo|hi|low|high|left|right|mid|start|end)\s*=.*//\s*2"),
    re.compile(r"mid\s*=.*//\s*2"),
    re.compile(r"len\s*\(.*\)\s*//\s*2"),
]

_BRANCH_CALL_PATTERN = re.compile(r"\b{name}\s*\(")


def _detect_source_patterns(
    source: str, signals: DetectionSignals
) -> None:
    """Augment *signals* with patterns that are easier to spot via regex."""
    lines = source.splitlines()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Halving (binary search / divide-and-conquer)
        for pat in _HALVING_PATTERNS:
            if pat.search(line):
                signals.halving_detected = True
                break

        # Count recursive calls per line and track total
        if signals.function_name:
            pat = _BRANCH_CALL_PATTERN.pattern.format(name=re.escape(signals.function_name))
            count = len(re.findall(pat, line))
            if count > signals.recursive_branches:
                signals.recursive_branches = count

    # If >=2 total recursive calls (possibly on separate lines, e.g. merge_sort)
    # treat it as multi-branch even if no single line had 2 calls.
    if signals.recursive_calls >= 2 and signals.recursive_branches < 2:
        signals.recursive_branches = 2

    # Divide-and-conquer: recursive AND halving
    if signals.recursive_calls > 0 and signals.halving_detected:
        signals.divide_and_conquer = True



def _infer_complexity(s: DetectionSignals) -> tuple[str, str, str, str]:
    """Return (time, space, time_reason, space_reason)."""

    # Time complexity 
    if s.recursive_calls > 0:
        if s.divide_and_conquer:
            has_linear_combine = s.recursive_branches >= 2 or s.max_loop_depth >= 1
            if has_linear_combine:
                time = "O(n log n)"
                time_why = (
                    "Divide-and-conquer recursion (input halved each call) "
                    "with a linear merge/combine step."
                )
            else:
                time = "O(log n)"
                time_why = (
                    "Input is halved each recursive call with no extra linear work."
                )
        elif s.memoization_detected:
            time = "O(n)"
            time_why = (
                "Recursive with memoization — each unique subproblem is "
                "computed exactly once."
            )
        elif s.recursive_branches >= 2:
            base = s.recursive_branches
            time = f"O({base}ⁿ)"
            time_why = (
                f"{base} recursive branches per call causes the call tree to "
                f"grow exponentially."
            )
        else:
            time = "O(n)"
            time_why = (
                "Single recursive call per invocation — recursion depth is "
                "linear in the input."
            )
    elif s.halving_detected and s.max_loop_depth >= 1:
        if s.max_loop_depth == 1:
            time = "O(log n)"
            time_why = "Loop halves the search space on every iteration."
        else:
            time = f"O(n^{s.max_loop_depth - 1} log n)"
            time_why = (
                f"Halving loop nested {s.max_loop_depth - 1} level(s) deep "
                "inside other loops."
            )
    elif s.max_loop_depth == 0:
        time = "O(1)"
        time_why = "No loops or recursion — constant time."
    elif s.max_loop_depth == 1:
        time = "O(n)"
        time_why = "Single loop over the input — linear time."
    elif s.max_loop_depth == 2:
        time = "O(n²)"
        time_why = "Two nested loops — quadratic time."
    else:
        time = f"O(n^{s.max_loop_depth})"
        time_why = f"{s.max_loop_depth} nested loops — polynomial time."

    # Space complexity 
    if s.divide_and_conquer:
        space = "O(n)"
        space_why = (
            "Recursion call stack plus temporary arrays created during splits."
        )
    elif s.recursive_calls > 0 and s.memoization_detected:
        space = "O(n)"
        space_why = "Memo table and recursion call stack each grow to O(n)."
    elif s.recursive_calls > 0:
        space = "O(n)"
        space_why = "Recursion call stack depth is proportional to input size."
    elif s.growing_structures:
        space = "O(n)"
        space_why = (
            "Data structures (list/dict/set) grow proportionally with the input."
        )
    else:
        space = "O(1)"
        space_why = "Only fixed-size variables are used — constant extra space."

    return time, space, time_why, space_why


def analyze(source: str) -> ComplexityResult:
    source = textwrap.dedent(source)
    tree = ast.parse(source)

    detector = _SignalDetector()
    detector.visit(tree)
    signals = detector.signals

    _detect_source_patterns(source, signals)

    time, space, time_why, space_why = _infer_complexity(signals)
    return ComplexityResult(
        time_complexity=time,
        space_complexity=space,
        time_reason=time_why,
        space_reason=space_why,
        signals=signals,
    )


# Keep the old function name as a convenience alias
def estimate_complexity(code_str: str) -> tuple[str, str]:
    """
    Backward-compatible wrapper.  Returns (time_complexity, space_complexity).
    """
    try:
        result = analyze(code_str)
        return result.time_complexity, result.space_complexity
    except Exception as exc:
        return "Error", str(exc)
