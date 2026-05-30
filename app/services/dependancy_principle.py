"""
DIP (Dependency Inversion Principle) Analyzer
==============================================
Statically analyses Python source code for violations of the Dependency
Inversion Principle:

    "High-level modules should not depend on low-level modules.
     Both should depend on abstractions."

Rules
-----
DIP001  __init__ parameter typed with a concrete class.
DIP002  Method parameter typed with a concrete class.
DIP003  Direct instantiation of a concrete class inside a class body or method.
DIP004  Class / instance attribute annotated with a concrete class.
DIP005  Class inherits from a concrete class (not an abstraction).
DIP006  Method return type is a concrete class.
"""

from __future__ import annotations

import ast
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTIN_TYPES: frozenset[str] = frozenset({
    # primitives
    "str", "int", "float", "bool", "bytes", "bytearray", "memoryview",
    "complex",
    # collections
    "list", "dict", "tuple", "set", "frozenset",
    # typing aliases (also accepted as abstractions since they're protocols)
    "None", "Any", "Optional", "Union", "Type", "Literal",
    "Callable", "Awaitable", "Coroutine",
    "Generator", "Iterator", "Iterable", "AsyncIterator", "AsyncIterable",
    "AsyncGenerator",
    "Sequence", "MutableSequence",
    "Mapping", "MutableMapping",
    "Set", "MutableSet",
    "ClassVar", "Final", "TypeVar", "ParamSpec", "Annotated",
    # common safe names
    "Self", "Never", "NoReturn", "object",
    # exceptions are not DIP violations
    "Exception", "BaseException", "ValueError", "TypeError",
    "KeyError", "IndexError", "RuntimeError", "StopIteration",
    "OSError", "IOError", "NotImplementedError", "AttributeError",
    "ImportError", "NameError", "PermissionError", "FileNotFoundError",
})

# Naming heuristics for classes we cannot resolve from the local AST.
# Only treat a name as "abstract-by-convention" when the pattern is
# unambiguous — "I" prefix ONLY if the very next character is uppercase,
# preventing false negatives on names like "Image", "Index", "Item".
_ABSTRACT_SUFFIXES: tuple[str, ...] = (
    "Base", "ABC", "Abstract", "Protocol", "Interface", "Mixin",
    # DDD / hexagonal architecture conventions — only unambiguous abstract nouns.
    # "Store", "Service", "Handler" etc. are deliberately omitted: they are
    # equally common as concrete class names (e.g. SqliteStore, FileHandler).
    "Repository", "Gateway", "Port", "Resolver",
)

# Transparent generic wrappers — drill into their type argument(s)
_TRANSPARENT_WRAPPERS: frozenset[str] = frozenset({
    "Optional", "Union", "List", "Set", "FrozenSet", "Sequence", "Iterable",
    "Iterator", "AsyncIterator", "AsyncIterable", "Generator", "AsyncGenerator",
    "Type", "ClassVar", "Final", "Awaitable", "Coroutine",
    # lower-case built-in generics (3.9+)
    "list", "set", "frozenset", "tuple", "type",
})


