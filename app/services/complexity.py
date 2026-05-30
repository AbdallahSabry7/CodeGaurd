from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DetectionSignals:
    function_name: Optional[str] = None

    # Loop structure
    max_loop_depth: int = 0
    effective_loop_depth: int = 0
    loop_count: int = 0
    total_loops_in_file: int = 0

    # Recursion
    recursive_calls: int = 0
    recursive_branches: int = 0

    # Patterns
    halving_detected: bool = False
    sort_detected: bool = False
    sort_in_loop: bool = False
    memoization_detected: bool = False
    growing_structures: bool = False
    divide_and_conquer: bool = False
    implicit_linear_in_loop: bool = False
    inner_recursive_memo: bool = False 


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


# ---------------------------------------------------------------------------
# Known O(n) builtin / method names
# ---------------------------------------------------------------------------

_LINEAR_BUILTINS: frozenset = frozenset({
    # len() is O(1) in Python; sorted() handled via sort_detected.
    # Constructors (list/set/dict/tuple) excluded to avoid false positives
    # inside `for i in range(len(arr))` patterns.
    "min", "max", "sum", "any", "all", "reversed",
})

_LINEAR_METHODS: frozenset = frozenset({
    "count", "index", "remove", "reverse", "copy",
    "find", "rfind", "replace", "split", "rsplit", "join",
    "startswith", "endswith",
    "update", "intersection", "union", "difference",
    "intersection_update", "difference_update",
    "heapify",
})

_SORT_METHODS: frozenset = frozenset({"sort", "sorted"})
_SORT_MODULES: frozenset = frozenset({"heapq", "bisect"})


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------

