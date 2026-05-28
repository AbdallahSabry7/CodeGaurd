"""
LSP (Liskov Substitution Principle) violation detector.

Improvements over v1:
- Two-pass architecture: collect all class definitions first, then analyze
  methods — fixes ordering issues where child is defined before parent.
- Deduplication: violations are keyed by (line, message) so multi-level
  inheritance chains don't produce duplicate reports.
- classmethod/staticmethod-aware self/cls skipping in extract_signature.
- Removed high-false-positive "every if-raise = stricter precondition" rule;
  replaced with a narrower check that only flags raises on bare argument
  equality/identity checks at the top of a method.
- Return-type check now understands None, Optional[X] ~ X, and bare names.
- Severity enum for structured filtering downstream.
- get_lsp_report returns all violations, not just the first.
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


@dataclass(frozen=True)
class Violation:
    line: int
    message: str
    severity: Severity = Severity.MEDIUM


def exc_name_from_raise(node: ast.Raise) -> str:
    """Extract exception class name from a raise statement."""
    if node.exc is None:
        return ""
    if isinstance(node.exc, ast.Name):
        return node.exc.id
    if isinstance(node.exc, ast.Call):
        func = node.exc.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    if isinstance(node.exc, ast.Attribute):
        return node.exc.attr
    if isinstance(node.exc, ast.Subscript):
        if isinstance(node.exc.value, ast.Name):
            return node.exc.value.id
    return ""


def _decorator_names(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for d in func.decorator_list:
        if isinstance(d, ast.Name):
            names.add(d.id)
        elif isinstance(d, ast.Attribute):
            names.add(d.attr)
    return names


def _is_classmethod(func: ast.FunctionDef) -> bool:
    return bool(_decorator_names(func) & {"classmethod"})


def _is_staticmethod(func: ast.FunctionDef) -> bool:
    return bool(_decorator_names(func) & {"staticmethod"})


# ---------------------------------------------------------------------------
# Abstract-class / abstract-method detection
# ---------------------------------------------------------------------------

_ABSTRACT_DECORATORS = {
    "abstractmethod",
    "abstractproperty",
    "abstractclassmethod",
    "abstractstaticmethod",
}

_ABSTRACT_DOC_TRIGGERS = {
    "not implemented",
    "abstract method",
    "subclasses should implement",
    "to be implemented by subclass",
    "abstract",
    "must implement",
    "override",
    "implement me",
}


def is_abstract_method(node: ast.FunctionDef) -> bool:
    # Decorator-based
    if _decorator_names(node) & _ABSTRACT_DECORATORS:
        return True

    # Single-statement body patterns
    if len(node.body) == 1:
        stmt = node.body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            return True
        if (
            isinstance(stmt, ast.Return)
            and isinstance(stmt.value, ast.Name)
            and stmt.value.id == "NotImplemented"
        ):
            return True

    # Raises NotImplementedError anywhere in body
    for n in ast.walk(node):
        if isinstance(n, ast.Raise) and exc_name_from_raise(n) == "NotImplementedError":
            return True

    # Docstring hints
    doc = ast.get_docstring(node)
    if doc and any(t in doc.lower() for t in _ABSTRACT_DOC_TRIGGERS):
        return True

    return False


def is_abstract_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = None
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in ("ABC", "ABCMeta"):
            return True

    return any(
        isinstance(item, ast.FunctionDef) and is_abstract_method(item)
        for item in node.body
    )


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

@dataclass
class Signature:
    positional: list[str]
    kwonly: list[str]
    n_defaults: int
    vararg: Optional[str]
    kwarg: Optional[str]
    annotations: dict[str, str]  # param_name -> source string
    return_annotation: Optional[str]


def extract_signature(func: ast.FunctionDef) -> Signature:
    """
    Build a Signature, skipping 'self' for regular/class methods and
    skipping nothing for static methods (they have no implicit first arg).
    """
    args = func.args
    is_static = _is_staticmethod(func)
    # For non-static methods drop the first positional arg (self / cls)
    positional_args = args.args if is_static else args.args[1:]

    def src(node) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    return Signature(
        positional=[a.arg for a in positional_args],
        kwonly=[a.arg for a in args.kwonlyargs],
        n_defaults=len(args.defaults),
        vararg=args.vararg.arg if args.vararg else None,
        kwarg=args.kwarg.arg if args.kwarg else None,
        annotations={
            a.arg: src(a.annotation)
            for a in positional_args
            if a.annotation
        },
        return_annotation=src(func.returns) if func.returns else None,
    )


# ---------------------------------------------------------------------------
# Type-compatibility helpers
# ---------------------------------------------------------------------------

_BUILTIN_HIERARCHY: dict[str, list[str]] = {
    "bool": ["int", "object"],
    "int": ["object"],
    "float": ["object"],
    "str": ["object"],
    "bytes": ["object"],
    "list": ["object"],
    "dict": ["object"],
    "tuple": ["object"],
    "set": ["object"],
    "frozenset": ["object"],
}


def _unwrap_optional(type_str: str) -> tuple[bool, str]:
    """
    Return (is_optional, inner_type).
    Handles 'Optional[X]', 'Union[X, None]', 'X | None'.
    """
    s = type_str.strip()
    if s.startswith("Optional[") and s.endswith("]"):
        return True, s[9:-1].strip()
    if s.endswith("| None"):
        return True, s[:-6].strip()
    if s.startswith("None |"):
        return True, s[6:].strip()
    # Union[X, None] — very naive but covers the common case
    if s.startswith("Union[") and s.endswith("]"):
        inner = s[6:-1]
        parts = [p.strip() for p in inner.split(",")]
        non_none = [p for p in parts if p != "None"]
        if len(non_none) == 1:
            return True, non_none[0]
    return False, s


class TypeChecker:
    def __init__(self, user_inheritance: dict[str, list[str]]):
        self._inh = user_inheritance
        self._cache: dict[tuple[str, str], bool] = {}

    def _all_parents(self, cls: str, visited: set[str] | None = None) -> set[str]:
        if visited is None:
            visited = set()
        result: set[str] = set()
        for parent in self._inh.get(cls, []) + _BUILTIN_HIERARCHY.get(cls, []):
            if parent not in visited:
                visited.add(parent)
                result.add(parent)
                result |= self._all_parents(parent, visited)
        return result

    def is_subtype(self, child: str, parent: str) -> bool:
        """Return True if child is-a parent (or equal)."""
        if child == parent:
            return True
        key = (child, parent)
        if key in self._cache:
            return self._cache[key]

        # Optional unwrapping: Optional[X] is a subtype of Optional[X] (handled above)
        # Optional[X] is NOT a subtype of X (stricter); X IS a subtype of Optional[X]
        p_opt, p_inner = _unwrap_optional(parent)
        c_opt, c_inner = _unwrap_optional(child)
        if p_opt and not c_opt:
            # parent is Optional[T], child is T  → T ⊆ Optional[T]  ✓
            result = self.is_subtype(child, p_inner)
        elif c_opt and not p_opt:
            # parent is T, child is Optional[T] → Optional[T] ⊄ T   ✗
            result = False
        else:
            result = parent in self._all_parents(child)

        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

class LSPDetector(ast.NodeVisitor):
    """
    Two-pass LSP detector.

    Pass 1 (via visit_*): collect all ClassDef and FunctionDef nodes.
    Pass 2 (via analyze): compare overriding methods against their parents.
    """

    def __init__(self):
        self._classes: dict[str, ast.ClassDef] = {}
        self._inheritance: dict[str, list[str]] = {}
        self._abstract_classes: set[str] = set()
        self._violations: list[Violation] = []
        self._seen: set[tuple[int, str]] = set()  # dedup key

    # ------------------------------------------------------------------
    # Pass 1 — collection
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._classes[node.name] = node
        parents: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                parents.append(base.id)
            elif isinstance(base, ast.Attribute):
                parents.append(base.attr)
        self._inheritance[node.name] = parents
        if is_abstract_class(node):
            self._abstract_classes.add(node.name)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Pass 2 — analysis
    # ------------------------------------------------------------------

    def analyze(self) -> list[Violation]:
        checker = TypeChecker(self._inheritance)
        for cls_name, cls_node in self._classes.items():
            all_parents = self._all_parents(cls_name)
            child_methods = {
                m.name: m
                for m in cls_node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            # Track which method names we've already checked against an ancestor
            # so that A→B→C doesn't fire B's violation twice when checking C.
            checked: set[str] = set()
            for parent_name in all_parents:
                if parent_name not in self._classes:
                    continue
                parent_cls = self._classes[parent_name]
                parent_methods = {
                    m.name: m
                    for m in parent_cls.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for method_name, child_method in child_methods.items():
                    if method_name in parent_methods and method_name not in checked:
                        self._compare(
                            child_method,
                            parent_methods[method_name],
                            cls_name,
                            parent_name,
                            checker,
                        )
                checked.update(parent_methods)
        return self._violations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_parents(self, cls: str, visited: set[str] | None = None) -> list[str]:
        """BFS order so the most direct parent is checked first."""
        if visited is None:
            visited = set()
        result: list[str] = []
        for parent in self._inheritance.get(cls, []):
            if parent not in visited:
                visited.add(parent)
                result.append(parent)
                result.extend(self._all_parents(parent, visited))
        return result

    def _add(self, node: ast.AST, msg: str, severity: Severity = Severity.MEDIUM) -> None:
        line = getattr(node, "lineno", -1)
        key = (line, msg)
        if key not in self._seen:
            self._seen.add(key)
            self._violations.append(Violation(line=line, message=msg, severity=severity))

    def _compare(
        self,
        child: ast.FunctionDef,
        parent: ast.FunctionDef,
        child_cls: str,
        parent_cls: str,
        checker: TypeChecker,
    ) -> None:
        parent_abstract = is_abstract_method(parent)
        child_sig = extract_signature(child)
        parent_sig = extract_signature(parent)
        name = child.name

        # --- Parameter count ---
        if len(child_sig.positional) != len(parent_sig.positional):
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' overrides '{parent_cls}.{name}' "
                f"with a different positional parameter count "
                f"({len(child_sig.positional)} vs {len(parent_sig.positional)}).",
                Severity.HIGH,
            )

        # --- Keyword-only parameters ---
        if child_sig.kwonly != parent_sig.kwonly:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' changes keyword-only parameters "
                f"{parent_sig.kwonly!r} → {child_sig.kwonly!r}.",
            )

        # --- Default removal (child removes a caller-relied-upon default) ---
        if child_sig.n_defaults < parent_sig.n_defaults:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' removes default parameter values "
                f"that callers may rely on.",
            )

        # --- *args / **kwargs ---
        if child_sig.vararg != parent_sig.vararg:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' changes *args "
                f"('{parent_sig.vararg}' → '{child_sig.vararg}').",
            )
        if child_sig.kwarg != parent_sig.kwarg:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' changes **kwargs "
                f"('{parent_sig.kwarg}' → '{child_sig.kwarg}').",
            )

        # --- Parameter type annotations (contravariance) ---
        for param in parent_sig.annotations:
            p_type = parent_sig.annotations[param]
            c_type = child_sig.annotations.get(param)
            if p_type and c_type and c_type != p_type:
                # Child param must accept at least as broad a type as parent
                if not checker.is_subtype(p_type, c_type):
                    self._add(
                        child,
                        f"LSP: parameter '{param}' in '{child_cls}.{name}' "
                        f"violates contravariance — parent accepts '{p_type}' "
                        f"but child requires '{c_type}'.",
                        Severity.HIGH,
                    )

        # --- Return type (covariance) ---
        p_ret = parent_sig.return_annotation
        c_ret = child_sig.return_annotation
        if p_ret and c_ret and c_ret != p_ret:
            if not checker.is_subtype(c_ret, p_ret):
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' narrows return type "
                    f"'{p_ret}' → '{c_ret}' (not a subtype).",
                    Severity.HIGH,
                )

        # --- Method binding type (static/classmethod) ---
        _important = {"staticmethod", "classmethod"}
        if _decorator_names(child) & _important != _decorator_names(parent) & _important:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' changes method binding type "
                f"(staticmethod/classmethod mismatch with '{parent_cls}.{name}').",
            )

        # --- Concrete parent: child raises NotImplementedError ---
        if not parent_abstract:
            for n in ast.walk(child):
                if isinstance(n, ast.Raise) and exc_name_from_raise(n) == "NotImplementedError":
                    self._add(
                        child,
                        f"LSP: '{child_cls}.{name}' raises NotImplementedError "
                        f"while overriding the concrete method '{parent_cls}.{name}'.",
                        Severity.HIGH,
                    )

        # --- Concrete parent: child introduces new exception types ---
        if not parent_abstract:
            parent_excs = {exc_name_from_raise(n) for n in ast.walk(parent) if isinstance(n, ast.Raise)} - {""}
            child_excs  = {exc_name_from_raise(n) for n in ast.walk(child)  if isinstance(n, ast.Raise)} - {""}
            for exc in child_excs - parent_excs:
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' introduces new exception '{exc}' "
                    f"not raised by '{parent_cls}.{name}'.",
                )

        # --- Method body is a single raise (removes all parent behavior) ---
        # Only meaningful when the parent has concrete behavior to remove.
        if (
            not parent_abstract
            and len(child.body) == 1
            and isinstance(child.body[0], ast.Raise)
        ):
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' only raises an exception and "
                f"removes all parent behavior.",
                Severity.HIGH,
            )

        # --- Stronger preconditions: assert statements ---
        for n in ast.walk(child):
            if isinstance(n, ast.Assert):
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' introduces assert statements "
                    f"(stronger preconditions than parent).",
                )
                break  # one violation per method is enough

        # --- Narrower preconditions: type-guard raises at the TOP of method.
        #     Only flag if the very first statement is an if-raise whose test
        #     is an isinstance() or identity check on a parameter.
        #     This avoids flagging ordinary business logic that happens to
        #     raise inside a conditional.
        if child.body:
            first = child.body[0]
            if (
                isinstance(first, ast.If)
                and len(first.body) == 1
                and isinstance(first.body[0], ast.Raise)
                and _is_type_guard(first.test, child_sig.positional)
            ):
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' adds a type-guard check at the "
                    f"top of the method, strengthening the parent's precondition.",
                )

        # --- Parent returns a value; child never does ---
        parent_returns = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(parent)
        )
        child_returns = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(child)
        )
        if parent_returns and not child_returns:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' discards the non-None return value "
                f"expected by '{parent_cls}.{name}'.",
                Severity.HIGH,
            )


def _is_type_guard(test: ast.expr, param_names: list[str]) -> bool:
    """
    Return True if `test` looks like a top-level type or identity guard
    on a method parameter: isinstance(x, T), x is None, not isinstance(x, T).
    """
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _is_type_guard(test.operand, param_names)
    if isinstance(test, ast.Call):
        func = test.func
        if isinstance(func, ast.Name) and func.id == "isinstance":
            args = test.args
            if args and isinstance(args[0], ast.Name) and args[0].id in param_names:
                return True
    if isinstance(test, ast.Compare):
        left = test.left
        if isinstance(left, ast.Name) and left.id in param_names:
            if any(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops):
                return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_code(code_str: str) -> list[Violation]:
    tree = ast.parse(code_str)
    detector = LSPDetector()
    detector.visit(tree)
    return detector.analyze()


def get_lsp_report(code_str: str) -> dict:
    try:
        violations = analyze_code(code_str)
        if not violations:
            return {
                "status": "Pass",
                "reason": "Subclasses maintain LSP compatibility.",
                "violations": [],
            }
        return {
            "status": "Violation",
            "violations": [
                {
                    "line": v.line,
                    "severity": v.severity.value,
                    "message": v.message,
                }
                for v in sorted(violations, key=lambda v: v.line)
            ],
            "suggestion": "Keep subclass behavior compatible with parent contracts.",
        }
    except SyntaxError as e:
        return {"status": "Error", "reason": f"Syntax error: {e}", "violations": []}
    except Exception as e:
        return {"status": "Error", "reason": str(e), "violations": []}


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

PARAM_COUNT_VIOLATION = """
class Animal:
    def process(self, x: int) -> object:
        return x