def _looks_abstract_by_name(name: str) -> bool:
    """Heuristic: does the class name follow an abstraction naming convention?"""
    if len(name) >= 2 and name[0] == "I" and name[1].isupper():
        return True
    return any(name.endswith(s) for s in _ABSTRACT_SUFFIXES)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class Violation(NamedTuple):
    filename: str
    line: int
    col: int
    message: str

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}: {self.message}"


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _collect_concrete_names(annotation: ast.expr) -> list[str]:
    """
    Recursively collect all type names embedded in an annotation.

    Unlike the old ``_extract_type_name`` this function drills into *every*
    argument of every generic alias so that composite types like
    ``Dict[str, ConcreteClass]``, ``Tuple[Foo, Bar]``, and
    ``Union[Foo, Bar, None]`` are fully checked.

    Returns a flat list of bare type-name strings (may be empty).
    """
    if isinstance(annotation, ast.Name):
        return [annotation.id]

    if isinstance(annotation, ast.Attribute):
        return [annotation.attr]

    if isinstance(annotation, ast.Constant):
        # Forward-reference strings — parse them for completeness.
        if isinstance(annotation.value, str):
            try:
                inner = ast.parse(annotation.value, mode="eval").body
                return _collect_concrete_names(inner)
            except SyntaxError:
                pass
        return []  # None constant or other literal

    if isinstance(annotation, ast.Subscript):
        outer_name = _extract_outer_name(annotation.value)

        # Annotated[X, metadata, …]  — only X is a type; skip metadata args.
        if outer_name == "Annotated":
            slice_node = annotation.slice
            # The first element of the tuple is the real type.
            if isinstance(slice_node, ast.Tuple) and slice_node.elts:
                return _collect_concrete_names(slice_node.elts[0])
            return _collect_concrete_names(slice_node)

        # Dict / Mapping / Tuple / … — check all inner args.
        if outer_name in _TRANSPARENT_WRAPPERS or outer_name in (
            "Dict", "Mapping", "MutableMapping", "Tuple", "MutableSet",
            "dict", "tuple",
        ):
            return _collect_from_slice(annotation.slice)

        # Unknown generic — surface only the outer name; don't dig inside
        # (e.g. ``MyGeneric[int]`` — the violation is ``MyGeneric`` itself).
        return [outer_name] if outer_name else []

    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # PEP 604: X | Y | Z
        return (
            _collect_concrete_names(annotation.left)
            + _collect_concrete_names(annotation.right)
        )

    if isinstance(annotation, ast.Tuple):
        # Bare tuple of types (used in some Callable / generic contexts)
        names: list[str] = []
        for elt in annotation.elts:
            names.extend(_collect_concrete_names(elt))
        return names

    return []


def _extract_outer_name(node: ast.expr) -> str | None:
    """Return the bare name of the outermost generic, e.g. ``Optional`` from ``Optional[X]``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _collect_from_slice(slice_node: ast.expr) -> list[str]:
    """Expand a subscript slice (Name, Tuple of Names, …) into type names."""
    if isinstance(slice_node, ast.Tuple):
        names: list[str] = []
        for elt in slice_node.elts:
            names.extend(_collect_concrete_names(elt))
        return names
    return _collect_concrete_names(slice_node)


# Keep a thin compatibility shim used by inheritance checking (single name).
def _extract_type_name(annotation: ast.expr) -> str | None:
    """
    Return *one* representative name from an annotation.

    Prefer ``_collect_concrete_names`` for full analysis; this shim exists
    for the inheritance-base check where only one name is expected.
    """
    names = _collect_concrete_names(annotation)
    return names[0] if names else None


def _is_abstract_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has an @abstractmethod decorator."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "abstractmethod":
            return True
    return False


def _has_only_pass_or_ellipsis(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Return True if the function body contains only ``pass``, ``...``,
    a docstring, or a ``raise`` statement — signals of an interface stub.
    """
    for stmt in node.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Raise):
            continue  # raise NotImplementedError(...) or bare raise
        if isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Constant) and val.value is ...:
                continue
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                continue
        return False
    return True