class _SignalDetector(ast.NodeVisitor):

    def __init__(self) -> None:
        self._s = DetectionSignals()
        self._loop_depth: int = 0
        self._func_stack: list = []
        self._in_main_block: bool = False

    @property
    def signals(self) -> DetectionSignals:
        return self._s

    # ------------------------------------------------------------------ funcs
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _visit_func(self, node: ast.FunctionDef) -> None:
        if self._s.function_name is None:
            self._s.function_name = node.name
        for default in node.args.defaults:
            if isinstance(default, (ast.Dict, ast.List, ast.Set)):
                self._s.memoization_detected = True
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    # ------------------------------------------------------------------ loops
    def _enter_loop(self, node: ast.AST) -> None:
        if self._in_main_block:
            self.generic_visit(node)
            return
        self._s.loop_count += 1
        self._s.total_loops_in_file += 1
        self._loop_depth += 1
        self._s.max_loop_depth = max(self._s.max_loop_depth, self._loop_depth)
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._enter_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._enter_loop(node)

    # ------------------------------------------------------------------ comprehensions (FIX 1)
    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._s.growing_structures = True   # builds a new list
        self._handle_implicit_loop(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._s.growing_structures = True
        self._handle_implicit_loop(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._s.growing_structures = True
        self._handle_implicit_loop(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._handle_implicit_loop(node)

    def _handle_implicit_loop(self, node: ast.AST) -> None:
        self._s.total_loops_in_file += 1
        self._loop_depth += 1
        self._s.max_loop_depth = max(self._s.max_loop_depth, self._loop_depth)
        self.generic_visit(node)
        self._loop_depth -= 1

    # ------------------------------------------------------------------ calls (FIX 1, 2, 3)
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # recursion detection: only fire when inside the owning function (FIX 3)
        outer = self._s.function_name
        if (outer
                and isinstance(func, ast.Name)
                and func.id == outer
                and self._func_stack
                and self._func_stack[-1] == outer
                and not self._in_main_block):
            self._s.recursive_calls += 1

        # sort detection (FIX 2)
        is_sort = False
        if isinstance(func, ast.Name) and func.id == "sorted":
            is_sort = True
            self._s.sort_detected = True
            self._s.growing_structures = True  # sorted() always allocates O(n)
        if isinstance(func, ast.Attribute) and func.attr in _SORT_METHODS:
            is_sort = True
            self._s.sort_detected = True
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in _SORT_MODULES):
            is_sort = True
            self._s.sort_detected = True
        if is_sort and self._loop_depth > 0:
            self._s.sort_in_loop = True

        # implicit-linear inside loop (FIX 1)
        if self._loop_depth > 0:
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _LINEAR_BUILTINS or name in _LINEAR_METHODS:
                self._s.implicit_linear_in_loop = True

        self.generic_visit(node)

    # ------------------------------------------------------------------ `in` on lists (FIX 1)
    def visit_Compare(self, node: ast.Compare) -> None:
        if self._loop_depth > 0:
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    if isinstance(comp, (ast.Name, ast.List, ast.Tuple)):
                        self._s.implicit_linear_in_loop = True
        self.generic_visit(node)

    # ------------------------------------------------------------------ assignments / memo
    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                self._s.growing_structures = True
                if target.value.id in {"memo", "cache", "dp"}:
                    self._s.memoization_detected = True
            # local `memo = {}` or `cache = {}` / `dp = {}` declaration (exact names only)
            if isinstance(target, ast.Name) and target.id in {"memo", "cache", "dp"}:
                if isinstance(node.value, (ast.Dict, ast.Call)):
                    self._s.memoization_detected = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        # detect `if __name__ == "__main__"` (FIX 3)
        is_main = (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        )
        if is_main:
            prev = self._in_main_block
            self._in_main_block = True
            self.generic_visit(node)
            self._in_main_block = prev
            return

        if isinstance(test, ast.Compare):
            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, ast.Name):
                    # "seen"/"visited" indicate graph traversal, not subproblem memoization
                    if comp.id in {"memo", "cache", "dp"}:
                        self._s.memoization_detected = True
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr in {"append", "extend", "add", "push", "insert"}:
                    self._s.growing_structures = True
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_HALVING_PATTERNS = [
    re.compile(r"\b(lo|hi|low|high|left|right|mid|start|end)\s*=.*//\s*2"),
    re.compile(r"\bmid\s*=.*//\s*2"),
    re.compile(r"len\s*\(.*\)\s*//\s*2"),
]

_BRANCH_CALL_RE = re.compile(r"\b{name}\s*\(")


def _count_calls_in_node(node: ast.AST, name: str) -> int:
    """Count direct (non-conditional) recursive calls in a node's subtree."""
    return sum(
        1 for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == name
    )


def _count_unconditional_recursive_calls(func_node: ast.FunctionDef, name: str) -> int:
    """
    Count recursive calls that ALWAYS execute (not inside an if/elif/else branch).

    merge_sort:  left = merge_sort(...)   # unconditional assign → counts
                 right = merge_sort(...)  # unconditional assign → counts  → total 2
    bin_search:  if cond: return f(...)   # inside If body → conditional, skip
                 else:    return f(...)   # inside If orelse → conditional, skip → total 0
                 → falls back to per-expression max = 1
    fibonacci:   return f(n-1) + f(n-2)  # single Return with 2 calls → 2
    """
    unconditional = 0
    for stmt in func_node.body:
        # Skip pure If/While/For blocks — calls inside are conditional
        if isinstance(stmt, (ast.If, ast.While, ast.For)):
            continue
        unconditional += _count_calls_in_node(stmt, name)

    # Also check max calls in any single expression (covers fibonacci return case)
    per_expr_max = 0
    for node in ast.walk(func_node):
        if isinstance(node, (ast.Return, ast.Assign, ast.Expr)):
            c = _count_calls_in_node(node, name)
            if c > per_expr_max:
                per_expr_max = c

    return max(unconditional, per_expr_max)


def _detect_source_patterns(source: str, s: DetectionSignals) -> None:
    # ── halving patterns (regex) ─────────────────────────────────────────────
    for line in source.splitlines():
        if line.strip().startswith("#"):
            continue
        for pat in _HALVING_PATTERNS:
            if pat.search(line):
                s.halving_detected = True
                break

    # ── branch counting via structural AST analysis ───────────────────────────
    # Distinguishes merge_sort (2 unconditional calls) from bin_search
    # (2 mutually-exclusive conditional calls).
    if s.function_name and s.recursive_calls > 0:
        try:
            tree = ast.parse(textwrap.dedent(source))
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == s.function_name:
                    branches = _count_unconditional_recursive_calls(node, s.function_name)
                    s.recursive_branches = max(s.recursive_branches, branches)
                    break

    # ── divide-and-conquer: halving + truly concurrent multi-branch ──────────
    # Single-branch + halving = binary search = O(log n), not O(n log n).
    if s.recursive_calls > 0 and s.halving_detected and s.recursive_branches >= 2:
        s.divide_and_conquer = True

    # ── effective depth: implicit linear-in-loop bumps by 1 (FIX 1) ─────────
    s.effective_loop_depth = s.max_loop_depth
    if s.implicit_linear_in_loop and s.max_loop_depth >= 1:
        s.effective_loop_depth = s.max_loop_depth + 1


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _infer_complexity(s: DetectionSignals) -> tuple:
    # FIX 4: fall back to total_loops_in_file when outer fn has no direct loops
    effective_depth = s.effective_loop_depth
    if effective_depth == 0 and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        effective_depth = min(s.total_loops_in_file, 2)  # conservative cap

    # ── time ────────────────────────────────────────────────────────────────
    if s.recursive_calls > 0:
        # Single-branch recursion that halves input = O(log n)
        if s.recursive_calls > 0 and s.halving_detected and s.recursive_branches < 2:
            time = "O(log n)"
            time_why = "Single-branch recursion that halves the input each call — O(log n)."
            space = "O(log n)"
            space_why = "Recursion stack depth is O(log n) due to input halving."
            return time, space, time_why, space_why
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
                time_why = "Input is halved each recursive call with no extra linear work."
        elif s.memoization_detected:
            time = "O(n)"
            time_why = "Recursive with memoization — each subproblem computed once."
        elif s.recursive_branches >= 2:
            base = s.recursive_branches
            time = f"O({base}ⁿ)"
            time_why = f"{base} recursive branches per call → exponential call tree."
        else:
            if s.max_loop_depth >= 1:
                if s.max_loop_depth == 1:
                    time = "O(n²)"
                    time_why = "Linear recursion with a loop inside each call → O(n²)."
                else:
                    time = f"O(n^{s.max_loop_depth + 1})"
                    time_why = (
                        f"Linear recursion with {s.max_loop_depth}-deep loops inside each call."
                    )
            else:
                time = "O(n)"
                time_why = "Single recursive call per invocation — linear recursion depth."

    elif s.memoization_detected and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        # Nested helper with memoization (outer fn has no direct recursion)
        time = "O(n)"
        time_why = "Memoized computation — each unique subproblem solved once."
    elif s.sort_in_loop:
        time = "O(n² log n)"
        time_why = "Sort operation (O(n log n)) called inside a loop."

    elif s.halving_detected and s.max_loop_depth >= 1:
        if s.max_loop_depth == 1:
            time = "O(log n)"
            time_why = "Loop halves the search space on every iteration."
        else:
            time = f"O(n^{s.max_loop_depth - 1} log n)"
            time_why = f"Halving loop nested {s.max_loop_depth - 1} level(s) deep."

    elif s.sort_detected:
        time = "O(n log n)"
        time_why = "Sort operation dominates — O(n log n)."

    elif effective_depth == 0:
        time = "O(1)"
        time_why = "No loops, recursion, or implicit linear work — constant time."
    elif effective_depth == 1:
        time = "O(n)"
        time_why = "Single loop (or equivalent linear scan) over the input."
    elif effective_depth == 2:
        if s.implicit_linear_in_loop and s.max_loop_depth == 1:
            time = "O(n²)"
            time_why = (
                "Implicit O(n) operation (membership test, builtin scan, or "
                "comprehension) inside a loop → O(n²)."
            )
        else:
            time = "O(n²)"
            time_why = "Two nested loops — quadratic time."
    else:
        time = f"O(n^{effective_depth})"
        time_why = f"{effective_depth} effective loop levels — polynomial time."

    # ── space ───────────────────────────────────────────────────────────────
    if s.divide_and_conquer:
        space = "O(n)"
        space_why = "Recursion call stack plus temporary arrays created during splits."
    elif s.recursive_calls > 0 and s.memoization_detected:
        space = "O(n)"
        space_why = "Memo table and recursion call stack each grow to O(n)."
    elif s.recursive_calls > 0:
        space = "O(n)"
        space_why = "Recursion call stack depth is proportional to input size."
    elif s.growing_structures:
        space = "O(n)"
        space_why = "Data structures (list/dict/set) grow proportionally with input."
    else:
        space = "O(1)"
        space_why = "Only fixed-size variables used — constant extra space."

    return time, space, time_why, space_why


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _find_inner_recursive_helpers(tree: ast.AST, signals: DetectionSignals) -> None:
    """Detect nested helper functions that recurse into themselves with memoization.
    E.g. outer() defines inner helper() which calls helper() recursively with a memo dict.
    In this pattern outer has no direct recursion, but the work is still O(n).
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        inner_name = node.name
        if inner_name == signals.function_name:
            continue  # already handled as the outer function
        # Count self-calls inside this inner function
        self_calls = sum(
            1 for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == inner_name
        )
        if self_calls == 0:
            continue
        # Check for memoization inside this inner function
        has_memo = any(
            isinstance(n, ast.Compare)
            and any(
                isinstance(op, ast.In)
                and isinstance(comp, ast.Name)
                and comp.id in {"memo", "cache", "dp", "seen"}
                for op, comp in zip(n.ops, n.comparators)
            )
            for n in ast.walk(node)
        )
        branches = self_calls  # conservative: treat each call as a potential branch
        if has_memo:
            signals.memoization_detected = True
            signals.inner_recursive_memo = True
            signals.recursive_calls = max(signals.recursive_calls, 1)
        elif self_calls >= 2:
            signals.recursive_calls = max(signals.recursive_calls, self_calls)
            signals.recursive_branches = max(signals.recursive_branches, self_calls)
        else:
            signals.recursive_calls = max(signals.recursive_calls, 1)


def analyze(source: str) -> ComplexityResult:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    detector = _SignalDetector()
    detector.visit(tree)
    signals = detector.signals
    _find_inner_recursive_helpers(tree, signals)
    _detect_source_patterns(source, signals)
    time, space, time_why, space_why = _infer_complexity(signals)
    return ComplexityResult(
        time_complexity=time,
        space_complexity=space,
        time_reason=time_why,
        space_reason=space_why,
        signals=signals,
    )


def estimate_complexity(code_str: str) -> tuple:
    try:
        result = analyze(code_str)
        return result.time_complexity, result.space_complexity
    except Exception as exc:
        return "Error", str(exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_block() -> str:
    print("Enter your code (blank line to finish):\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _cli() -> None:
    print("Python Complexity Estimator  (v2)")
    print("=" * 40)
    while True:
        print()
        code = _read_block()
        if not code.strip():
            print("No code entered.")
        else:
            try:
                result = analyze(code)
                print()
                print(result)
            except SyntaxError as exc:
                print(f"Syntax error: {exc}")
        again = input("\nAnalyze another snippet? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye!")
            break


# ---------------------------------------------------------------------------
# Smoke tests  — python complexity_analyzer.py --test
# ---------------------------------------------------------------------------

def _run_tests() -> None:
    import sys

    cases = [
        ("Constant", "def f(x): return x + 1", "O(1)", "O(1)"),
        ("Linear loop", """
def sum_array(arr):
    total = 0
    for num in arr:
        total += num
    return total
""", "O(n)", "O(1)"),
        ("Quadratic nested loops", """
def count_pairs(arr):
    count = 0
    for i in range(len(arr)):
        for j in range(i + 1, len(arr)):
            count += 1
    return count
""", "O(n²)", "O(1)"),
        ("Quadratic — `in` list inside loop ", """
def has_duplicate(arr):
    seen = []
    for x in arr:
        if x in seen:
            return True
        seen.append(x)
    return False
""", "O(n²)", "O(n)"),
        ("Quadratic — min() inside loop ", """
def selection_sort(arr):
    for i in range(len(arr)):
        min_idx = arr.index(min(arr[i:]))
        arr[i], arr[min_idx] = arr[min_idx], arr[i]
    return arr
""", "O(n²)", "O(1)"),
        ("O(n log n) — standalone sort ", """
def sort_and_return(arr):
    return sorted(arr)
""", "O(n log n)", "O(n)"),
        ("O(n log n) — merge sort", """
def merge_sort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])
    return merge(left, right)