class BadDog(Animal):
    def process(self, x, y):
        return x
"""

PARAM_COUNT_PASS = """
class Animal:
    def process(self, x: int) -> object:
        return x

class Dog(Animal):
    def process(self, x: int) -> object:
        return x * 2
"""

PARAM_TYPE_VIOLATION = """
class Animal:
    def process(self, x: int) -> object:
        return x

class Dog(Animal):
    def process(self, x: str) -> object:  # str is not a supertype of int
        return x
"""

PARAM_TYPE_PASS = """
class Animal:
    def process(self, x: bool) -> object:
        return x

class Dog(Animal):
    def process(self, x: int) -> object:  # int is supertype of bool — OK
        return x
"""

RETURN_TYPE_VIOLATION = """
class Base:
    def run(self) -> int:
        return 42

class Broken(Base):
    def run(self) -> str:   # str is NOT a subtype of int
        return "oops"
"""

RETURN_TYPE_PASS = """
class Base:
    def get(self) -> object:
        return 1

class Child(Base):
    def get(self) -> int:   # int is subtype of object — covariance satisfied
        return 2
"""

NOT_IMPLEMENTED_VIOLATION = """
class Base:
    def run(self):
        print("running")

class Child(Base):
    def run(self):
        raise NotImplementedError()
"""

NOT_IMPLEMENTED_PASS = """
from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def run(self): pass

