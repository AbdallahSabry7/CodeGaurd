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
                        if isinstance(stmt.func, ast.Attribute) and isinstance(stmt.func.value, ast.Name):
                            objects_used.add(stmt.func.value.id)
                        elif isinstance(stmt.func, ast.Name):
                            objects_used.add(stmt.func.id)

                # Detection logic using naming conventions
                responsibilities = re.split('_|And|Or', method_name)
                responsibilities = [r.lower() for r in responsibilities if r]

                methods_info.append({
                    "name": method_name,
                    "objects_used": list(objects_used),
                    "responsibilities": responsibilities
                })

        all_responsibilities = set(r for m in methods_info for r in m["responsibilities"])
        total_objects = sum(len(m["objects_used"]) for m in methods_info)

        responsibility_factor = max(0, len(all_responsibilities) - 1) / len(all_responsibilities) if all_responsibilities else 0
        object_factor = max(0, total_objects - len(methods_info)) / total_objects if total_objects else 0

        srp_violation_score = min(1, responsibility_factor + object_factor)

        self.report[class_name] = {
            "srp_violation_score": round(srp_violation_score * 100, 1),
            "is_violation": srp_violation_score > 0.4,
            "methods": [m["name"] for m in methods_info]
        }
        self.generic_visit(node)

def get_srp_report(code):
    try:
        tree = ast.parse(code)
        analyzer = SRPAnalyzerEnhanced()
        analyzer.visit(tree)
        
        if not analyzer.report:
            return {"status": "Pass", "reason": "No classes detected.", "suggestion": "Define a class to see SRP analysis."}
            
        first_class = list(analyzer.report.keys())[0]
        data = analyzer.report[first_class]
        
        if data["is_violation"]:
            return {
                "status": "Violation",
                "reason": f"Class '{first_class}' score is {data['srp_violation_score']}%. It likely has too many responsibilities.",
                "suggestion": f"Split '{first_class}' into smaller classes. Avoid 'And' in method names like '{data['methods'][0]}'."
            }
        
        return {
            "status": "Pass",
            "reason": f"Class '{first_class}' is cohesive.",
            "suggestion": "No refactor needed."
        }
    except Exception:
        return {"status": "Pass", "reason": "Analysis pending...", "suggestion": "N/A"}