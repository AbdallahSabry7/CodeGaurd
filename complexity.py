import ast


class UniversalComplexityAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.function_name = None
        self.loop_count = 0
        self.max_loop_depth = 0
        self.current_loop_depth = 0
        self.recursive_calls = 0
        self.variables = set()
        self.data_structures = set()
        self.growing_structures = set()
        self.memoization_detected = False

    def visit_FunctionDef(self, node):
        self.function_name = node.name
        for default in node.args.defaults:
            if isinstance(default, ast.Dict):
                self.memoization_detected = True
        self.generic_visit(node)

    def visit_For(self, node):
        self.loop_count += 1
        self.current_loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.current_loop_depth)
        self.generic_visit(node)
        self.current_loop_depth -= 1

    def visit_While(self, node):
        self.loop_count += 1
        self.current_loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.current_loop_depth)
        self.generic_visit(node)
        self.current_loop_depth -= 1

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == self.function_name:
            self.recursive_calls += 1
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.variables.add(target.id)
            elif isinstance(target, ast.Subscript):
                if isinstance(target.value, ast.Name):
                    self.growing_structures.add(target.value.id)
        self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and any(
                isinstance(op, ast.In) for op in node.test.ops
            ):
                self.memoization_detected = True
        self.generic_visit(node)

    def visit_List(self, node):
        self.data_structures.add("list")
        self.generic_visit(node)

    def visit_Dict(self, node):
        self.data_structures.add("dict")
        self.generic_visit(node)

    def visit_Set(self, node):
        self.data_structures.add("set")
        self.generic_visit(node)

    def visit_Tuple(self, node):
        self.data_structures.add("tuple")
        self.generic_visit(node)

    def analyze(self):
        if self.recursive_calls > 0:
            if self.memoization_detected:
                time_complexity = "O(n)"
            else:
                time_complexity = "O(2^n)"
        elif self.max_loop_depth == 1:
            time_complexity = "O(n)"
        elif self.max_loop_depth == 2:
            time_complexity = "O(n^2)"
        elif self.max_loop_depth > 2:
            time_complexity = f"O(n^{self.max_loop_depth})"
        else:
            time_complexity = "O(1)"

        if self.recursive_calls > 0 or self.memoization_detected:
            space_complexity = "O(n)"
        elif self.growing_structures or self.data_structures & {"list", "dict", "set"}:
            space_complexity = "O(n)"
        else:
            space_complexity = "O(1)"

        return time_complexity, space_complexity


def estimate_complexity(code_str: str):
    try:
        tree = ast.parse(code_str)
        analyzer = UniversalComplexityAnalyzer()
        analyzer.visit(tree)
        return analyzer.analyze()
    except Exception as e:
        return ("Error", str(e))
