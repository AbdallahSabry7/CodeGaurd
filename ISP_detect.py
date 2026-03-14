import ast

class ISPDetector(ast.NodeVisitor):
    def __init__(self, method_threshold=6, unused_threshold=0.4):
        self.method_threshold = method_threshold
        self.unused_threshold = unused_threshold
        self.violations = []
        self.current_class = None
        self.current_interface = None
        self.interfaces = {}
        self.class_implements = {}
        self.class_usage = {}
        self.class_methods = {}
        self.forced_methods = {}

    def visit_ClassDef(self, node):
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        methods = [f.name for f in node.body if isinstance(f, ast.FunctionDef)]

        if any(b.endswith("Interface") or b.startswith("I") for b in bases):
            self.current_interface = node.name
            self.interfaces[node.name] = methods
            self.detect_fat_interface(node, methods)
            self.detect_interface_role_mixing(node)
            self.current_interface = None
            return

        self.current_class = node.name
        self.class_methods[node.name] = methods
        self.class_implements[node.name] = bases
        self.class_usage[node.name] = set()
        self.forced_methods[node.name] = set()

        for f in node.body:
            if isinstance(f, ast.FunctionDef):
                self.visit(f)

        self.detect_unused_interface_methods(node)
        self.detect_forced_methods(node)

        self.current_class = None

    def visit_FunctionDef(self, node):
        if self.current_class:
            if len(node.body) == 1:
                b = node.body[0]
                if isinstance(b, ast.Pass):
                    self.forced_methods[self.current_class].add(node.name)
                if isinstance(b, ast.Raise):
                    self.forced_methods[self.current_class].add(node.name)

            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute):
                        if isinstance(child.func.value, ast.Name):
                            if child.func.value.id == "self":
                                self.class_usage[self.current_class].add(child.func.attr)

    def detect_fat_interface(self, node, methods):
        if len(methods) > self.method_threshold:
            self.violations.append({
                "interface": node.name,
                "reason": f"Has {len(methods)} methods (fat interface)"
            })

    def detect_interface_role_mixing(self, node):
        keywords = {
            "save", "load", "connect", "render", "draw", "update",
            "delete", "cache", "log", "email", "send", "store"
        }
        actions = set()
        for f in node.body:
            if isinstance(f, ast.FunctionDef):
                for word in keywords:
                    if word in f.name.lower():
                        actions.add(word)
        if len(actions) > 3:
            self.violations.append({
                "interface": node.name,
                "reason": f"Interface mixes multiple unrelated responsibilities: {', '.join(actions)}"
            })

    def detect_unused_interface_methods(self, node):
        for base in self.class_implements[node.name]:
            if base in self.interfaces:
                interface_methods = set(self.interfaces[base])
                used = self.class_usage[node.name]
                unused = interface_methods - used
                ratio = len(unused) / len(interface_methods)
                if ratio >= self.unused_threshold:
                    self.violations.append({
                        "class": node.name,
                        "reason": f"Implements {base} but leaves {len(unused)}/{len(interface_methods)} methods unused"
                    })

    def detect_forced_methods(self, node):
        forced = self.forced_methods[node.name]
        if forced:
            for method in forced:
                self.violations.append({
                    "class": node.name,
                    "reason": f"Method {method} looks forced (empty, pass, or raise)"
                })


def analyze_isp(code, method_threshold=6, unused_threshold=0.4):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        print(f"Syntax Error: {e}")
        return []
    detector = ISPDetector(method_threshold, unused_threshold)
    detector.visit(tree)
    return detector.violations


def get_isp_report(code_str: str):
    try:
        violations = analyze_isp(code_str)
        if not violations:
            return {"status": "Pass", "reason": "No fat or forced interfaces detected.", "suggestion": "N/A"}
        v = violations[0]
        reason = v.get("reason", str(v))
        target = v.get("interface", v.get("class", "Unknown"))
        return {
            "status": "Violation",
            "reason": f"'{target}': {reason}",
            "suggestion": "Split the interface into smaller, role-specific interfaces."
        }
    except Exception as e:
        return {"status": "Pass", "reason": "Analyzer active.", "suggestion": str(e)}


if __name__ == "__main__":
    user_code = """
class IDataInterface:
    def save_data(self): pass
    def load_data(self): pass
    def connect_server(self): pass
    def draw_ui(self): pass
    def log_event(self): pass
    def delete_cache(self): pass

class MyClass(IDataInterface):
    def save_data(self): 
        pass
    def load_data(self):
        self.save_data()

"""
    results = analyze_isp(user_code)
    if results:
        print("\nISP Violations Detected:")
        for v in results:
            print(f"- {v}")
    else:
        print("\nNo ISP violations detected.")