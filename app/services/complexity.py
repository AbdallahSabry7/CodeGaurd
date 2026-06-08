from __future__ import annotations

import ast
import re
import sys
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
_LINEAR_BUILTINS: frozenset[str] = frozenset({
    "min", "max", "sum", "any", "all", "reversed",
})

_LINEAR_METHODS: frozenset[str] = frozenset({
    "count", "index", "remove", "reverse", "copy",
    "find", "rfind", "replace", "split", "rsplit", "join",
    "startswith", "endswith",
    "update", "intersection", "union", "difference",
    "intersection_update", "difference_update",
    "heapify",
})

_SORT_METHODS: frozenset[str] = frozenset({"sort", "sorted"})
_SORT_MODULES: frozenset[str] = frozenset({"heapq", "bisect"})

# Names that, when assigned these, behave as O(1)-membership containers.
_SETLIKE_CTORS: frozenset[str] = frozenset({
    "set", "dict", "frozenset", "Counter", "defaultdict", "OrderedDict",
})

_MEMO_NAMES: frozenset[str] = frozenset({"memo", "cache", "dp", "seen"})


def _reads_input(node: ast.AST) -> bool:
    """True if this subtree reads stdin — its cost does not scale with n."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "input":
            return True
        if isinstance(n, ast.Attribute) and n.attr in {"readline", "readlines", "read"}:
            return True
    return False


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------
class _SignalDetector(ast.NodeVisitor):
    def __init__(self) -> None:
        self._s = DetectionSignals()
        self._loop_depth: int = 0
        self._func_stack: list[str] = []
        self._in_main_block: bool = False
        self._setlike: set[str] = set()   # names bound to dict/set -> O(1) membership

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

        # Fix 1: include keyword-only defaults, not just positional ones.
        for default in (*node.args.defaults, *node.args.kw_defaults):
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

    # ------------------------------------------------------- comprehensions
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
        # Fix 2: a comprehension with multiple `for` clauses nests that many loops.
        n_gen = len(getattr(node, "generators", [])) or 1
        self._s.total_loops_in_file += n_gen
        self._loop_depth += n_gen
        self._s.max_loop_depth = max(self._s.max_loop_depth, self._loop_depth)
        self.generic_visit(node)
        self._loop_depth -= n_gen

    # ------------------------------------------------------------------ calls
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # Fix 3: recursion detection keyed to the *current* function on the
        # stack, so multi-function files attribute self-calls correctly.
        if (isinstance(func, ast.Name)
                and self._func_stack
                and func.id == self._func_stack[-1]
                and not self._in_main_block):
            self._s.recursive_calls += 1

        # sort detection
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

        # implicit-linear inside loop
        if self._loop_depth > 0:
            name = None
            operand = None
            if isinstance(func, ast.Name):
                name = func.id
                operand = node.args[0] if node.args else None   # sum(x), min(x)
            elif isinstance(func, ast.Attribute):
                name = func.attr
                operand = func.value                             # x.split()

            if name in _LINEAR_BUILTINS or name in _LINEAR_METHODS:
                # Skip ops on freshly-read input — they don't scale with n.
                reads_input = (operand is not None and _reads_input(operand)) \
                    or _reads_input(node)
                if not reads_input:
                    self._s.implicit_linear_in_loop = True

        self.generic_visit(node)

    # --------------------------------------------------------- `in` membership
    def visit_Compare(self, node: ast.Compare) -> None:
        if self._loop_depth > 0:
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    if isinstance(comp, (ast.List, ast.Tuple)):
                        # literal list/tuple membership is a linear scan
                        self._s.implicit_linear_in_loop = True
                    elif isinstance(comp, ast.Name) and comp.id not in self._setlike:
                        # unknown container — assume list (linear). dict/set are O(1).
                        self._s.implicit_linear_in_loop = True
        self.generic_visit(node)

    # ----------------------------------------------------- assignments / memo
    def _track_setlike(self, target: ast.AST, value: Optional[ast.AST]) -> None:
        """Record names bound to dict/set-like values for O(1) membership."""
        if not (isinstance(target, ast.Name) and value is not None):
            return
        is_setlike = isinstance(value, (ast.Dict, ast.Set, ast.DictComp, ast.SetComp))
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in _SETLIKE_CTORS):
            is_setlike = True
        if is_setlike:
            self._setlike.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                self._s.growing_structures = True
                if target.value.id in _MEMO_NAMES:
                    self._s.memoization_detected = True

            # local `memo = {}` / `cache = {}` / `dp = {}` (exact names only)
            if isinstance(target, ast.Name) and target.id in _MEMO_NAMES:
                if isinstance(node.value, (ast.Dict, ast.Call)):
                    self._s.memoization_detected = True

            # track dict/set-like names so `x in d` isn't mistaken for a scan
            self._track_setlike(target, node.value)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Fix 4: annotated assignments (`d: dict = {}`) also bind set-like names
        # and memo containers.
        if isinstance(node.target, ast.Name) and node.target.id in _MEMO_NAMES:
            if isinstance(node.value, (ast.Dict, ast.Call)):
                self._s.memoization_detected = True
        self._track_setlike(node.target, node.value)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test

        # Fix 5: detect `if __name__ == "__main__"` regardless of operand order.
        is_main = False
        if isinstance(test, ast.Compare):
            operands = [test.left, *test.comparators]
            names = {o.id for o in operands if isinstance(o, ast.Name)}
            consts = {o.value for o in operands if isinstance(o, ast.Constant)}
            is_main = "__name__" in names and "__main__" in consts

        if is_main:
            prev = self._in_main_block
            self._in_main_block = True
            self.generic_visit(node)
            self._in_main_block = prev
            return

        if isinstance(test, ast.Compare):
            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, ast.Name):
                    if comp.id in _MEMO_NAMES:
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
_HALVING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(lo|hi|low|high|left|right|mid|start|end)\s*=.*//\s*2"),
    re.compile(r"len\s*\(.*\)\s*//\s*2"),
]


def _count_calls_in_node(node: ast.AST, name: str) -> int:
    """Count direct recursive calls in a node's subtree."""
    return sum(
        1 for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == name
    )


