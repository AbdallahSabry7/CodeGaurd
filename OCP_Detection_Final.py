import ast

BUILTIN_TYPES = {"int", "str", "float", "list", "dict", "bool", "set", "tuple"}

class OCPDetector(ast.NodeVisitor):
    def __init__(self):
        self.violations = []
        self.current_class = None

    def is_type_comparison(self, node):
        if isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and left.id.lower() in ["type", "kind", "action", "method"]:
                return True
        return False

    def is_isinstance_dispatch(self, node):
        if isinstance(node.test, ast.Call):
            func = node.test.func
            if isinstance(func, ast.Name) and func.id == "isinstance":
                type_arg = node.test.args[1] if len(node.test.args) > 1 else None
                if isinstance(type_arg, ast.Name) and type_arg.id in BUILTIN_TYPES:
                    return False
                return True
        return False

    def report_violation(self, node, v_type, severity, detail=""):
        self.violations.append({
            "class": self.current_class,
            "line": node.lineno,
            "type": v_type,
            "severity": severity,
            "detail": detail
        })

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_If(self, node):
        if self.is_type_comparison(node):
            severity = "medium" if any(isinstance(c, ast.Constant) for c in node.test.comparators) else "high"
            self.report_violation(node, "IF Type Dispatch", severity, "Uses if/elif on type/kind/action/method")
        elif self.is_isinstance_dispatch(node):
            self.report_violation(node, "isinstance Dispatch", "high", "Uses isinstance() on non-built-in type")
        self.generic_visit(node)

    def visit_Match(self, node):
        all_constants = all(
            isinstance(case.pattern, ast.MatchValue) and isinstance(case.pattern.value, ast.Constant)
            for case in node.cases
        )
        severity = "medium" if all_constants else "high"
        self.report_violation(node, "MATCH-CASE Dispatch", severity, "Uses match-case (switch-style)")
        self.generic_visit(node)


def detect_ocp_violations_from_file(filename: str):
    with open(filename, "r", encoding="utf-8") as f:
        code = f.read()
    tree = ast.parse(code)
    detector = OCPDetector()
    detector.visit(tree)
    return detector.violations


def get_ocp_report(code_str: str):
    try:
        tree = ast.parse(code_str)
        detector = OCPDetector()
        detector.visit(tree)
        if not detector.violations:
            return {"status": "Pass", "reason": "No type-based dispatching detected.", "suggestion": "N/A"}
        v = detector.violations[0]
        return {
            "status": "Violation",
            "reason": f"Line {v['line']} ({v['type']}): {v['detail']}",
            "suggestion": "Use polymorphism or strategy pattern instead of type-based branching."
        }
    except Exception as e:
        return {"status": "Pass", "reason": "Analyzer active.", "suggestion": str(e)}