""", "O(n log n)", "O(n)"),
        ("O(log n) — binary search", """
def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""", "O(log n)", "O(1)"),
        ("O(2ⁿ) — naive fibonacci", """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
""", "O(2ⁿ)", "O(n)"),
        ("O(n) — memoized fibonacci ", """
def fib_memo(n, memo={}):
    if n in memo:
        return memo[n]
    if n <= 1:
        return n
    memo[n] = fib_memo(n - 1, memo) + fib_memo(n - 2, memo)
    return memo[n]
""", "O(n)", "O(n)"),
        ("O(n) — helper loop counted ", """
def helper(arr):
    total = 0
    for x in arr:
        total += x
    return total

def main(arr):
    return helper(arr)
""", "O(n)", "O(1)"),
        ("No false recursion from driver ", """
def process(arr):
    return [x * 2 for x in arr]

if __name__ == "__main__":
    process([1, 2, 3])
""", "O(n)", "O(n)"),

        ("Cubic — triple nested loops", """
def count_triplets(arr):
    count = 0
    for i in arr:
        for j in arr:
            for k in arr:
                count += 1
    return count
""", "O(n^3)", "O(1)"),

        ("Linear recursion — single branch", """
def countdown(n):
    if n <= 0:
        return
    countdown(n - 1)