def _raises_not_implemented(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Return True if the function body raises ``NotImplementedError``.

    This distinguishes intentional interface stubs from trivially empty
    concrete methods (``def noop(self): pass``).
    """
    for stmt in node.body:
        if not isinstance(stmt, ast.Raise) or stmt.exc is None:
            continue
        exc = stmt.exc
        if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
            return True
        if (
            isinstance(exc, ast.Call)
            and isinstance(exc.func, ast.Name)
            and exc.func.id == "NotImplementedError"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Class registry builder
# ---------------------------------------------------------------------------

@dataclass
class ClassRegistry:
    """Tracks which class names are abstract vs concrete within one module."""
    abstract: set[str] = field(default_factory=set)
    concrete: set[str] = field(default_factory=set)

    def classify(self, name: str) -> str:
        """Return 'abstract', 'concrete', or 'unknown'."""
        if name in self.abstract:
            return "abstract"
        if name in self.concrete:
            return "concrete"
        return "unknown"


def _build_class_registry(tree: ast.Module) -> ClassRegistry:
    """
    Walk the top-level AST and classify every class definition.

    A class is treated as *abstract* when ANY of the following hold:
      1. It inherits from ``ABC``, ``abc.ABC``, ``Protocol``, or ``typing.Protocol``.
      2. At least one of its methods is decorated with ``@abstractmethod``.
      3. At least one method body is a stub (``pass`` / ``...`` / docstring only)
         AND the class itself has a method with no concrete implementation —
         this catches informal interfaces.
      4. Its name satisfies ``_looks_abstract_by_name``.
    """
    registry = ClassRegistry()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Rule 1 — bases
        inherits_abstract = any(
            (isinstance(b, ast.Name) and b.id in ("ABC", "Protocol"))
            or (isinstance(b, ast.Attribute) and b.attr in ("ABC", "Protocol"))
            for b in node.bases
        )

        # Rule 2 — @abstractmethod on any method (sync or async)
        has_abstract_method = any(
            _is_abstract_method(item)
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

        # Rule 3 — all non-dunder methods are stubs AND at least one raises
        # NotImplementedError, signalling intentional interface design.
        # A plain ``pass`` body alone is not sufficient — that's a valid (if
        # empty) concrete implementation and should not be treated as abstract.
        non_dunder_methods = [
            item for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not (item.name.startswith("__") and item.name.endswith("__"))
        ]
        all_stubs = bool(non_dunder_methods) and all(
            _has_only_pass_or_ellipsis(m) for m in non_dunder_methods
        ) and any(
            _raises_not_implemented(m) for m in non_dunder_methods
        )

        # Rule 4 — name convention
        name_looks_abstract = _looks_abstract_by_name(node.name)

        if inherits_abstract or has_abstract_method or all_stubs or name_looks_abstract:
            registry.abstract.add(node.name)
        else:
            registry.concrete.add(node.name)

    return registry


# ---------------------------------------------------------------------------
# Concreteness check
# ---------------------------------------------------------------------------

def _is_concrete(typename: str | None, registry: ClassRegistry) -> bool:
    """
    Return True iff *typename* refers to a concrete (non-abstract) class.

    Resolution order:
    1. Reject ``None`` / empty string.
    2. Reject built-in / typing names → not a DIP concern.
    3. Check registry (authoritative for classes seen in the same file).
    4. Fall back to naming heuristics for imported types.
    """
    if not typename:
        return False
    if typename in _BUILTIN_TYPES:
        return False

    classification = registry.classify(typename)
    if classification == "abstract":
        return False
    if classification == "concrete":
        return True

    # Unknown — imported type; use heuristics
    if _looks_abstract_by_name(typename):
        return False

    # Assume concrete only if it starts with an uppercase letter
    return bool(typename) and typename[0].isupper()


# ---------------------------------------------------------------------------
# Visitor
# ---------------------------------------------------------------------------

class DipAnalyzer(ast.NodeVisitor):
    """
    Walk an AST and collect DIP violations.

    Tracks:
    - Current class context (``current_class``)
    - Whether we are inside a method (``_in_method``)
    - Nesting depth of class/function scopes for ``AnnAssign`` scoping
    """

    __slots__ = (
        "filename",
        "current_class",
        "_current_method",
        "_in_method",
        "_method_decorator_kinds",
        "violations",
        "registry",
    )

    def __init__(self, filename: str, registry: ClassRegistry) -> None:
        self.filename = filename
        self.current_class: str | None = None
        self._current_method: str | None = None
        self._in_method: bool = False
        self._method_decorator_kinds: set[str] = set()
        self.violations: list[Violation] = []
        self.registry = registry

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_concrete(self, typename: str | None) -> bool:
        return _is_concrete(typename, self.registry)

    def _add(self, rule: str, line: int, col: int, detail: str) -> None:
        self.violations.append(Violation(self.filename, line, col, f"{rule} {detail}"))

    def _check_annotation(
        self,
        annotation: ast.expr,
        rule: str,
        line: int,
        col: int,
        context_msg: str,
    ) -> None:
        """
        Collect *all* type names from ``annotation`` and emit a violation for
        each concrete one.  This replaces the old pattern of calling
        ``_extract_type_name`` (which returned at most one name).
        """
        for typename in _collect_concrete_names(annotation):
            if self._is_concrete(typename):
                self._add(rule, line, col, context_msg.format(typename=typename))

    # ------------------------------------------------------------------
    # Class scope
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous_class = self.current_class
        previous_method = self._current_method
        previous_in_method = self._in_method

        self.current_class = node.name
        self._current_method = None
        self._in_method = False

        self._check_class_inheritance(node)
        self.generic_visit(node)

        self.current_class = previous_class
        self._current_method = previous_method
        self._in_method = previous_in_method

    def _check_class_inheritance(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            typename = _extract_type_name(base)
            if typename in ("ABC", "Protocol", "object", None):
                continue
            if self._is_concrete(typename):
                self._add(
                    "DIP005", node.lineno, node.col_offset,
                    f"Class '{node.name}' inherits from concrete class '{typename}'."
                )

    # ------------------------------------------------------------------
    # Method / function scope
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_any_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_any_function(node)

    def _visit_any_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        previous_method = self._current_method
        previous_in_method = self._in_method
        previous_decorators = self._method_decorator_kinds

        self._current_method = node.name
        self._in_method = True
        self._method_decorator_kinds = {
            d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
            for d in node.decorator_list
        }

        if self.current_class is not None:
            self._check_method_args(node)
            self._check_return_type(node)

        self.generic_visit(node)

        self._current_method = previous_method
        self._in_method = previous_in_method
        self._method_decorator_kinds = previous_decorators

    def _check_method_args(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """
        Check every parameter annotation, skipping implicit ``self``/``cls``.

        Covers: positional, keyword-only, positional-only, *args, **kwargs.
        """
        is_static = "staticmethod" in self._method_decorator_kinds
        rule = "DIP001" if node.name == "__init__" else "DIP002"

        all_positional = node.args.args
        args_to_check = all_positional if is_static else all_positional[1:]

        def _check_arg(arg: ast.arg) -> None:
            if arg.annotation is None:
                return
            self._check_annotation(
                arg.annotation, rule, arg.lineno, arg.col_offset,
                f"Class '{self.current_class}' depends on concrete class '{{typename}}' "
                f"in '{node.name}'. Use an abstraction instead.",
            )

        for arg in args_to_check:
            _check_arg(arg)

        for arg in (*node.args.kwonlyargs, *(node.args.posonlyargs or [])):
            _check_arg(arg)

        # *args and **kwargs annotations
        if node.args.vararg and node.args.vararg.annotation:
            _check_arg(node.args.vararg)
        if node.args.kwarg and node.args.kwarg.annotation:
            _check_arg(node.args.kwarg)

    def _check_return_type(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        if node.returns is None or node.name == "__init__":
            return
        # Factory/classmethod pattern: returning the class itself is not a violation.
        names_to_skip = {self.current_class, "Self"}
        for typename in _collect_concrete_names(node.returns):
            if typename in names_to_skip:
                continue
            if self._is_concrete(typename):
                self._add(
                    "DIP006", node.lineno, node.col_offset,
                    f"Method '{node.name}' in '{self.current_class}' "
                    f"returns concrete class '{typename}'.",
                )

    # ------------------------------------------------------------------
    # Attribute annotations  (class-level only, not local variables)
    # ------------------------------------------------------------------

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.current_class is not None and not self._in_method:
            self._check_annotation(
                node.annotation, "DIP004", node.lineno, node.col_offset,
                f"Class '{self.current_class}' has class-level attribute "
                f"annotated with concrete class '{{typename}}'.",
            )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Direct instantiation
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        # Only check calls that are directly inside a class scope.
        if self.current_class is not None:
            typename = _extract_type_name(node.func)
            if (
                typename
                and typename not in ("super", self.current_class)
                and typename not in _BUILTIN_TYPES
                and self._is_concrete(typename)
            ):
                if self._current_method:
                    context = (
                        "__init__" if self._current_method == "__init__"
                        else f"'{self._current_method}'"
                    )
                else:
                    context = "class body"

                self._add(
                    "DIP003", node.lineno, node.col_offset,
                    f"Class '{self.current_class}' directly instantiates concrete "
                    f"class '{typename}' in {context}. Inject via constructor instead."
                )
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_file(path: str) -> list[Violation]:
    """Parse *path* and return all DIP violations found."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except OSError as exc:
        warnings.warn(f"Cannot read '{path}': {exc}", stacklevel=2)
        return []

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        warnings.warn(f"Syntax error in '{path}': {exc}", stacklevel=2)
        return []

    registry = _build_class_registry(tree)
    analyzer = DipAnalyzer(path, registry)
    analyzer.visit(tree)
    return analyzer.violations


def analyze_directory(
    folder: str,
    *,
    max_workers: int | None = None,
    exclude_dirs: frozenset[str] = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules"}),
) -> list[Violation]:
    """
    Recursively analyse all ``.py`` files under *folder*.

    Parameters
    ----------
    folder:
        Root directory to scan.
    max_workers:
        Thread-pool size. Defaults to ``min(32, cpu_count + 4)``.
    exclude_dirs:
        Directory names to skip (matched against the basename only).
    """
    py_files: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for fname in files:
            if fname.endswith(".py"):
                py_files.append(os.path.join(root, fname))

    results: list[Violation] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(analyze_file, p): p for p in py_files}
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"Error analysing '{futures[future]}': {exc}", stacklevel=2)

    results.sort(key=lambda v: (v.filename, v.line))
    return results