class Child(Base):
    def run(self):
        print("running")  # concrete implementation — no violation
"""

REMOVES_RETURN_VIOLATION = """
class Base:
    def compute(self) -> int:
        return 42

class Child(Base):
    def compute(self):
        print("computing")   # never returns a value
"""

REMOVES_RETURN_PASS = """
class Base:
    def compute(self) -> int:
        return 42

class Child(Base):
    def compute(self) -> int:
        return 99
"""

BINDING_TYPE_VIOLATION = """
class A:
    @classmethod
    def test(cls):
        pass

class B(A):
    def test(self):   # drops classmethod
        pass
"""

BINDING_TYPE_PASS = """
class A:
    @classmethod
    def test(cls):
        pass

class B(A):
    @classmethod
    def test(cls):
        pass
"""

KWONLY_VIOLATION = """
class Base:
    def run(self, *, verbose=False): pass

class Child(Base):
    def run(self, *, debug=False): pass  # renamed kwonly param
"""

KWONLY_PASS = """
class Base:
    def run(self, *, verbose=False): pass

class Child(Base):
    def run(self, *, verbose=False): pass
"""

REMOVES_DEFAULT_VIOLATION = """
class Base:
    def connect(self, host, port=8080): pass

class Child(Base):
    def connect(self, host, port): pass  # removes default
