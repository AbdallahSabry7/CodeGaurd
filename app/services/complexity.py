from __future__ import annotations
import ast
import re
import sys
import textwrap
from dataclasses import dataclass, field, fields
from typing import Optional

# ===========================================================================
# Data structures
# ===========================================================================
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
    recursion_in_loop: bool = False        # FIX 1: recursive call located inside a loop
    # Patterns
    halving_detected: bool = False
    sort_detected: bool = False
    sort_in_loop: bool = False
    memoization_detected: bool = False
    growing_structures: bool = False
    divide_and_conquer: bool = False
    implicit_linear_in_loop: bool = False
    inner_recursive_memo: bool = False
    exponential_loop: bool = False         # FIX B: iterates an exponential/permutation space
    two_pointer: bool = False              # FIX H: inner loop advances an outer loop's pointer

    def active(self) -> dict:
        """Non-default (i.e. fired) signals, for per-prediction logging."""
        base = DetectionSignals()
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) != getattr(base, f.name) and f.name != "function_name"
        }


@dataclass
class ComplexityResult:
    time_complexity: str
    space_complexity: str
    time_reason: str
    space_reason: str
    signals: DetectionSignals = field(repr=False)

    def __str__(self) -> str:
        return (
            f"Time  : {self.time_complexity}  \u2014 {self.time_reason}\n"
            f"Space : {self.space_complexity}  \u2014 {self.space_reason}"
        )

    @property
    def trace(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.signals.active().items())


# ===========================================================================
# Known O(n) builtin / method names
# ===========================================================================
_LINEAR_BUILTINS: frozenset = frozenset({
    "min", "max", "sum", "any", "all", "reversed",
})
# FIX A: only methods whose cost scales with the loop's n stay here. String-parsing
# methods (split/join/find/replace/startswith/endswith) were firing the implicit-linear
# bump on bounded strings inside loops, which turned `quadratic` into a magnet class.
_LINEAR_METHODS: frozenset = frozenset({
    "count", "index", "remove", "reverse", "copy",
    "update", "intersection", "union", "difference",
    "intersection_update", "difference_update",
    "heapify",
})
_STRING_PARSE_METHODS: frozenset = frozenset({
    "find", "rfind", "replace", "split", "rsplit", "join", "startswith", "endswith",
})
_SORT_METHODS: frozenset = frozenset({"sort", "sorted"})
_SORT_MODULES: frozenset = frozenset({"heapq", "bisect"})
_SETLIKE_CTORS: frozenset = frozenset({
    "set", "dict", "frozenset", "Counter", "defaultdict", "OrderedDict",
})
_LISTLIKE_CTORS: frozenset = frozenset({"list", "tuple", "deque"})

# FIX B: iterables whose length is exponential/factorial in n.
_EXP_ITER: frozenset = frozenset({"permutations", "product"})

# FIX D (opt-in): discount "for _ in range(T): ... input() ..." test-case loops,
# whose count is the number of test cases, not the algorithm's input size n.
# Toggle this to A/B its effect on the dataset.
DISCOUNT_TESTCASE_LOOPS = True

# FIX 1: a *memo table* (stores & reuses computed results) collapses recursion to
# polynomial.  A *visited set* (seen/visited) used in backtracking does NOT --
# it only prunes, the call tree is still exponential.  Keep them separate.
_MEMO_NAMES: frozenset = frozenset({"memo", "cache", "dp"})