def get_dip_report(code_str: str) -> dict[str, object]:
    """
    Analyse an in-memory code string and return a structured report.

    Returns a dict with:
    - ``status``      : "Pass" | "Violation" | "Error"
    - ``violations``  : list of violation dicts (empty on Pass/Error)
    - ``reason``      : human-readable summary
    - ``suggestion``  : remediation guidance
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError as exc:
        return {
            "status": "Error",
            "violations": [],
            "reason": f"Syntax error: {exc}",
            "suggestion": "Fix the syntax error before running the DIP analyser.",
        }

    registry = _build_class_registry(tree)
    analyzer = DipAnalyzer("<string>", registry)
    analyzer.visit(tree)

    if not analyzer.violations:
        return {
            "status": "Pass",
            "violations": [],
            "reason": "No concrete class dependencies detected.",
            "suggestion": "N/A",
        }

    return {
        "status": "Violation",
        "violations": [
            {"line": v.line, "col": v.col, "message": v.message}
            for v in analyzer.violations
        ],
        "reason": (
            f"{len(analyzer.violations)} violation(s) found. "
            f"First: Line {analyzer.violations[0].line}: {analyzer.violations[0].message}"
        ),
        "suggestion": (
            "Inject abstractions (interfaces/abstract classes) instead of concrete classes. "
            "Define a Protocol or ABC for each dependency and accept it in __init__."
        ),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python dip_analyzer.py <file_or_directory>", file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1]
    violations = (
        analyze_directory(target) if os.path.isdir(target) else analyze_file(target)
    )

    if not violations:
        print("✓ No DIP violations found.")
        sys.exit(0)
    else:
        for v in violations:
            print(v)
        print(f"\n{len(violations)} violation(s) found.", file=sys.stderr)
        sys.exit(1)