"""

REMOVES_DEFAULT_PASS = """
class Base:
    def connect(self, host, port=8080): pass

class Child(Base):
    def connect(self, host, port=9090): pass  # changes default value — OK
"""

FORWARD_DECLARED_VIOLATION = """
class EarlyChild(LateParent):
    def greet(self, name: int) -> str:
        return str(name)

class LateParent:
    def greet(self, name: str) -> str:
        return name
"""

FORWARD_DECLARED_PASS = """
class LateParent:
    def greet(self, name: str) -> str:
        return name

class EarlyChild(LateParent):
    def greet(self, name: str) -> str:
        return name.upper()
"""

NEW_EXCEPTION_VIOLATION = """
class Base:
    def load(self, path):
        return open(path).read()

class Child(Base):
    def load(self, path):
        if not path:
            raise FileNotFoundError()
        return open(path).read()
"""

NEW_EXCEPTION_PASS = """
class Base:
    def load(self, path):
        raise FileNotFoundError()

class Child(Base):
    def load(self, path):
        # does real work, raises the same exception the parent does
        data = open(path).read()
        if not data:
            raise FileNotFoundError()
        return data
"""

ALWAYS_RAISES_VIOLATION = """
class Base:
    def save(self, data):
        self.db.write(data)

class Child(Base):
    def save(self, data):
        raise RuntimeError("not supported")
