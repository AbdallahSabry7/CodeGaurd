import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
    "must implement",
    "implement me",
}


def is_abstract_method(node: ast.FunctionDef) -> bool:
    # Decorator-based (most reliable signal — keep)
    if _decorator_names(node) & _ABSTRACT_DECORATORS:
        return True

    # Single-statement body patterns
    if len(node.body) == 1:
        stmt = node.body[0]
        if isinstance(stmt, ast.Pass):
            return True
        # FIX: only treat a docstring-only body as abstract when combined with
        # an explicit raise of NotImplementedError or an @abstract decorator,
        # NOT on its own.  A docstring alone is just documentation.
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

    # FIX: tighten docstring heuristic — require explicit "not implemented" /
    # "subclasses should implement" phrasing only (removed vague "abstract",
    # "override" which caused far too many false positives).
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
    annotations: dict[str, str]
    return_annotation: Optional[str]
    # NEW: track default values as unparsed strings so we can detect
    # changes in default *values* (not just count).
    default_values: list[str] = field(default_factory=list)
    # NEW: track all param annotations including kwonly
    kwonly_annotations: dict[str, str] = field(default_factory=dict)


def extract_signature(func: ast.FunctionDef) -> Signature:
    args = func.args
    is_static = _is_staticmethod(func)
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
        default_values=[src(d) for d in args.defaults],
        kwonly_annotations={
            a.arg: src(a.annotation)
            for a in args.kwonlyargs
            if a.annotation
        },
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
    s = type_str.strip()
    if s.startswith("Optional[") and s.endswith("]"):
        return True, s[9:-1].strip()
    if s.endswith("| None"):
        return True, s[:-6].strip()
    if s.startswith("None |"):
        return True, s[6:].strip()
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
        if child == parent:
            return True
        key = (child, parent)
        if key in self._cache:
            return self._cache[key]

        p_opt, p_inner = _unwrap_optional(parent)
        c_opt, c_inner = _unwrap_optional(child)
        if p_opt and not c_opt:
            result = self.is_subtype(child, p_inner)
        elif c_opt and not p_opt:
            result = False
        else:
            result = parent in self._all_parents(child)

        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# NEW: Helper to collect all raises in a function (non-recursive into nested
#      function/class defs, matching how callers see the method surface).
# ---------------------------------------------------------------------------

def _direct_raises(func: ast.FunctionDef) -> set[str]:
    """
    Walk the function body but do NOT descend into nested functions/classes,
    so we only see raises that the caller of *this* method will encounter.
    """
    raises: set[str] = set()
    _walk_no_nested(func, raises)
    return raises - {""}