def _reads_input(node: ast.AST) -> bool:
    """True if this subtree reads stdin -- its cost does not scale with n."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "input":
            return True
        if isinstance(n, ast.Attribute) and n.attr in {"readline", "readlines", "read"}:
            return True
    return False


# ===========================================================================
# AST visitor
# ===========================================================================
class _SignalDetector(ast.NodeVisitor):
    def __init__(self) -> None:
        self._s = DetectionSignals()
        self._loop_depth: int = 0
        self._func_stack: list = []
        self._in_main_block: bool = False
        self._setlike: set = set()    # names bound to dict/set  -> O(1) membership
        self._listlike: set = set()   # FIX 3: names bound to list/tuple -> O(n) membership
        self._while_cond_stack: list = []  # FIX H: stack of enclosing while-condition var sets

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
        if not self._in_main_block and self._is_exponential_iter(node.iter):
            self._s.exponential_loop = True        # FIX B
        if not self._in_main_block and self._is_testcase_loop(node):
            self.generic_visit(node)               # FIX D: don't count test-case loop depth
            return
        self._enter_loop(node)

    def _is_testcase_loop(self, node: ast.For) -> bool:
        """FIX D: `for _ in range(T): ... input ...` repeats per test case, not per n."""
        if not DISCOUNT_TESTCASE_LOOPS or not isinstance(node.target, ast.Name):
            return False
        it = node.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range"):
            return False                            # only bounded count loops
        if not any(_reads_input(st) for st in node.body):
            return False                            # each case reads its own input
        tgt = node.target.id
        target_uses = sum(1 for n in ast.walk(node)
                          if isinstance(n, ast.Name) and n.id == tgt)
        return tgt == "_" or target_uses <= 1       # loop var unused -> "repeat T times"

    @staticmethod
    def _is_exp_expr(e: ast.AST) -> bool:
        if isinstance(e, ast.BinOp):
            if isinstance(e.op, ast.LShift) and _is_const(e.left, 1):
                return True    # 1 << n
            if isinstance(e.op, ast.Pow) and _is_const(e.left, 2):
                return True    # 2 ** n
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
                and e.func.id == "pow" and e.args and _is_const(e.args[0], 2)):
            return True        # pow(2, n)
        return False

    def _is_exponential_iter(self, it: ast.AST) -> bool:
        if not isinstance(it, ast.Call):
            return False
        func = it.func
        if isinstance(func, ast.Name):
            if func.id == "range" and any(self._is_exp_expr(a) for a in it.args):
                return True
            if func.id in _EXP_ITER:
                return True
        if isinstance(func, ast.Attribute) and func.attr in _EXP_ITER:
            return True
        return False

    def visit_While(self, node: ast.While) -> None:
        # FIX F: a while bounded by an exponentially growing quantity
        # (while (1 << k) < n, while 2 ** k <= n, while pow(2, k) < n) runs
        # O(log n) times -- it is a logarithmic loop, not a linear scan.
        if self._has_exponential_bound(node.test):
            self._s.halving_detected = True
        cond_vars = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        # FIX H: an inner while that advances an enclosing while's loop variable
        # is a two-pointer scan -- total inner work is O(n) amortized, NOT a
        # nested O(n^2) loop. Don't bump loop depth for it.
        if (self._loop_depth > 0 and self._while_cond_stack
                and self._advances_outer_pointer(node, cond_vars)):
            self._s.two_pointer = True
            self._while_cond_stack.append(cond_vars)
            self.generic_visit(node)
            self._while_cond_stack.pop()
            return
        self._while_cond_stack.append(cond_vars)
        self._enter_loop(node)
        self._while_cond_stack.pop()

    def _advances_outer_pointer(self, node: ast.While, cond_vars: set) -> bool:
        """FIX H: inner while shares a counter with an enclosing while AND mutates it."""
        outer_vars: set = set().union(*self._while_cond_stack)
        shared = cond_vars & outer_vars
        if not shared:
            return False
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if (isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name)
                        and sub.target.id in shared):
                    return True
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name) and t.id in shared:
                            return True
        return False

    @staticmethod
    def _has_exponential_bound(test: ast.AST) -> bool:
        for sub in ast.walk(test):
            if isinstance(sub, ast.BinOp):
                if isinstance(sub.op, ast.LShift) and _is_const(sub.left, 1):
                    return True
                if isinstance(sub.op, ast.Pow) and _is_const(sub.left, 2):
                    return True
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == "pow" and len(sub.args) >= 2
                    and _is_const(sub.args[0], 2)):
                return True
        return False

    # ------------------------------------------------------- comprehensions
    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._s.growing_structures = True
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
        n_gen = len(getattr(node, "generators", [])) or 1
        self._s.total_loops_in_file += n_gen
        self._loop_depth += n_gen
        self._s.max_loop_depth = max(self._s.max_loop_depth, self._loop_depth)
        self.generic_visit(node)
        self._loop_depth -= n_gen

    # ------------------------------------------------------------------ calls
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (isinstance(func, ast.Name)
                and self._func_stack
                and func.id == self._func_stack[-1]
                and not self._in_main_block):
            self._s.recursive_calls += 1
            if self._loop_depth > 0:               # FIX 1
                self._s.recursion_in_loop = True
        # sort detection
        is_sort = False
        if isinstance(func, ast.Name) and func.id == "sorted":
            is_sort = True
            self._s.sort_detected = True
            self._s.growing_structures = True
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
                operand = node.args[0] if node.args else None
            elif isinstance(func, ast.Attribute):
                name = func.attr
                operand = func.value
            if name in _LINEAR_BUILTINS or name in _LINEAR_METHODS:
                # FIX E: min(a, b) / max(a, b, c) over multiple scalar args is
                # O(#args) = O(1), NOT a linear scan. Only a single iterable
                # argument actually scales with n.
                multi_arg_minmax = (name in ("min", "max")
                                    and isinstance(func, ast.Name)
                                    and len(node.args) >= 2)
                if not multi_arg_minmax:
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
                    elif isinstance(comp, ast.Name):
                        # FIX 3: only count as O(n) when we KNOW it's a list/tuple.
                        # set/dict are O(1); unknown containers are assumed O(1)
                        # (conservative) instead of the old assume-list default,
                        # which made `quadratic` a magnet class.
                        if comp.id in self._listlike and comp.id not in self._setlike:
                            self._s.implicit_linear_in_loop = True
        self.generic_visit(node)

    # ----------------------------------------------------- assignments / memo
    def _track_containers(self, target: ast.AST, value: Optional[ast.AST]) -> None:
        if not (isinstance(target, ast.Name) and value is not None):
            return
        is_setlike = isinstance(value, (ast.Dict, ast.Set, ast.DictComp, ast.SetComp))
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in _SETLIKE_CTORS):
            is_setlike = True
        if is_setlike:
            self._setlike.add(target.id)
            self._listlike.discard(target.id)
            return
        # FIX 3: track list/tuple-bound names so known-list membership stays O(n)
        is_listlike = isinstance(value, (ast.List, ast.Tuple, ast.ListComp))
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in _LISTLIKE_CTORS):
            is_listlike = True
        if is_listlike:
            self._listlike.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                self._s.growing_structures = True
                if target.value.id in _MEMO_NAMES:
                    self._s.memoization_detected = True
            if isinstance(target, ast.Name) and target.id in _MEMO_NAMES:
                if isinstance(node.value, (ast.Dict, ast.Call)):
                    self._s.memoization_detected = True
            self._track_containers(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in _MEMO_NAMES:
            if isinstance(node.value, (ast.Dict, ast.Call)):
                self._s.memoization_detected = True
        self._track_containers(node.target, node.value)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
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


# ===========================================================================
# Pattern detection helpers
# ===========================================================================
_HALVING_PATTERNS = [
    re.compile(r"\b(lo|hi|low|high|left|right|mid|start|end)\s*=.*//\s*2"),
    re.compile(r"len\s*\(.*\)\s*//\s*2"),
]


def _is_const(node: ast.AST, val: int) -> bool:
    return isinstance(node, ast.Constant) and node.value == val


def _is_int_const_ge(node: ast.AST, k: int) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool) and node.value >= k)


def _detect_halving_ast(tree: ast.AST, s: DetectionSignals) -> None:
    """FIX 2: AST-based halving/doubling detection (binary-search & log loops).

    Catches forms the old name-anchored regex missed:
        n //= 2 | n >>= 1 | i *= 2 | i <<= 1 | n = n // 2 | n = n >> 1
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign):
            op = type(node.op)
            # FIX C: any integer division by k>=2 (// 2, //= 10, >>= 1...) halves -> log
            if op in (ast.FloorDiv, ast.Div) and _is_int_const_ge(node.value, 2):
                s.halving_detected = True
            elif op is ast.RShift and _is_int_const_ge(node.value, 1):
                s.halving_detected = True
            elif op is ast.Mult and _is_int_const_ge(node.value, 2):
                s.halving_detected = True            # doubling toward n -> log n
            elif op is ast.LShift and _is_int_const_ge(node.value, 1):
                s.halving_detected = True
        elif isinstance(node, ast.Assign):
            # FIX G: a variable reassigned to (a function of) ITSELF divided by a
            # const halves -> log n.  Examples: x = x // 2 | x = int(x / 2) |
            # x = x >> 1 | x = math.floor(x / 3).  Requiring self-reference avoids
            # flagging one-off midpoints like `mid = len(arr) // 2` as logarithmic.
            # Binary-search midpoints (mid = (lo + hi) // 2) keep their log signal
            # via the lo/hi range-narrowing patterns and the _HALVING_PATTERNS regex.
            v = node.value
            target_names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if target_names:
                for sub in ast.walk(v):
                    if (isinstance(sub, ast.BinOp) and isinstance(sub.left, ast.Name)
                            and sub.left.id in target_names):
                        op = type(sub.op)
                        if op in (ast.FloorDiv, ast.Div) and _is_int_const_ge(sub.right, 2):
                            s.halving_detected = True
                        elif op is ast.RShift and _is_int_const_ge(sub.right, 1):
                            s.halving_detected = True