""", "O(n)", "O(n)"),

        (" O(n log n) — sort then single loop", """
def sort_then_scan(arr):
    arr = sorted(arr)
    result = 0
    for x in arr:
        result += x
    return result
""", "O(n log n)", "O(n)"),

        ("Quadratic — sort inside loop", """
def bogosort_step(arr):
    for _ in range(len(arr)):
        arr = sorted(arr)
    return arr
""", "O(n² log n)", "O(n)"),

        ("O(n²) — sum() inside loop", """
def prefix_sums(arr):
    result = []
    for i in range(len(arr)):
        result.append(sum(arr[:i+1]))
    return result
""", "O(n²)", "O(n)"),

        (" O(log n) — recursive binary search", """
def bin_search(arr, target, lo, hi):
    if lo > hi:
        return -1
    mid = (lo + hi) // 2
    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        return bin_search(arr, target, mid + 1, hi)
    else:
        return bin_search(arr, target, lo, mid - 1)
""", "O(log n)", "O(log n)"),

        (" DP with explicit memo dict", """
def dp_fib(n):
    memo = {}
    def helper(k):
        if k in memo:
            return memo[k]
        if k <= 1:
            return k
        memo[k] = helper(k - 1) + helper(k - 2)
        return memo[k]
    return helper(n)