def _walk_no_nested(node: ast.AST, out: set[str]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # don't descend into nested scopes
        if isinstance(child, ast.Raise):
            out.add(exc_name_from_raise(child))
        _walk_no_nested(child, out)


# ---------------------------------------------------------------------------
# NEW: Detect early-return guards anywhere in the method body
#      (not just the first statement like the original code).
# ---------------------------------------------------------------------------

def _has_early_return_guard(func: ast.FunctionDef, param_names: list[str]) -> bool:
    """
    Return True if there is ANY if-block in the function body (at the top
    level of the function, not inside loops/try blocks) whose test is a
    type/identity guard on a parameter AND whose body only returns or raises.
    This catches stricter-precondition guards beyond just the first line.
    """
    for stmt in func.body:
        if (
            isinstance(stmt, ast.If)
            and _is_type_guard(stmt.test, param_names)
            and all(isinstance(s, (ast.Return, ast.Raise)) for s in stmt.body)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# NEW: Detect whether a method calls super() for the same method name.
#      A concrete override that never calls super() may silently break the
#      parent contract (Liskov substitutability via behavioral composition).
# ---------------------------------------------------------------------------

def _calls_super(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            # super().method_name(...)
            if (
                isinstance(f, ast.Attribute)
                and f.attr == func.name
                and isinstance(f.value, ast.Call)
                and isinstance(f.value.func, ast.Name)
                and f.value.func.id == "super"
            ):
                return True
            # super().__init__() etc.
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Call)
                and isinstance(f.value.func, ast.Name)
                and f.value.func.id == "super"
            ):
                return True
    return False


# ---------------------------------------------------------------------------
# NEW: Parameter renaming detection.
#      Callers using positional args are fine, but callers using keyword args
#      will break if a positional parameter is renamed.
# ---------------------------------------------------------------------------

def _renamed_params(child_sig: "Signature", parent_sig: "Signature") -> list[tuple[str, str]]:
    """Return list of (parent_name, child_name) pairs that differ by position."""
    renames = []
    for i, (p, c) in enumerate(zip(parent_sig.positional, child_sig.positional)):
        if p != c:
            renames.append((p, c))
    return renames


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
        self._seen: set[tuple[int, str]] = set()


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


    def analyze(self) -> list[Violation]:
        checker = TypeChecker(self._inheritance)
        for cls_name, cls_node in self._classes.items():
            all_parents = self._all_parents(cls_name)
            child_methods = {
                m.name: m
                for m in cls_node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

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
                    if method_name in parent_methods:
                        self._compare(
                            child_method,
                            parent_methods[method_name],
                            cls_name,
                            parent_name,
                            checker,
                        )
        return self._violations

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

        if len(child_sig.positional) != len(parent_sig.positional):
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' overrides '{parent_cls}.{name}' "
                f"with a different positional parameter count "
                f"({len(child_sig.positional)} vs {len(parent_sig.positional)}).",
                Severity.HIGH,
            )

        if child_sig.kwonly != parent_sig.kwonly:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' changes keyword-only parameters "
                f"{parent_sig.kwonly!r} → {child_sig.kwonly!r}.",
            )

        for kw_param, p_type in parent_sig.kwonly_annotations.items():
            c_type = child_sig.kwonly_annotations.get(kw_param)
            if c_type and c_type != p_type:
                if not checker.is_subtype(p_type, c_type):
                    self._add(
                        child,
                        f"LSP: keyword-only parameter '{kw_param}' in "
                        f"'{child_cls}.{name}' violates contravariance — "
                        f"parent accepts '{p_type}' but child requires '{c_type}'.",
                        Severity.HIGH,
                    )

        if child_sig.n_defaults < parent_sig.n_defaults:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' removes default parameter values "
                f"that callers may rely on.",
            )

        if child_sig.n_defaults > 0 and parent_sig.n_defaults > 0:
            p_defs = parent_sig.default_values
            c_defs = child_sig.default_values
            # compare the shared trailing slice
            shared = min(len(p_defs), len(c_defs))
            for pd, cd in zip(p_defs[-shared:], c_defs[-shared:]):
                if pd != cd:
                    self._add(
                        child,
                        f"LSP: '{child_cls}.{name}' changes default parameter "
                        f"values ('{pd}' → '{cd}'), breaking callers that rely "
                        f"on the parent's defaults.",
                    )
                    break  

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

        # FIX NEW: positional parameter renaming breaks keyword callers.
        renames = _renamed_params(child_sig, parent_sig)
        for p_name, c_name in renames:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' renames parameter '{p_name}' → "
                f"'{c_name}', breaking callers that pass it as a keyword argument.",
            )

        # --- Parameter type annotations (contravariance) ---
        for param in parent_sig.annotations:
            p_type = parent_sig.annotations[param]
            c_type = child_sig.annotations.get(param)
            if p_type and c_type and c_type != p_type:
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

        # FIX NEW: parent has return annotation but child drops it entirely.
        # Dropping annotations is a soft signal — use LOW severity.
        if p_ret and not c_ret:
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' drops the return type annotation "
                f"'{p_ret}' from '{parent_cls}.{name}'. "
                f"Static checkers can no longer verify the contract.",
                Severity.LOW,
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
        # FIX: use _direct_raises instead of ast.walk to avoid false positives
        # from nested function/lambda exception handling.
        if not parent_abstract:
            parent_excs = _direct_raises(parent)
            child_excs  = _direct_raises(child)
            for exc in child_excs - parent_excs:
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' introduces new exception '{exc}' "
                    f"not raised by '{parent_cls}.{name}'.",
                )

        if parent_abstract:
            sibling_excs = self._sibling_exceptions(child_cls, name, child)
            own_excs = _direct_raises(child)
            for exc in own_excs - sibling_excs:
                if sibling_excs:  # only flag when we have a baseline
                    self._add(
                        child,
                        f"LSP: '{child_cls}.{name}' raises '{exc}' which is not "
                        f"raised by other concrete implementations of "
                        f"'{parent_cls}.{name}'.",
                        Severity.LOW,
                    )

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
                break

        if _has_early_return_guard(child, child_sig.positional):
            self._add(
                child,
                f"LSP: '{child_cls}.{name}' adds a type-guard check, "
                f"strengthening the parent's precondition.",
            )

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

        if not parent_abstract and not _calls_super(child):
            # Only flag non-trivial overrides (more than just a docstring or pass)
            non_trivial = any(
                not (
                    isinstance(s, ast.Expr)
                    and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str)
                )
                and not isinstance(s, ast.Pass)
                for s in child.body
            )
            if non_trivial and _calls_super(parent):
                self._add(
                    child,
                    f"LSP: '{child_cls}.{name}' overrides '{parent_cls}.{name}' "
                    f"without calling super(), dropping parent behavior.",
                    Severity.MEDIUM,
                )


    def _sibling_exceptions(
        self, cls_name: str, method_name: str, skip_node: ast.FunctionDef
    ) -> set[str]:
        """
        Return the union of exceptions raised by all OTHER concrete classes
        that also define `method_name` and share a common abstract parent.
        """
        result: set[str] = set()
        for other_cls, other_node in self._classes.items():
            if other_cls == cls_name:
                continue
            for item in other_node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                    and item is not skip_node
                    and not is_abstract_method(item)
                ):
                    result |= _direct_raises(item)
        return result


def _is_type_guard(test: ast.expr, param_names: list[str]) -> bool:
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
            # "suggestion": "Keep subclass behavior compatible with parent contracts.",
        }
    except SyntaxError as e:
        return {"status": "Error", "reason": f"Syntax error: {e}", "violations": []}
    except Exception as e:
        return {"status": "Error", "reason": str(e), "violations": []}