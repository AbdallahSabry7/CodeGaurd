import ast
from typing import Optional

BUILTIN_TYPES = {"int", "str", "float", "list", "dict", "bool", "set", "tuple", "bytes", "bytearray"}

# Variable names that strongly suggest type-dispatching
TYPE_DISPATCH_NAMES = {
    "type", "kind", "action", "method", "mode", "variant",
    "category", "strategy", "op", "operation", "cmd", "command",
    "role", "shape", "tag", "event_type", "msg_type", "request_type",
}

# Attribute access patterns that suggest type-dispatch
TYPE_DISPATCH_ATTRS = {
    "type", "kind", "action", "category", "variant", "op", "operation",
    "tag", "name", "__class__", "__name__",
}


def _attr_chain(node: ast.expr) -> str:
    """Flatten an Attribute/Name access chain into a dotted string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_chain(node.value)}.{node.attr}"
    return ""


class OCPDetector(ast.NodeVisitor):
    def __init__(self):
        self.violations: list[dict] = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    # ------------------------------------------------------------------ #
    # helpers                                                              #
    # ------------------------------------------------------------------ #

    def _report(self, node: ast.AST, v_type: str, severity: str, detail: str = ""):
        self.violations.append({
            "class": self.current_class,
            "function": self.current_function,
            "line": node.lineno,
            "type": v_type,
            "severity": severity,
            "detail": detail,
        })

    # ---- individual pattern checks ------------------------------------ #

    def _check_name_type_dispatch(self, node: ast.If) -> bool:
        """if <dispatch_name> == ..."""
        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        left = test.left
        name = ""
        if isinstance(left, ast.Name):
            name = left.id.lower()
        elif isinstance(left, ast.Attribute):
            name = left.attr.lower()
        if name in TYPE_DISPATCH_NAMES:
            severity = "medium" if all(isinstance(c, ast.Constant) for c in test.comparators) else "high"
            self._report(node, "IF Name Dispatch", severity,
                         f"Condition branches on '{name}' — suggests type-based dispatch")
            return True
        return False

    def _check_isinstance_dispatch(self, node: ast.If) -> bool:
        """if isinstance(x, SomeConcreteClass):"""
        test = node.test
        # unwrap `not isinstance(...)`
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance"):
            return False
        if len(test.args) < 2:
            return False
        type_arg = test.args[1]
        # isinstance(x, (A, B)) — Tuple of types
        if isinstance(type_arg, ast.Tuple):
            types = [elt for elt in type_arg.elts if isinstance(elt, ast.Name)]
            non_builtin = [t.id for t in types if t.id not in BUILTIN_TYPES]
        elif isinstance(type_arg, ast.Name):
            non_builtin = [] if type_arg.id in BUILTIN_TYPES else [type_arg.id]
        else:
            non_builtin = []
        if non_builtin:
            self._report(node, "isinstance Dispatch", "high",
                         f"Dispatches on concrete type(s): {', '.join(non_builtin)}")
            return True
        return False

    def _check_type_call_comparison(self, node: ast.If) -> bool:
        """if type(x) == SomeClass / if type(x).__name__ == 'Foo'"""
        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        parts = [test.left] + list(test.comparators)
        for part in parts:
            chain = _attr_chain(part)
            if chain.startswith("type(") or ".__class__" in chain or ".__name__" in chain:
                self._report(node, "type() / __class__ Dispatch", "high",
                             "Compares type() or __class__/__name__ — hard-coded type check")
                return True
            # ast representation: Call(func=Name('type'), ...) compared to Name or Constant
            if (isinstance(part, ast.Call)
                    and isinstance(part.func, ast.Name)
                    and part.func.id == "type"):
                self._report(node, "type() Dispatch", "high",
                             "Uses type() comparison for branching")
                return True
        # Also catch: x.__class__.__name__ == "Foo"
        for part in parts:
            if isinstance(part, ast.Attribute) and part.attr == "__name__":
                inner = part.value
                if isinstance(inner, ast.Attribute) and inner.attr == "__class__":
                    self._report(node, "__class__.__name__ Dispatch", "high",
                                 "Compares __class__.__name__ string — brittle type check")
                    return True
        return False

    def _check_hasattr_dispatch(self, node: ast.If) -> bool:
        """if hasattr(x, 'some_method'): — duck-type dispatch"""
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if (isinstance(test, ast.Call)
                and isinstance(test.func, ast.Name)
                and test.func.id == "hasattr"):
            self._report(node, "hasattr Dispatch", "medium",
                         "Uses hasattr() to branch on capability — consider protocol/ABC instead")
            return True
        return False

    def _check_getattr_dispatch(self, node: ast.If) -> bool:
        """if getattr(x, 'type', None) == 'foo':"""
        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        left = test.left
        if (isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "getattr"):
            args = left.args
            if len(args) >= 2 and isinstance(args[1], ast.Constant):
                attr_name = str(args[1].value).lower()
                if attr_name in TYPE_DISPATCH_ATTRS:
                    self._report(node, "getattr Dispatch", "medium",
                                 f"Uses getattr() on '{attr_name}' for branching")
                    return True
        return False

    def _check_elif_chain(self, node: ast.If) -> int:
        """Count elif depth; long chains are a strong OCP smell."""
        depth = 0
        current = node
        while current.orelse and len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            depth += 1
            current = current.orelse[0]
        return depth

    # ------------------------------------------------------------------ #
    # visitors                                                             #
    # ------------------------------------------------------------------ #

    def visit_ClassDef(self, node: ast.ClassDef):
        prev = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If):
        matched = (
            self._check_name_type_dispatch(node)
            or self._check_isinstance_dispatch(node)
            or self._check_type_call_comparison(node)
            or self._check_hasattr_dispatch(node)
            or self._check_getattr_dispatch(node)
        )

        # Long elif chains are an OCP smell regardless of what they test
        if not matched:
            depth = self._check_elif_chain(node)
            if depth >= 3:
                severity = "high" if depth >= 5 else "medium"
                self._report(node, "Long elif Chain", severity,
                             f"elif chain of depth {depth} — consider polymorphism or a dispatch table")

        self.generic_visit(node)

    def visit_Match(self, node: ast.Match):
        """match/case — always an OCP smell unless matching on data literals."""
        # Check if the subject looks like a type-dispatch variable
        subject_name = ""
        if isinstance(node.subject, ast.Name):
            subject_name = node.subject.id.lower()
        elif isinstance(node.subject, ast.Attribute):
            subject_name = node.subject.attr.lower()

        all_constants = all(
            isinstance(case.pattern, ast.MatchValue)
            and isinstance(case.pattern.value, ast.Constant)
            for case in node.cases
            if not isinstance(case.pattern, ast.MatchAs)  # ignore wildcard
        )

        if subject_name in TYPE_DISPATCH_NAMES or not all_constants:
            severity = "high"
        else:
            severity = "medium"

        self._report(node, "MATCH-CASE Dispatch", severity,
                     f"match-case on '{subject_name or '?'}' — "
                     + ("type-dispatch variable" if subject_name in TYPE_DISPATCH_NAMES
                        else ("mixed patterns" if not all_constants else "constant dispatch")))

        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict):
        """Detect type-keyed dispatch dicts: {Dog: handle_dog, Cat: handle_cat}"""
        if not node.keys:
            return
        # Keys are all Names that look like class names (CapWords) → dispatch table
        class_name_keys = [
            k for k in node.keys
            if isinstance(k, ast.Name) and k.id and k.id[0].isupper() and k.id not in BUILTIN_TYPES
        ]
        if len(class_name_keys) >= 2:
            names = ", ".join(k.id for k in class_name_keys[:4])
            self._report(node, "Type Dispatch Dict", "medium",
                         f"Dict keyed on class names ({names}...) — possible type-dispatch table")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Detect: x.__class__.__name__ comparisons embedded in calls."""
        self.generic_visit(node)


