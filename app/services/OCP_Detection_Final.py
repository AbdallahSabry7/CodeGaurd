"""Open/Closed Principle (OCP) type-dispatch detector.

Corrected version. Notable fixes vs. the original are marked with `# FIX:`.
"""

import ast
from typing import Optional

BUILTIN_TYPES = {
    "int", "str", "float", "list", "dict", "bool", "set", "tuple",
    "bytes", "bytearray", "complex", "frozenset", "memoryview",
    "object", "type", "None", "NoneType",
}

# Variable names that strongly suggest type-dispatching
TYPE_DISPATCH_NAMES = {
    "type", "kind", "action", "method", "mode", "variant",
    "category", "strategy", "op", "operation", "cmd", "command",
    "role", "shape", "tag", "event_type", "msg_type", "request_type",
    "format", "protocol", "handler", "dispatch", "subtype", "msg_kind", "cls",
}

# Attribute access patterns that suggest type-dispatch
TYPE_DISPATCH_ATTRS = {
    "type", "kind", "action", "category", "variant", "op", "operation",
    "tag", "name", "__class__", "__name__", "mode", "format", "role",
    "status", "state", "subtype", "method", "protocol",
}

# Patterns that are clearly NOT OCP violations (safe isinstance uses)
_SAFE_EXCEPTION_TYPES = {
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "RuntimeError", "OSError", "IOError",
    "FileNotFoundError", "PermissionError", "StopIteration", "GeneratorExit",
    "SystemExit", "NotImplementedError", "OverflowError", "ZeroDivisionError",
    "UnicodeError", "UnicodeDecodeError", "UnicodeEncodeError",
    "ImportError", "ModuleNotFoundError", "NameError", "RecursionError",
}

# Broad prefixes used only as a *hint* for the find_by / search_by heuristic.
DISPATCH_PREFIXES = {
    "pay", "process", "parse", "handle", "export", "import",
    "generate", "calculate", "render", "validate", "format",
    "convert", "find", "search", "filter",
}

# Tight, intentional set for true type-routing method detection.
_ROUTING_PREFIXES = {"pay", "parse", "export", "import", "render", "convert", "serialize"}


