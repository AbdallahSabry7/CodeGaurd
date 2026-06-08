from __future__ import annotations

import ast
import re
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
    recursion_in_loop: bool = False
    # Patterns
    halving_detected: bool = False
    sort_detected: bool = False
    sort_in_loop: bool = False
    memoization_detected: bool = False
    growing_structures: bool = False
    divide_and_conquer: bool = False
    implicit_linear_in_loop: bool = False
    inner_recursive_memo: bool = False
    exponential_loop: bool = False
    two_pointer: bool = False
    # FIX #1: dimensionality of the memo/DP state (key arity) -> O(n^arity)
    memo_key_arity: int = 0
    # FIX #2: recursive calls descend into a bounded structure (tree/graph) -> linear
    branches_on_substructure: bool = False
    # FIX #2/#3: a *monotonic* visited/seen set guards recursion (graph traversal -> linear)
    visited_guard: bool = False
    # FIX #2/#3: visited state is added AND undone in the same scope (backtracking -> exponential)
    visited_backtracking: bool = False

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
_EXP_ITER: frozenset = frozenset({"permutations", "product"})

DISCOUNT_TESTCASE_LOOPS = True

_MEMO_NAMES: frozenset = frozenset({"memo", "cache", "dp"})
# FIX #3: names/structures that PRUNE a search but do not collapse it.
_VISITED_NAMES: frozenset = frozenset({"seen", "visited", "vis", "used", "done", "explored"})
# Constructors that build a memo table (dict-like) vs a visited set (set/list-like).
_MEMO_CTORS: frozenset = frozenset({"dict", "Counter", "defaultdict", "OrderedDict"})
_VISITED_CTORS: frozenset = frozenset({"set", "frozenset", "list", "tuple", "deque"})
_CACHE_DECORATORS: frozenset = frozenset({"lru_cache", "cache"})


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
        self._setlike: set = set()
        self._listlike: set = set()
        self._while_cond_stack: list = []

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

        # FIX #3: classify default-arg containers as memo (dict-like) vs visited (set/list-like)
        # instead of treating every Dict/List/Set default as memoization.
        self._classify_default_args(node)

        # FIX #1: functools.lru_cache / cache decorator == memoization; key arity == #params.
        for dec in node.decorator_list:
            if _decorator_name(dec) in _CACHE_DECORATORS:
                self._s.memoization_detected = True
                n_params = len([a for a in node.args.args if a.arg not in ("self", "cls")])
                self._s.memo_key_arity = max(self._s.memo_key_arity, n_params)

        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def _classify_default_args(self, node: ast.FunctionDef) -> None:
        pos = node.args.args
        defaults = node.args.defaults
        paired = list(zip(pos[len(pos) - len(defaults):], defaults)) if defaults else []
        paired += [
            (a, d) for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults) if d is not None
        ]
        for arg, default in paired:
            kind = _classify_container(arg.arg, default)
            if kind == "memo":
                self._s.memoization_detected = True
            elif kind == "visited":
                self._s.visited_guard = True

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
            self._s.exponential_loop = True
        if not self._in_main_block and self._is_testcase_loop(node):
            self.generic_visit(node)
            return
        self._enter_loop(node)

    def _is_testcase_loop(self, node: ast.For) -> bool:
        if not DISCOUNT_TESTCASE_LOOPS or not isinstance(node.target, ast.Name):
            return False
        it = node.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range"):
            return False
        if not any(_reads_input(st) for st in node.body):
            return False
        tgt = node.target.id
        target_uses = sum(1 for n in ast.walk(node)
                          if isinstance(n, ast.Name) and n.id == tgt)
        return tgt == "_" or target_uses <= 1

    @staticmethod
    def _is_exp_expr(e: ast.AST) -> bool:
        if isinstance(e, ast.BinOp):
            if isinstance(e.op, ast.LShift) and _is_const(e.left, 1):
                return True
            if isinstance(e.op, ast.Pow) and _is_const(e.left, 2):
                return True
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
                and e.func.id == "pow" and e.args and _is_const(e.args[0], 2)):
            return True
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
        if self._has_exponential_bound(node.test):
            self._s.halving_detected = True
        cond_vars = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
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
            if self._loop_depth > 0:
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
                        self._s.implicit_linear_in_loop = True
                    elif isinstance(comp, ast.Name):
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


def _decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return ""


def _classify_container(arg_name: str, default: ast.AST) -> Optional[str]:
    """FIX #3: 'memo' (dict-like, collapses recursion) vs 'visited' (set/list-like, prunes only)."""
    if arg_name in _MEMO_NAMES:
        return "memo"
    if arg_name in _VISITED_NAMES:
        return "visited"
    if isinstance(default, ast.Dict):
        return "memo"
    if isinstance(default, (ast.Set, ast.List, ast.Tuple)):
        return "visited"
    if isinstance(default, ast.Call) and isinstance(default.func, ast.Name):
        if default.func.id in _MEMO_CTORS:
            return "memo"
        if default.func.id in _VISITED_CTORS:
            return "visited"
    return None


def _subscript_slice(node: ast.Subscript) -> ast.AST:
    sl = node.slice
    if isinstance(sl, ast.Index):  # py<3.9 compatibility
        return sl.value
    return sl