def _count_calls_in_node(node: ast.AST, name: str) -> int:
    return sum(
        1 for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == name
    )


def _count_unconditional_recursive_calls(func_node: ast.FunctionDef, name: str) -> int:
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
    for line in source.splitlines():
        if line.strip().startswith("#"):
            continue
        for pat in _HALVING_PATTERNS:
            if pat.search(line):
                s.halving_detected = True
                break
    _detect_halving_ast(tree, s)        # FIX 2
    # FIX C: recursion that passes a halved argument -- f(n // 2), f(n >> 1) -- is O(log n)
    if s.function_name and s.recursive_calls > 0:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == s.function_name):
                for arg in node.args:
                    if isinstance(arg, ast.BinOp):
                        if (isinstance(arg.op, (ast.FloorDiv, ast.Div))
                                and _is_int_const_ge(arg.right, 2)):
                            s.halving_detected = True
                        elif isinstance(arg.op, ast.RShift):
                            s.halving_detected = True
    if s.function_name and s.recursive_calls > 0:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == s.function_name:
                branches = _count_unconditional_recursive_calls(node, s.function_name)
                s.recursive_branches = max(s.recursive_branches, branches)
                break
    if s.recursive_calls > 0 and s.halving_detected and s.recursive_branches >= 2:
        s.divide_and_conquer = True
    s.effective_loop_depth = s.max_loop_depth
    if s.implicit_linear_in_loop and s.max_loop_depth == 1:
        s.effective_loop_depth = 2