def _attr_chain(node: ast.expr) -> str:
    """Flatten an Attribute/Name access chain into a dotted string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{_attr_chain(node.func)}(...)"
    return ""


def _unwrap_not(test: ast.expr) -> ast.expr:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return test.operand
    return test


def _is_exception_isinstance(node: ast.If) -> bool:
    """True only if EVERY type arg is a known builtin/exception Name.

    FIX: previously an empty `names` list (e.g. an attribute type like
    `exceptions.MyError`, or a tuple containing non-Name elements) made
    `all([])` return True, wrongly classifying real dispatch as "safe".
    """
    test = _unwrap_not(node.test)
    if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"):
        return False
    if len(test.args) < 2:
        return False
    type_arg = test.args[1]

    def _safe_name(n: ast.expr) -> bool:
        return isinstance(n, ast.Name) and (n.id in _SAFE_EXCEPTION_TYPES or n.id in BUILTIN_TYPES)

    if isinstance(type_arg, ast.Tuple):
        return len(type_arg.elts) > 0 and all(_safe_name(e) for e in type_arg.elts)
    return _safe_name(type_arg)


def _extract_compare_names(node: ast.Compare) -> list:
    """Return all Name/Attribute ids referenced in a comparison (lowercased)."""
    parts = [node.left] + list(node.comparators)
    result = []
    for p in parts:
        if isinstance(p, ast.Name):
            result.append(p.id.lower())
        elif isinstance(p, ast.Attribute):
            result.append(p.attr.lower())
    return result


class OCPDetector(ast.NodeVisitor):
    def __init__(self):
        self.violations: list = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None
        # Stack of per-scope tracked type-carrying variable names.
        self._type_var_scopes: list = [set()]
        # FIX: remember which If nodes are part of an already-counted elif
        # chain so we don't re-report the same chain at every level.
        self._counted_elif: set = set()

    @property
    def _type_vars(self) -> set:
        """Type variables for the *current* (innermost) scope."""
        return self._type_var_scopes[-1]

    def _is_type_var(self, name: str) -> bool:
        """FIX: look through the whole scope stack, not just the top frame,
        so module-level tracked vars are visible inside nested functions."""
        return any(name in frame for frame in self._type_var_scopes)

    def _report(self, node: ast.AST, v_type: str, severity: str, detail: str = ""):
        self.violations.append({
            "class": self.current_class,
            "function": self.current_function,
            "line": getattr(node, "lineno", None),
            "type": v_type,
            "severity": severity,
            "detail": detail,
        })

    # ---- individual pattern checks ------------------------------------ #
    def _check_enum_dispatch(self, node: ast.If) -> bool:
        """if kind == Status.RUNNING:  (now actually wired into visit_If)."""
        test = _unwrap_not(node.test)
        if not isinstance(test, ast.Compare):
            return False
        parts = [test.left] + list(test.comparators)
        has_enum_like = False
        has_dispatch_var = False
        for part in parts:
            if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name):
                if part.value.id and part.value.id[0].isupper() and part.value.id not in BUILTIN_TYPES:
                    has_enum_like = True
            elif isinstance(part, ast.Name) and (part.id in TYPE_DISPATCH_NAMES or self._is_type_var(part.id.lower())):
                has_dispatch_var = True
        if has_enum_like and has_dispatch_var:
            self._report(node, "Enum Dispatch", "medium",
                         "Branching on an Enum/Class constant. Consider the State or Strategy pattern.")
            return True
        return False

    def _check_name_type_dispatch(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        # FIX: only OR-chains represent a dispatch table in disguise; an AND
        # conjunct that happens to mention a kind var is incidental.
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            for val in test.values:
                if isinstance(val, ast.Compare):
                    names = _extract_compare_names(val)
                    if any(n in TYPE_DISPATCH_NAMES or self._is_type_var(n) for n in names):
                        self._report(node, "IF Name Dispatch (BoolOp)", "high",
                                     "Boolean chain of type-name comparisons \u2014 type-based dispatch")
                        return True
        if not isinstance(test, ast.Compare):
            return False
        names = _extract_compare_names(test)
        hit = next((n for n in names if n in TYPE_DISPATCH_NAMES), None)
        if hit is not None:
            self._report(node, "IF Name Dispatch", "high",
                         f"Condition branches on '{hit}' \u2014 suggests type-based dispatch")
            return True
        tracked = next((n for n in names if self._is_type_var(n)), None)
        if tracked is not None:
            self._report(node, "IF Tracked-Type Var Dispatch", "high",
                         f"Branches on variable that carries type/kind info: {tracked!r}")
            return True
        return False

    def _check_isinstance_dispatch(self, node: ast.If) -> bool:
        if _is_exception_isinstance(node):
            return False
        test = _unwrap_not(node.test)
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance"):
            return False
        if len(test.args) < 2:
            return False
        type_arg = test.args[1]
        if isinstance(type_arg, ast.Tuple):
            types = [elt for elt in type_arg.elts if isinstance(elt, ast.Name)]
            non_builtin = [t.id for t in types
                           if t.id not in BUILTIN_TYPES and t.id not in _SAFE_EXCEPTION_TYPES]
        elif isinstance(type_arg, ast.Name):
            non_builtin = ([] if type_arg.id in BUILTIN_TYPES or type_arg.id in _SAFE_EXCEPTION_TYPES
                           else [type_arg.id])
        elif isinstance(type_arg, ast.Attribute):
            # FIX: attribute type args (e.g. mod.MyClass) are concrete types too.
            non_builtin = [_attr_chain(type_arg)]
        else:
            non_builtin = []
        if non_builtin:
            self._report(node, "isinstance Dispatch", "high",
                         f"Dispatches on concrete type(s): {', '.join(non_builtin)}")
            return True
        return False

    def _check_type_call_comparison(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if not isinstance(test, ast.Compare):
            return False
        parts = [test.left] + list(test.comparators)
        for part in parts:
            chain = _attr_chain(part)
            if ".__class__" in chain or ".__name__" in chain:
                self._report(node, "type() / __class__ Dispatch", "high",
                             "Compares __class__/__name__ \u2014 hard-coded type check")
                return True
            if (isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                    and part.func.id == "type"):
                self._report(node, "type() Dispatch", "high",
                             "Uses type() comparison for branching")
                return True
        return False

    def _check_hasattr_dispatch(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "hasattr"):
            self._report(node, "hasattr Dispatch", "medium",
                         "Uses hasattr() to branch on capability \u2014 consider a protocol/ABC")
            return True
        return False

    def _check_getattr_dispatch(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if not isinstance(test, ast.Compare):
            return False
        # FIX: check every operand, not just `.left`, so
        # `"foo" == getattr(x, "type")` is also caught.
        for part in [test.left] + list(test.comparators):
            if (isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                    and part.func.id == "getattr"):
                args = part.args
                if len(args) >= 2 and isinstance(args[1], ast.Constant):
                    attr_name = str(args[1].value).lower()
                    if attr_name in TYPE_DISPATCH_ATTRS:
                        self._report(node, "getattr Dispatch", "medium",
                                     f"Uses getattr() on '{attr_name}' for branching")
                        return True
        return False

    def _check_callable_dispatch(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "callable"):
            self._report(node, "callable() Dispatch", "medium",
                         "Uses callable() to branch on capability \u2014 consider a protocol or ABC")
            return True
        return False

    def _check_issubclass_dispatch(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "issubclass"):
            return False
        if len(test.args) < 2:
            return False
        type_arg = test.args[1]
        if isinstance(type_arg, ast.Tuple):
            names = [e.id for e in type_arg.elts if isinstance(e, ast.Name)]
        elif isinstance(type_arg, ast.Name):
            names = [type_arg.id]
        elif isinstance(type_arg, ast.Attribute):
            names = [_attr_chain(type_arg)]
        else:
            names = []
        non_builtin = [n for n in names if n not in BUILTIN_TYPES]
        if non_builtin:
            self._report(node, "issubclass Dispatch", "high",
                         f"issubclass() dispatch on {', '.join(non_builtin)} \u2014 prefer ABCs / registration")
            return True
        return False

    def _check_string_startswith_type(self, node: ast.If) -> bool:
        test = _unwrap_not(node.test)
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
                and test.func.attr in ("startswith", "endswith")):
            return False
        chain = _attr_chain(test.func.value)
        last_attr = chain.split(".")[-1].lower() if "." in chain else chain.lower()
        if last_attr in TYPE_DISPATCH_ATTRS:
            self._report(node, "startswith/endswith Type Dispatch", "medium",
                         f"Partial-string dispatch on '{last_attr}' via {test.func.attr}()")
            return True
        return False

    def _check_elif_chain(self, node: ast.If) -> int:
        """Count elif depth below this If."""
        depth = 0
        current = node
        while current.orelse and len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            depth += 1
            current = current.orelse[0]
        return depth

    def _mark_chain_counted(self, node: ast.If) -> None:
        """Mark every elif-If in the chain so it isn't re-counted as a head."""
        current = node
        while current.orelse and len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            self._counted_elif.add(id(current))

    def _check_property_inspection(self, node: ast.If) -> bool:
        """Tell, Don't Ask: if obj.properties['color'] == 'red':"""
        test = _unwrap_not(node.test)
        if not isinstance(test, ast.Compare):
            return False
        for part in [test.left] + list(test.comparators):
            if isinstance(part, ast.Subscript) and isinstance(part.value, ast.Attribute):
                attr_name = part.value.attr.lower()
                if attr_name in {"properties", "data", "attributes", "config", "meta", "info"}:
                    self._report(node, "Property Inspection (Tell, Don't Ask)", "high",
                                 f"Inspecting '{part.value.attr}' externally to make decisions. "
                                 "Push this logic inside the class as a method.")
                    return True
        return False

    def _check_hardcoded_filtering(self, node: ast.FunctionDef) -> None:
        """Missing-Specification smell inside find/search/filter functions."""
        name_lower = node.name.lower()
        if not any(name_lower.startswith(prefix) for prefix in ("find", "search", "filter")):
            return
        # FIX: don't descend into nested functions \u2014 their BoolOps belong to them.
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
                continue
            if isinstance(child, ast.BoolOp):
                attribute_checks = 0
                for value in child.values:
                    if isinstance(value, ast.Compare):
                        for comp_part in [value.left] + value.comparators:
                            if "." in _attr_chain(comp_part):
                                attribute_checks += 1
                if attribute_checks >= 2:
                    self._report(node, "Hardcoded Filtering (Missing Specification)", "medium",
                                 f"Method '{node.name}' hardcodes attribute filtering. "
                                 "Consider the Specification pattern instead.")
                    return

    def _check_method_routing(self, node: ast.ClassDef) -> bool:
        """Type-routing disguised as methods (pay_credit/pay_debit) sharing an
        identical signature. Tight prefix set + signature match keeps valid
        business actions (process_payment/process_refund) from being flagged."""
        method_signatures: dict = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                is_abstract = any(
                    (isinstance(dec, ast.Name) and dec.id == "abstractmethod")
                    or (isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod")
                    for dec in item.decorator_list
                )
                if is_abstract:
                    continue
                parts = item.name.split("_")
                if len(parts) > 1 and parts[0].lower() in _ROUTING_PREFIXES:
                    args = tuple(arg.arg for arg in item.args.args)
                    method_signatures.setdefault((parts[0].lower(), args), []).append(item.name)
        flagged = False
        for (prefix, _args), names in method_signatures.items():
            if len(names) >= 2:
                self._report(node, "Method Name Routing", "high",
                             f"Class '{node.name}' has type-specific methods with identical signatures "
                             f"({', '.join(names[:2])}...). Use the Strategy pattern instead.")
                flagged = True
        return flagged

    def _check_find_by_routing(self, node: ast.ClassDef) -> None:
        """find_by_x / search_by_y proliferation \u2014 a softer (medium) smell."""
        buckets: dict = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                parts = item.name.split("_")
                if len(parts) >= 3 and parts[1] == "by":
                    buckets.setdefault(f"{parts[0].lower()}_by", []).append(item.name)
        for prefix, names in buckets.items():
            if len(names) >= 2:
                self._report(node, "Method Name Routing (find_by)", "medium",
                             f"Class '{node.name}' has repeated '{prefix}_*' lookups "
                             f"({', '.join(names[:3])}...). Consider the Specification pattern.")

    # ---- assignment tracking ------------------------------------------ #
    def _track_type_assignment(self, node: ast.Assign) -> None:
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            varname = target.id.lower()
            val = node.value
            if isinstance(val, ast.Attribute) and val.attr.lower() in TYPE_DISPATCH_ATTRS:
                self._type_vars.add(varname)
            elif isinstance(val, ast.Subscript):
                sl = val.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value.lower() in TYPE_DISPATCH_ATTRS:
                    self._type_vars.add(varname)
            elif (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                  and val.func.id == "getattr" and len(val.args) >= 2
                  and isinstance(val.args[1], ast.Constant)
                  and str(val.args[1].value).lower() in TYPE_DISPATCH_ATTRS):
                self._type_vars.add(varname)
            elif varname in TYPE_DISPATCH_NAMES:
                self._type_vars.add(varname)

    # ---- visitors ------------------------------------------------------ #
    def visit_FunctionDef(self, node):
        prev_fn = self.current_function
        self.current_function = node.name
        self._type_var_scopes.append(set())
        self._check_hardcoded_filtering(node)
        self.generic_visit(node)
        self._type_var_scopes.pop()
        self.current_function = prev_fn

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        self._track_type_assignment(node)
        if isinstance(node.value, ast.Dict) and node.value.keys:
            has_class_instantiation = any(
                isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                and v.func.id and v.func.id[0].isupper() and v.func.id not in BUILTIN_TYPES
                for v in node.value.values
            )
            if has_class_instantiation:
                for target in node.targets:
                    if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        self._report(node, "Hardcoded Registry", "medium",
                                     f"Hardcoded dict mapping to class instances in 'self.{target.attr}'. "
                                     "Use dependency injection or a registration method instead.")
                        break
        self.generic_visit(node)

    def visit_If(self, node):
        matched = (
            # FIX: run the more specific Enum/State check *before* the generic
            # name check, otherwise the high-severity name check always wins
            # and Enum Dispatch is unreachable.
            self._check_enum_dispatch(node)
            or self._check_name_type_dispatch(node)
            or self._check_isinstance_dispatch(node)
            or self._check_type_call_comparison(node)
            or self._check_hasattr_dispatch(node)
            or self._check_getattr_dispatch(node)
            or self._check_callable_dispatch(node)
            or self._check_issubclass_dispatch(node)
            or self._check_string_startswith_type(node)
            or self._check_property_inspection(node)
        )
        # FIX: only evaluate the elif-chain length once, at the head of the
        # chain. Nested elif Ifs are marked and skipped to avoid duplicates.
        if not matched and id(node) not in self._counted_elif:
            depth = self._check_elif_chain(node)
            if depth >= 2:
                severity = "high" if depth >= 4 else "medium"
                self._report(node, "Long elif Chain", severity,
                             f"elif chain of depth {depth} \u2014 consider a dispatch table or polymorphism")
            self._mark_chain_counted(node)
        self.generic_visit(node)

    def visit_Match(self, node):
        subject_name = ""
        if isinstance(node.subject, ast.Name):
            subject_name = node.subject.id.lower()
        elif isinstance(node.subject, ast.Attribute):
            subject_name = node.subject.attr.lower()
        non_wildcard = [c for c in node.cases if not isinstance(c.pattern, ast.MatchAs)]
        all_constants = bool(non_wildcard) and all(
            isinstance(c.pattern, ast.MatchValue) and isinstance(c.pattern.value, ast.Constant)
            for c in non_wildcard
        )
        has_class_pattern = any(isinstance(c.pattern, ast.MatchClass) for c in node.cases)
        if has_class_pattern:
            self._report(node, "MATCH-CASE Class Pattern Dispatch", "high",
                         "match-case with class patterns \u2014 use polymorphism or singledispatch")
            self.generic_visit(node)
            return
        is_type_subject = subject_name in TYPE_DISPATCH_NAMES or self._is_type_var(subject_name)
        if is_type_subject or not all_constants:
            severity = "high" if is_type_subject else "medium"
            self._report(node, "MATCH-CASE Dispatch", severity,
                         f"match-case on '{subject_name or '?'}'")
        elif all_constants and len(non_wildcard) >= 3:
            self._report(node, "MATCH-CASE Dispatch", "medium",
                         f"match-case with {len(non_wildcard)} constant arms \u2014 consider a dispatch table")
        self.generic_visit(node)

    def visit_Dict(self, node):
        if not node.keys:
            return
        class_name_keys = [
            k for k in node.keys
            if isinstance(k, ast.Name) and k.id and k.id[0].isupper() and k.id not in BUILTIN_TYPES
        ]
        if len(class_name_keys) >= 2:
            names = ", ".join(k.id for k in class_name_keys[:4])
            self._report(node, "Type Dispatch Dict", "medium",
                         f"Dict keyed on class names ({names}...) \u2014 possible type-dispatch table")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        sl = node.slice
        if isinstance(sl, ast.Call) and isinstance(sl.func, ast.Name) and sl.func.id == "type":
            self._report(node, "Dict Subscript type() Dispatch", "high",
                         "Dict indexed by type(obj) \u2014 replace with polymorphism or singledispatch")
        elif isinstance(sl, ast.Attribute) and sl.attr in TYPE_DISPATCH_ATTRS:
            val_chain = _attr_chain(node.value).lower()
            if any(k in val_chain for k in ("handler", "dispatch", "registry", "router",
                                            "factory", "map", "table", "lookup")):
                self._report(node, "Dict Subscript Attr Dispatch", "medium",
                             f"Dict indexed by .{sl.attr} attribute \u2014 consider polymorphism")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        prev_class = self.current_class
        self.current_class = node.name
        self._type_var_scopes.append(set())
        # FIX: use the signature-aware routing check + a separate find_by check,
        # instead of the broad name-prefix logic that flagged process_*/handle_*.
        self._check_method_routing(node)
        self._check_find_by_routing(node)
        self.generic_visit(node)
        self._type_var_scopes.pop()
        self.current_class = prev_class

    def visit_Module(self, node):
        # FIX: removed the pre-walk that tracked assignments from *inside*
        # functions into module scope (scope pollution + double processing).
        # Ordinary traversal tracks each assignment in its own scope.
        self.generic_visit(node)


def _suggestion_for(v_type: str) -> str:
    suggestions = {
        "IF Name Dispatch": "Replace if/elif chains with polymorphism or a strategy object.",
        "IF Name Dispatch (BoolOp)": "Boolean chains of type comparisons are a dispatch table in disguise \u2014 use a dict or polymorphism.",
        "IF Tracked-Type Var Dispatch": "Variable carries type/kind info; replace branching with polymorphism or a dispatch dict.",
        "Enum Dispatch": "Branching on an enum/class constant \u2014 consider the State or Strategy pattern.",
        "isinstance Dispatch": "Use polymorphism or functools.singledispatch instead of isinstance().",
        "issubclass Dispatch": "issubclass() dispatch belongs in a registry; use ABCs or singledispatch.",
        "type() Dispatch": "Avoid comparing type() directly; prefer polymorphism.",
        "type() / __class__ Dispatch": "Avoid __class__ comparisons; rely on polymorphism or ABCs.",
        "__class__.__name__ Dispatch": "String-based class-name checks are fragile; use isinstance() or polymorphism.",
        "hasattr Dispatch": "Define a shared interface/Protocol so callers don't inspect capabilities.",
        "callable() Dispatch": "Use a Protocol with __call__ rather than checking callability at runtime.",
        "getattr Dispatch": "Centralise type metadata in a base class rather than probing attributes.",
        "startswith/endswith Type Dispatch": "Partial-string type matching is brittle; use an enum or subclass hierarchy.",
        "Long elif Chain": "Long elif chains are hard to extend; replace with a dispatch table or polymorphic calls.",
        "MATCH-CASE Dispatch": "Match-case over types/roles violates OCP; prefer visitor pattern or singledispatch.",
        "MATCH-CASE Class Pattern Dispatch": "Class pattern match-case is explicit type dispatch; use the Visitor pattern or singledispatch.",
        "Type Dispatch Dict": "A class-keyed dict is a manual vtable; consider singledispatch or subclass registration.",
        "Dict Subscript type() Dispatch": "Indexing a dict by type(obj) is a dispatch table \u2014 use singledispatch or polymorphism.",
        "Dict Subscript Attr Dispatch": "Routing through a dict keyed on .type/.kind \u2014 consider polymorphism or a registry.",
        "Property Inspection (Tell, Don't Ask)": "Push the decision logic into the object as a method.",
        "Hardcoded Filtering (Missing Specification)": "Use the Specification pattern so new criteria don't require edits.",
        "Hardcoded Registry": "Use dependency injection or a registration method instead of a hardcoded map.",
        "Method Name Routing": "Use the Strategy pattern or polymorphism instead of type-specific methods.",
        "Method Name Routing (find_by)": "Use the Specification pattern instead of proliferating find_by_* methods.",
    }
    return suggestions.get(v_type, "Use polymorphism or a strategy pattern instead of type-based branching.")


def detect_ocp_violations_from_file(filename: str) -> list:
    with open(filename, "r", encoding="utf-8") as f:
        code = f.read()
    tree = ast.parse(code)
    detector = OCPDetector()
    detector.visit(tree)
    return detector.violations


def get_ocp_report(code_str: str) -> dict:
    """Single-violation summary plus a `violations` list of all issues."""
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return {"status": "Error", "reason": f"Syntax error: {e}", "violations": []}

    try:
        detector = OCPDetector()
        detector.visit(tree)
    except Exception as e:
        return {"status": "Error", "reason": f"Analyzer error: {type(e).__name__}: {e}", "violations": []}

    if not detector.violations:
        return {"status": "Pass", "reason": "No type-based dispatching detected.", "violations": []}

    high = [v for v in detector.violations if v["severity"] == "high"]
    top = high[0] if high else detector.violations[0]
    location = f"line {top['line']}"
    if top["class"]:
        location += f" in class {top['class']}"
    if top["function"]:
        location += f" / {top['function']}()"
    return {
        "status": "Violation",
        "reason": f"{location} [{top['type']}]: {top['detail']}",
        "suggestion": _suggestion_for(top["type"]),
        "violations": detector.violations,
    }