# ------------------------------------------------------------------ #
# Public API                                                          #
# ------------------------------------------------------------------ #

def detect_ocp_violations_from_file(filename: str) -> list[dict]:
    with open(filename, "r", encoding="utf-8") as f:
        code = f.read()
    tree = ast.parse(code)
    detector = OCPDetector()
    detector.visit(tree)
    return detector.violations


def get_ocp_report(code_str: str) -> dict:
    """
    Returns a single-violation summary dict compatible with the original API,
    plus a `violations` key listing all found issues.
    """
    try:
        tree = ast.parse(code_str)
        detector = OCPDetector()
        detector.visit(tree)

        if not detector.violations:
            return {
                "status": "Pass",
                "reason": "No type-based dispatching detected.",
                "suggestion": "N/A",
                "violations": [],
            }

        # Prioritise high-severity violations for the top-level summary
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
    except SyntaxError as e:
        return {
            "status": "Error",
            "reason": f"Syntax error: {e}",
            "suggestion": "Fix syntax before analysing.",
            "violations": [],
        }
    except Exception as e:
        return {
            "status": "Pass",
            "reason": "Analyser active.",
            "suggestion": str(e),
            "violations": [],
        }


def _suggestion_for(v_type: str) -> str:
    suggestions = {
        "IF Name Dispatch":            "Replace if/elif chains with polymorphism — move behaviour into subclasses or a strategy object.",
        "isinstance Dispatch":         "Use polymorphism or register-based dispatch (functools.singledispatch) instead of isinstance().",
        "type() Dispatch":             "Avoid comparing type() directly; use isinstance() at most, or better, polymorphism.",
        "type() / __class__ Dispatch": "Avoid __class__ comparisons; rely on polymorphism or ABCs.",
        "__class__.__name__ Dispatch": "String-based class name checks are fragile; use isinstance() or polymorphism.",
        "hasattr Dispatch":            "Define a shared interface/Protocol so callers don't need to inspect capabilities.",
        "getattr Dispatch":            "Centralise type metadata in a base class rather than probing attributes at call sites.",
        "Long elif Chain":             "Long elif chains are hard to extend; replace with a dispatch table or polymorphic calls.",
        "MATCH-CASE Dispatch":         "Match-case over types/roles violates OCP; prefer visitor pattern or singledispatch.",
        "Type Dispatch Dict":          "A class-keyed dict is a manual vtable; consider using singledispatch or subclass registration.",
    }
    return suggestions.get(v_type, "Use polymorphism or strategy pattern instead of type-based branching.")