# ===========================================================================
# Inference
# ===========================================================================
def _infer_complexity(s: DetectionSignals):
    effective_depth = s.effective_loop_depth
    if effective_depth == 0 and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        effective_depth = min(s.total_loops_in_file, 2)

    # -- time --
    if s.exponential_loop:                          # FIX B
        time = "O(2\u207f)"
        time_why = ("Iterates over an exponential/permutation search space "
                    "(2**n, 1<<n, or permutations/product) \u2014 exponential.")
    elif s.recursive_calls > 0:
        if s.halving_detected and s.recursive_branches < 2 and not s.recursion_in_loop:
            time = "O(log n)"
            time_why = "Single-branch recursion that halves the input each call \u2014 O(log n)."
            space = "O(log n)"
            space_why = "Recursion stack depth is O(log n) due to input halving."
            return time, space, time_why, space_why
        if s.divide_and_conquer:
            has_linear_combine = s.recursive_branches >= 2 or s.max_loop_depth >= 1
            if has_linear_combine:
                time = "O(n log n)"
                time_why = ("Divide-and-conquer recursion (input halved each call) "
                            "with a linear merge/combine step.")
            else:
                time = "O(log n)"
                time_why = "Input is halved each recursive call with no extra linear work."
        elif s.memoization_detected:
            time = "O(n)"
            time_why = "Recursive with memoization \u2014 each subproblem computed once."
        elif s.recursive_branches >= 2 or s.recursion_in_loop:        # FIX 1
            base = max(s.recursive_branches, 2)
            time = f"O({base}\u207f)"
            if s.recursion_in_loop and s.recursive_branches < 2:
                time_why = ("Recursive call(s) inside a loop \u2014 branching call tree, "
                            "exponential without memoization.")
            else:
                time_why = f"{base} recursive branches per call -> exponential call tree."
        else:
            if s.max_loop_depth >= 1:
                if s.max_loop_depth == 1:
                    time = "O(n\u00b2)"
                    time_why = "Linear recursion with a loop inside each call -> O(n^2)."
                else:
                    time = f"O(n^{s.max_loop_depth + 1})"
                    time_why = f"Linear recursion with {s.max_loop_depth}-deep loops inside each call."
            else:
                time = "O(n)"
                time_why = "Single recursive call per invocation \u2014 linear recursion depth."
    elif s.memoization_detected and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        time = "O(n)"
        time_why = "Memoized computation \u2014 each unique subproblem solved once."
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
        time_why = "Sort operation dominates \u2014 O(n log n)."
    elif effective_depth == 0:
        time = "O(1)"
        time_why = "No loops, recursion, or implicit linear work \u2014 constant time."
    elif effective_depth == 1:
        time = "O(n)"
        time_why = "Single loop (or equivalent linear scan) over the input."
    elif effective_depth == 2:
        if s.implicit_linear_in_loop and s.max_loop_depth == 1:
            time = "O(n\u00b2)"
            time_why = ("Implicit O(n) operation (membership test, builtin scan, or "
                        "comprehension) inside a loop -> O(n^2).")
        else:
            time = "O(n\u00b2)"
            time_why = "Two nested loops \u2014 quadratic time."
    else:
        time = f"O(n^{effective_depth})"
        time_why = f"{effective_depth} effective loop levels \u2014 polynomial time."

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
        space_why = "Only fixed-size variables used \u2014 constant extra space."

    return time, space, time_why, space_why


# ===========================================================================
# Public API
# ===========================================================================
def _find_inner_recursive_helpers(tree: ast.AST, signals: DetectionSignals) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        inner_name = node.name
        if inner_name == signals.function_name:
            continue
        self_calls = sum(
            1 for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == inner_name
        )
        if self_calls == 0:
            continue
        # FIX 1: inner helper recursing inside a loop -> branching/exponential
        for loop in ast.walk(node):
            if isinstance(loop, (ast.For, ast.While)) and _count_calls_in_node(loop, inner_name) > 0:
                signals.recursion_in_loop = True
                break
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


def estimate_complexity(code_str: str):
    try:
        result = analyze(code_str)
        return result.time_complexity, result.space_complexity
    except Exception as exc:
        return "Error", f"{type(exc).__name__}: {exc}"