""", "O(n)", "O(n)"),

        (" Growing list — O(n) space", """
def build_list(n):
    result = []
    for i in range(n):
        result.append(i * 2)
    return result
""", "O(n)", "O(n)"),
    ]

    passed = 0
    failures = []
    for name, code, expected_time, expected_space in cases:
        result = analyze(code)
        ok_t = result.time_complexity == expected_time
        ok_s = result.space_complexity == expected_space
        ok   = ok_t and ok_s
        if ok:
            passed += 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if not ok:
            if not ok_t:
                print(f"       time  : got {result.time_complexity!r:16}  expected {expected_time!r}")
                print(f"               reason: {result.time_reason}")
            if not ok_s:
                print(f"       space : got {result.space_complexity!r:16}  expected {expected_space!r}")
                print(f"               reason: {result.space_reason}")
            failures.append(name)

    print(f"\n{'='*50}")
    print(f"  {passed}/{len(cases)} tests passed", end="")
    if failures:
        print(f"  ({len(failures)} failed)")
        print("  Failed cases:")
        for f in failures:
            print(f"    • {f}")
    else:
        print("  — all green ✓")
    print(f"{'='*50}")
    import sys
    sys.exit(0 if passed == len(cases) else 1)


import sys as _sys
if __name__ == "__main__":
    _run_tests()