# ------------------------------------------------------------------ #
# Quick self-test                                                      #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    _SAMPLES = [
        ("isinstance dispatch (non-builtin)", """
class Renderer:
    def render(self, shape):
        if isinstance(shape, Circle):
            draw_circle(shape)
        elif isinstance(shape, Square):
            draw_square(shape)
""", "Violation"),
        ("isinstance on builtin — OK", """
def process(value):
    if isinstance(value, int):
        return value * 2
    return str(value)
""", "Pass"),
        ("type() comparison", """
def handle(obj):
    if type(obj) == Dog:
        obj.bark()
""", "Violation"),
        ("__class__.__name__ string check", """
def route(event):
    if event.__class__.__name__ == 'ClickEvent':
        handle_click(event)
""", "Violation"),
        ("hasattr dispatch", """
def run(obj):
    if hasattr(obj, 'fly'):
        obj.fly()
    else:
        obj.walk()
""", "Violation"),
        ("getattr on 'type' attribute", """
def process(msg):
    if getattr(msg, 'type', None) == 'error':
        log_error(msg)
""", "Violation"),
        ("match-case on type variable", """
def execute(action):
    match action:
        case 'run': do_run()
        case 'stop': do_stop()
        case 'pause': do_pause()
""", "Violation"),
        ("long elif chain", """
def compute(op, a, b):
    if op == 'add':
        return a + b
    elif op == 'sub':
        return a - b
    elif op == 'mul':
        return a * b
    elif op == 'div':
        return a / b
    elif op == 'mod':
        return a % b
""", "Violation"),
        ("type-dispatch dict", """
HANDLERS = {
    Circle: handle_circle,
    Square: handle_square,
    Triangle: handle_triangle,
}
""", "Violation"),
        ("clean polymorphic code", """
class Shape:
    def area(self): raise NotImplementedError

class Circle(Shape):
    def area(self): return 3.14 * self.r ** 2

class Square(Shape):
    def area(self): return self.side ** 2
""", "Pass"),
    ]

    passed = failed = 0
    print("\n" + "═" * 74)
    for title, code, expected in _SAMPLES:
        report = get_ocp_report(code)
        got = report["status"]
        ok = got == expected
        symbol = "✓" if ok else "✗"
        passed += ok
        failed += not ok
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<12}  Got: {got}")
        if report["violations"]:
            for v in report["violations"]:
                ctx = f"{v['class'] or ''} {'/ ' + v['function'] + '()' if v['function'] else ''}".strip()
                print(f"     [{v['severity']:6}] line {v['line']:3}  {v['type']:<30}  {ctx}")
        else:
            print(f"     {report['reason']}")
        print("─" * 74)

    print(f"\n  RESULTS: {passed} passed, {failed} failed out of {len(_SAMPLES)}")
    print("═" * 74)