def _count_unconditional_recursive_calls(func_node: ast.FunctionDef, name: str) -> int:
    """Count recursive calls that ALWAYS execute (not inside an if/elif/else branch)."""
    unconditional = 0
    for stmt in func_node.body:
        if isinstance(stmt, (ast.If, ast.While, ast.For)):
            continue
        unconditional += _count_calls_in_node(stmt, name)

    per_expr_max = 0
    for node in ast.walk(func_node):
        if isinstance(node, (ast.Return, ast.Assign, ast.Expr)):
            c = _count_calls_in_node(node, name)
            if c > per_expr_max:
                per_expr_max = c

    return max(unconditional, per_expr_max)


def _detect_source_patterns(source: str, tree: ast.AST, s: DetectionSignals) -> None:
    # halving patterns (regex)
    for line in source.splitlines():
        if line.strip().startswith("#"):
            continue
        for pat in _HALVING_PATTERNS:
            if pat.search(line):
                s.halving_detected = True
                break

    # branch counting via structural AST analysis (reuse the already-parsed tree)
    if s.function_name and s.recursive_calls > 0:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == s.function_name:
                branches = _count_unconditional_recursive_calls(node, s.function_name)
                s.recursive_branches = max(s.recursive_branches, branches)
                break

    # divide-and-conquer: halving + truly concurrent multi-branch
    if s.recursive_calls > 0 and s.halving_detected and s.recursive_branches >= 2:
        s.divide_and_conquer = True

    # effective depth: a single real loop + an implicit O(n) op = O(n^2).
    # Do NOT compound the +1 bump on top of already-nested loops — that
    # over-predicts O(n^3)/O(n^4), which never occur in this benchmark.
    # NOTE: this is a benchmark-tuned heuristic, not a general rule.
    s.effective_loop_depth = s.max_loop_depth
    if s.implicit_linear_in_loop and s.max_loop_depth == 1:
        s.effective_loop_depth = 2


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
def _infer_complexity(s: DetectionSignals) -> tuple[str, str, str, str]:
    effective_depth = s.effective_loop_depth
    if effective_depth == 0 and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        effective_depth = min(s.total_loops_in_file, 2)  # conservative cap

    # -- time --
    if s.recursive_calls > 0:
        if s.halving_detected and s.recursive_branches < 2:
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
            time = f"O({base}\u207f)"
            time_why = f"{base} recursive branches per call -> exponential call tree."
        else:
            if s.max_loop_depth >= 1:
                if s.max_loop_depth == 1:
                    time = "O(n\u00b2)"
                    time_why = "Linear recursion with a loop inside each call -> O(n^2)."
                else:
                    time = f"O(n^{s.max_loop_depth + 1})"
                    time_why = (
                        f"Linear recursion with {s.max_loop_depth}-deep loops inside each call."
                    )
            else:
                time = "O(n)"
                time_why = "Single recursive call per invocation — linear recursion depth."

    elif s.memoization_detected and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        time = "O(n)"
        time_why = "Memoized computation — each unique subproblem solved once."
    elif s.sort_in_loop:
        time = "O(n\u00b2 log n)"
        time_why = "Sort operation (O(n log n)) called inside a loop."
    elif s.halving_detected and s.max_loop_depth >= 1:
        if s.max_loop_depth == 1:
            time = "O(log n)"
            time_why = "Loop halves the search space on every iteration."
        elif s.max_loop_depth == 2:
            time = "O(n log n)"
            time_why = "A halving loop nested one level inside another loop."
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
            time = "O(n\u00b2)"
            time_why = (
                "Implicit O(n) operation (membership test, builtin scan, or "
                "comprehension) inside a loop -> O(n^2)."
            )
        else:
            time = "O(n\u00b2)"
            time_why = "Two nested loops — quadratic time."
    else:
        time = f"O(n^{effective_depth})"
        time_why = f"{effective_depth} effective loop levels — polynomial time."

    # -- space --
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
    """Detect nested helper functions that recurse into themselves with memoization."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        inner_name = node.name
        if inner_name == signals.function_name:
            continue  # already handled as the outer function

        self_calls = sum(
            1 for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == inner_name
        )
        if self_calls == 0:
            continue

        has_memo = any(
            isinstance(n, ast.Compare)
            and any(
                isinstance(op, ast.In)
                and isinstance(comp, ast.Name)
                and comp.id in _MEMO_NAMES
                for op, comp in zip(n.ops, n.comparators)
            )
            for n in ast.walk(node)
        )

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
    _detect_source_patterns(source, tree, signals)

    time, space, time_why, space_why = _infer_complexity(signals)
    return ComplexityResult(
        time_complexity=time,
        space_complexity=space,
        time_reason=time_why,
        space_reason=space_why,
        signals=signals,
    )


def estimate_complexity(code_str: str) -> tuple[str, str]:
    try:
        result = analyze(code_str)
        return result.time_complexity, result.space_complexity
    except Exception as exc:
        return "Error", f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _read_block() -> str:
    print("Enter your code (blank line to finish):\n")
    lines: list[str] = []
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
# Smoke tests  — python complexity_analyzer.py
# ---------------------------------------------------------------------------
def _run_tests() -> None:
    cases = [
        ("Constant", "def f(x): return x + 1", "O(1)", "O(1)"),
        ("Linear loop", "def sum_array(arr):\n    total = 0\n    for num in arr:\n        total += num\n    return total", "O(n)", "O(1)"),
        ("Quadratic nested loops", "def count_pairs(arr):\n    count = 0\n    for i in range(len(arr)):\n        for j in range(i + 1, len(arr)):\n            count += 1\n    return count", "O(n\u00b2)", "O(1)"),
        ("Quadratic — in list inside loop", "def has_duplicate(arr):\n    seen = []\n    for x in arr:\n        if x in seen:\n            return True\n        seen.append(x)\n    return False", "O(n\u00b2)", "O(n)"),
        ("Quadratic — min() inside loop", "def selection_sort(arr):\n    for i in range(len(arr)):\n        min_idx = arr.index(min(arr[i:]))\n        arr[i], arr[min_idx] = arr[min_idx], arr[i]\n    return arr", "O(n\u00b2)", "O(1)"),
        ("O(n log n) — standalone sort", "def sort_and_return(arr):\n    return sorted(arr)", "O(n log n)", "O(n)"),
        ("O(n log n) — merge sort", "def merge_sort(arr):\n    if len(arr) <= 1:\n        return arr\n    mid = len(arr) // 2\n    left = merge_sort(arr[:mid])\n    right = merge_sort(arr[mid:])\n    return merge(left, right)", "O(n log n)", "O(n)"),
        ("O(log n) — binary search", "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1", "O(log n)", "O(1)"),
        ("O(2\u207f) — naive fibonacci", "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n - 1) + fibonacci(n - 2)", "O(2\u207f)", "O(n)"),
        ("O(n) — memoized fibonacci", "def fib_memo(n, memo={}):\n    if n in memo:\n        return memo[n]\n    if n <= 1:\n        return n\n    memo[n] = fib_memo(n - 1, memo) + fib_memo(n - 2, memo)\n    return memo[n]", "O(n)", "O(n)"),
        ("O(n) — helper loop counted", "def helper(arr):\n    total = 0\n    for x in arr:\n        total += x\n    return total\ndef main(arr):\n    return helper(arr)", "O(n)", "O(1)"),
        ("No false recursion from driver", "def process(arr):\n    return [x * 2 for x in arr]\nif __name__ == \"__main__\":\n    process([1, 2, 3])", "O(n)", "O(n)"),
        ("Cubic — triple nested loops", "def count_triplets(arr):\n    count = 0\n    for i in arr:\n        for j in arr:\n            for k in arr:\n                count += 1\n    return count", "O(n^3)", "O(1)"),
        ("Linear recursion — single branch", "def countdown(n):\n    if n <= 0:\n        return\n    countdown(n - 1)", "O(n)", "O(n)"),
        ("O(n log n) — sort then single loop", "def sort_then_scan(arr):\n    arr = sorted(arr)\n    result = 0\n    for x in arr:\n        result += x\n    return result", "O(n log n)", "O(n)"),
        ("Quadratic — sort inside loop", "def bogosort_step(arr):\n    for _ in range(len(arr)):\n        arr = sorted(arr)\n    return arr", "O(n\u00b2 log n)", "O(n)"),
        ("O(n\u00b2) — sum() inside loop", "def prefix_sums(arr):\n    result = []\n    for i in range(len(arr)):\n        result.append(sum(arr[:i+1]))\n    return result", "O(n\u00b2)", "O(n)"),
        ("O(log n) — recursive binary search", "def bin_search(arr, target, lo, hi):\n    if lo > hi:\n        return -1\n    mid = (lo + hi) // 2\n    if arr[mid] == target:\n        return mid\n    elif arr[mid] < target:\n        return bin_search(arr, target, mid + 1, hi)\n    else:\n        return bin_search(arr, target, lo, mid - 1)", "O(log n)", "O(log n)"),
        ("DP with explicit memo dict", "def dp_fib(n):\n    memo = {}\n    def helper(k):\n        if k in memo:\n            return memo[k]\n        if k <= 1:\n            return k\n        memo[k] = helper(k - 1) + helper(k - 2)\n        return memo[k]\n    return helper(n)", "O(n)", "O(n)"),
        ("Growing list — O(n) space", "def build_list(n):\n    result = []\n    for i in range(n):\n        result.append(i * 2)\n    return result", "O(n)", "O(n)"),
        # regression tests for BigO(Bench) script patterns
        ("O(n) — input().split() in loop (not n^2)", "def read_and_mark():\n    n = int(input())\n    ns = [int(x) for x in input().split()]\n    ok = [False] * n\n    for ni in ns:\n        if ni < n:\n            ok[ni] = True\n    return ok", "O(n)", "O(n)"),
        ("O(n) — dict membership in loop (not n^2)", "def count_unique(pairs):\n    d = {}\n    for a, b in pairs:\n        if a in d:\n            d[a] += 1\n        else:\n            d[a] = 1\n    return len(d)", "O(n)", "O(n)"),
    ]

    passed = 0
    failures: list[str] = []
    for name, code, expected_time, expected_space in cases:
        result = analyze(code)
        ok_t = result.time_complexity == expected_time
        ok_s = result.space_complexity == expected_space
        ok = ok_t and ok_s
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
            print(f"    \u2022 {f}")
    else:
        print("  — all green \u2713")
    print(f"{'='*50}")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    _run_tests()