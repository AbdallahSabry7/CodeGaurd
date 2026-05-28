import ast
import re


class SRPAnalyzerEnhanced(ast.NodeVisitor):
    def __init__(self):
        self.report = {}

    def visit_ClassDef(self, node):
        class_name = node.name
        methods_info = []

        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                method_name = n.name
                objects_used = set()

                for stmt in ast.walk(n):
                    if isinstance(stmt, ast.Call):
                        if (
                            isinstance(stmt.func, ast.Attribute)
                            and isinstance(stmt.func.value, ast.Name)
                            and stmt.func.value.id != "self"  # Fix #7
                        ):
                            objects_used.add(stmt.func.value.id)
                        elif isinstance(stmt.func, ast.Name):
                            objects_used.add(stmt.func.id)

                # Fix #3: only split on explicit camelCase And/Or boundaries
                parts = re.split(r'(?<=[a-z])(?:And|Or)(?=[A-Z])', method_name)
                responsibilities = [p.lower() for p in parts if p]

                methods_info.append({
                    "name": method_name,
                    "objects_used": list(objects_used),
                    "responsibilities": responsibilities,
                })

        all_responsibilities = {r for m in methods_info for r in m["responsibilities"]}
        total_objects = sum(len(m["objects_used"]) for m in methods_info)

        # Fix #5: safe single-item case
        n = len(all_responsibilities)
        responsibility_factor = 0.0 if n <= 1 else (n - 1) / n

        object_factor = (
            max(0, total_objects - len(methods_info)) / total_objects
            if total_objects else 0
        )

        # Fix #4: weighted average instead of unclamped sum
        srp_violation_score = 0.6 * responsibility_factor + 0.4 * object_factor

        self.report[class_name] = {
            "srp_violation_score": round(srp_violation_score * 100, 1),
            "is_violation": srp_violation_score > 0.4,
            "methods": [m["name"] for m in methods_info],
        }
        self.generic_visit(node)


def get_srp_report(code):
    try:
        tree = ast.parse(code)
        analyzer = SRPAnalyzerEnhanced()
        analyzer.visit(tree)

        if not analyzer.report:
            return {
                "status": "Pass",
                "reason": "No classes detected.",
                "suggestion": "Define a class to see SRP analysis.",
            }

        # Fix #1: report on all classes, not just the first
        results = []
        for class_name, data in analyzer.report.items():
            if data["is_violation"]:
                first_method = data["methods"][0] if data["methods"] else "your methods"  # Fix #6
                results.append({
                    "class": class_name,
                    "status": "Violation",
                    "reason": f"Class '{class_name}' score is {data['srp_violation_score']}%. It likely has too many responsibilities.",
                    "suggestion": f"Split '{class_name}' into smaller classes. Avoid 'And' in method names like '{first_method}'.",
                })
            else:
                results.append({
                    "class": class_name,
                    "status": "Pass",
                    "reason": f"Class '{class_name}' is cohesive.",
                    "suggestion": "No refactor needed.",
                })

        return results

    except SyntaxError as e:
        return [{"status": "Error", "reason": f"Syntax error: {e}", "suggestion": "Fix the syntax before analysis."}]
    except Exception as e:
        return [{"status": "Error", "reason": f"Unexpected error: {e}", "suggestion": "N/A"}]