"""

ALWAYS_RAISES_PASS = """
class Base:
    def save(self, data):
        self.db.write(data)

class Child(Base):
    def save(self, data):
        self.cache.write(data)
"""

ASSERT_PRECONDITION_VIOLATION = """
class Base:
    def process(self, value):
        return value * 2

class Child(Base):
    def process(self, value):
        assert value > 0, "must be positive"
        return value * 2
"""

ASSERT_PRECONDITION_PASS = """
class Base:
    def process(self, value):
        assert value > 0
        return value * 2

class Child(Base):
    def process(self, value):
        return value * 2
"""

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    examples = [
        # violations
        ("Param count      VIOLATION — extra positional arg      (BadDog)",      PARAM_COUNT_VIOLATION,      "Violation"),
        ("Param type       VIOLATION — contravariance broken      (Dog/str→int)", PARAM_TYPE_VIOLATION,       "Violation"),
        ("Return type      VIOLATION — non-subtype return         (Broken)",      RETURN_TYPE_VIOLATION,      "Violation"),
        ("NotImplemented   VIOLATION — overrides concrete method  (Child)",       NOT_IMPLEMENTED_VIOLATION,  "Violation"),
        ("Removes return   VIOLATION — drops non-None return      (Child)",       REMOVES_RETURN_VIOLATION,   "Violation"),
        ("Binding type     VIOLATION — drops classmethod          (B)",           BINDING_TYPE_VIOLATION,     "Violation"),
        ("Kwonly params    VIOLATION — renames keyword-only param (Child)",       KWONLY_VIOLATION,           "Violation"),
        ("Removes default  VIOLATION — removes parameter default  (Child)",       REMOVES_DEFAULT_VIOLATION,  "Violation"),
        ("Forward declared VIOLATION — child before parent        (EarlyChild)",  FORWARD_DECLARED_VIOLATION, "Violation"),
        ("New exception    VIOLATION — introduces new exception   (Child)",       NEW_EXCEPTION_VIOLATION,    "Violation"),
        ("Always raises    VIOLATION — removes all parent behavior(Child)",       ALWAYS_RAISES_VIOLATION,    "Violation"),
        ("Assert precon.   VIOLATION — strengthens precondition   (Child)",       ASSERT_PRECONDITION_VIOLATION, "Violation"),
        # passes
        ("Param count      PASS      — same signature             (Dog)",         PARAM_COUNT_PASS,           "Pass"),
        ("Param type       PASS      — bool→int contravariance OK (Dog)",         PARAM_TYPE_PASS,            "Pass"),
        ("Return type      PASS      — int subtype of object      (Child)",       RETURN_TYPE_PASS,           "Pass"),
        ("NotImplemented   PASS      — parent is abstract         (Child)",       NOT_IMPLEMENTED_PASS,       "Pass"),
        ("Removes return   PASS      — child still returns        (Child)",       REMOVES_RETURN_PASS,        "Pass"),
        ("Binding type     PASS      — both classmethod           (B)",           BINDING_TYPE_PASS,          "Pass"),
        ("Kwonly params    PASS      — same kwonly params         (Child)",       KWONLY_PASS,                "Pass"),
        ("Removes default  PASS      — changes value, keeps param (Child)",       REMOVES_DEFAULT_PASS,       "Pass"),
        ("Forward declared PASS      — child after parent         (EarlyChild)",  FORWARD_DECLARED_PASS,      "Pass"),
        ("New exception    PASS      — same exception as parent   (Child)",       NEW_EXCEPTION_PASS,         "Pass"),
        ("Always raises    PASS      — child provides behavior    (Child)",       ALWAYS_RAISES_PASS,         "Pass"),
        ("Assert precon.   PASS      — child relaxes, not tightens(Child)",       ASSERT_PRECONDITION_PASS,   "Pass"),
    ]

    passed = failed = 0
    failures = []

    for title, code, expected in examples:
        report = get_lsp_report(code)
        got = report["status"]
        ok = (got == expected)
        symbol = "✓" if ok else "✗"
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((title, expected, got, report))

        print(f"\n{'═' * 74}")
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<12}  Got: {got}")
        print("═" * 74)
        if report["violations"]:
            for v in report["violations"]:
                print(f"  [{v['severity']}] line {v['line']} — {v['message']}")
        else:
            print(f"  {report.get('reason', 'No violations found.')}")

    print(f"\n{'═' * 74}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(examples)} examples")
    if failures:
        print("\n  FAILURES:")
        for title, exp, got, report in failures:
            print(f"    ✗ {title}")
            print(f"      Expected {exp}, got {got}")
            if report["violations"]:
                for v in report["violations"]:
                    print(f"        [{v['severity']}] {v['message']}")