def _detect_memo_arity(tree: ast.AST, s: DetectionSignals) -> None:
    """FIX #1: estimate the dimensionality of the DP/memo state.

    memo[i]        -> arity 1   (O(n))
    memo[i][j]     -> arity 2   (O(n^2))
    memo[(i, j)]   -> arity 2   (O(n^2))
    @lru_cache f(i, j) -> arity 2 (handled at the decorator site)
    """
    arity = s.memo_key_arity
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        chain = 0
        base = node
        while isinstance(base, ast.Subscript):
            chain += 1
            base = base.value
        if isinstance(base, ast.Name) and base.id in _MEMO_NAMES:
            a = chain
            sl = _subscript_slice(node)
            if isinstance(sl, ast.Tuple):
                a = max(a, len(sl.elts))
            arity = max(arity, a)
    if s.memoization_detected and arity == 0:
        arity = 1
    s.memo_key_arity = arity


def _setlike_names(tree: ast.AST) -> set:
    """Names bound to a set/frozenset (candidate visited containers)."""
    names = set(_VISITED_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            val = node.value
            is_set = isinstance(val, (ast.Set, ast.SetComp))
            if (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                    and val.func.id in ("set", "frozenset")):
                is_set = True
            if is_set:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
    return names


def _detect_visited_pattern(tree: ast.AST, s: DetectionSignals) -> None:
    """FIX #2/#3: distinguish a monotonic visited-set (graph traversal -> linear)
    from a backtracking add/undo (state restored -> exponential)."""
    containers = _setlike_names(tree)
    guarded = added = removed = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comp, ast.Name) \
                        and comp.id in containers:
                    guarded = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in containers:
                if node.func.attr in {"add", "append", "push", "update"}:
                    added = True
                if node.func.attr in {"remove", "discard", "pop"}:
                    removed = True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                        and t.value.id in containers:
                    added = True
        if isinstance(node, ast.Delete):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                        and t.value.id in containers:
                    removed = True
    s.visited_guard = s.visited_guard or guarded or added
    s.visited_backtracking = s.visited_backtracking or (added and removed)


def _detect_traversal_shape(tree: ast.AST, s: DetectionSignals) -> None:
    """FIX #2: recursive calls whose arguments descend into a data structure
    (node.left, root.children, arr[1:]) traverse a bounded structure -> linear,
    NOT exponential."""
    recursive_names = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and _count_calls_in_node(fn, fn.name) > 0:
            recursive_names.add(fn.name)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in recursive_names):
            for a in node.args:
                if isinstance(a, (ast.Attribute, ast.Subscript)):
                    s.branches_on_substructure = True


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
    _detect_halving_ast(tree, s)
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


def _detect_halving_ast(tree: ast.AST, s: DetectionSignals) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign):
            op = type(node.op)
            if op in (ast.FloorDiv, ast.Div) and _is_int_const_ge(node.value, 2):
                s.halving_detected = True
            elif op is ast.RShift and _is_int_const_ge(node.value, 1):
                s.halving_detected = True
            elif op is ast.Mult and _is_int_const_ge(node.value, 2):
                s.halving_detected = True
            elif op is ast.LShift and _is_int_const_ge(node.value, 1):
                s.halving_detected = True
        elif isinstance(node, ast.Assign):
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


# ===========================================================================
# Inference
# ===========================================================================
def _infer_complexity(s: DetectionSignals):
    effective_depth = s.effective_loop_depth
    if effective_depth == 0 and s.total_loops_in_file > 0 and s.recursive_calls == 0:
        effective_depth = min(s.total_loops_in_file, 2)

    space = "O(1)"
    space_why = "Only fixed-size variables used \u2014 constant extra space."

    # -- time --
    if s.exponential_loop:
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
            # FIX #1: memoized recursion is O(#states) = O(n^arity), NOT always O(n).
            k = max(s.memo_key_arity, 1)
            time, time_why = _poly_from_degree(
                k, "Recursive with memoization \u2014 "
                f"{k}-D memo key -> {k} dimension(s) of n distinct subproblems.")
        elif s.visited_backtracking:
            # FIX #2: state added then undone -> genuine exponential search.
            base = max(s.recursive_branches, 2)
            time = f"O({base}\u207f)"
            time_why = "Backtracking recursion (visited state added then undone) \u2014 exponential search space."
        elif s.branches_on_substructure or s.visited_guard:
            # FIX #2: calls descend into a bounded structure / guarded by a monotonic
            # visited-set (tree / graph traversal) -> linear in total nodes & edges.
            time = "O(n)"
            time_why = ("Recursive calls descend into a bounded structure or are guarded by a "
                        "monotonic visited-set (tree/graph traversal) \u2014 linear in total nodes.")
        elif s.recursive_branches >= 2 or s.recursion_in_loop:
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
        # FIX #1: tabulated DP is O(n^max(state-arity, loop-nesting)), NOT always O(n).
        degree = max(max(s.memo_key_arity, 1), s.effective_loop_depth)
        time, time_why = _poly_from_degree(
            degree, f"Tabulated DP \u2014 {degree}-dimensional state table.")
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
        space = "O(n)" if s.memo_key_arity <= 1 else _poly_from_degree(s.memo_key_arity, "")[0]
        space_why = "Memo table and recursion call stack."
    elif s.recursive_calls > 0:
        space = "O(n)"
        space_why = "Recursion call stack depth is proportional to input size."
    elif s.growing_structures:
        space = "O(n)"
        space_why = "Data structures (list/dict/set) grow proportionally with input."

    return time, space, time_why, space_why


def _poly_from_degree(degree: int, why: str):
    """Map a polynomial degree to a Big-O string + reason."""
    if degree <= 1:
        return "O(n)", why
    if degree == 2:
        return "O(n\u00b2)", why
    if degree == 3:
        return "O(n\u00b3)", why
    return f"O(n^{degree})", why


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
            signals.recursive_calls = max(signals.recursive_calls, 1)
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
    _detect_memo_arity(tree, signals)         
    _detect_visited_pattern(tree, signals)    
    _detect_traversal_shape(tree, signals)    
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
