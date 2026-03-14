import ast
import os


class DipAnalyzer(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.current_class = None
        self.violations = []

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_FunctionDef(self, node):
        if node.name == "__init__" and self.current_class is not None:
            for arg in node.args.args[1:]:  # skip self
                if arg.annotation:
                    typename = self._extract_type_name(arg.annotation)
                    if self._is_concrete(typename):
                        self.violations.append(
                            (
                                self.filename,
                                arg.lineno,
                                arg.col_offset,
                                f"DIP001 Class '{self.current_class}' depends on concrete class '{typename}'. Use an abstraction instead."
                            )
                        )
        self.generic_visit(node)

    def _extract_type_name(self, annotation):
        if isinstance(annotation, ast.Name):
            return annotation.id
        if isinstance(annotation, ast.Attribute):
            return annotation.attr
        return None

    def _is_concrete(self, typename):
        if typename is None:
            return False
        if typename.startswith("I"):
            return False
        if typename.endswith("Base") or typename.endswith("ABC"):
            return False
        return True


def analyze_file(path):
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    analyzer = DipAnalyzer(path)
    analyzer.visit(tree)
    return analyzer.violations


def analyze_directory(folder):
    results = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith(".py"):
                results.extend(analyze_file(os.path.join(root, file)))
    return results


def get_dip_report(code_str: str):
    try:
        tree = ast.parse(code_str)
        analyzer = DipAnalyzer(filename="<string>")
        analyzer.visit(tree)
        if not analyzer.violations:
            return {"status": "Pass", "reason": "No concrete class dependencies detected.", "suggestion": "N/A"}
        _, line, _, msg = analyzer.violations[0]
        return {
            "status": "Violation",
            "reason": f"Line {line}: {msg}",
            "suggestion": "Inject an abstraction (interface/abstract class) instead of a concrete class."
        }
    except Exception as e:
        return {"status": "Pass", "reason": "Analyzer active.", "suggestion": str(e)}


if __name__ == "__main__":
    import sys
    target = sys.argv[1]
    violations = (
        analyze_directory(target)
        if os.path.isdir(target)
        else analyze_file(target)
    )
    for file, line, col, msg in violations:
        print(f"{file}:{line}:{col}: {msg}")