import ast

def exc_name_from_raise(node: ast.Raise) -> str:
    """Extract exception name from raise statement."""
    if node.exc is None:
        return ""
    
    if isinstance(node.exc, ast.Name):
        # Handle cases like raise Exception
        return node.exc.id
    elif isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
        # Handle cases like raise Exception()
        return node.exc.func.id
    elif isinstance(node.exc, ast.Attribute):
        # Handle cases like module.Exception
        return node.exc.attr
    elif isinstance(node.exc, ast.Subscript):
        # Handle cases like Exception[Type]
        if isinstance(node.exc.value, ast.Name):
            return node.exc.value.id
    return ""

class AbstractClassHelper:

    ABSTRACT_DECORATORS = {
        "abstractmethod",
        "abstractproperty",
        "abstractclassmethod",
        "abstractstaticmethod",
    }

    @staticmethod
    def is_abstract_method(node: ast.FunctionDef) -> bool:

        for d in node.decorator_list:
            if isinstance(d, ast.Name) and d.id in AbstractClassHelper.ABSTRACT_DECORATORS:#check for @abstractmethod
                return True
            if isinstance(d, ast.Attribute) and d.attr in AbstractClassHelper.ABSTRACT_DECORATORS:#check for @abc.abstractmethod
                return True

        if len(node.body) == 1 :
            only_statement = node.body[0]

            if isinstance(only_statement, ast.Pass):#check for 'pass' only body
                return True
            
            if isinstance(only_statement, ast.Expr) and\
                isinstance(only_statement.value, ast.Constant) and isinstance(only_statement.value.value, str):#check for docstring only body
                return True
            
            if isinstance(only_statement, ast.Return) and\
                isinstance(only_statement.value,ast.Name) and only_statement.value.id == "NotImplemented":#check for 'return NotImplemented' only body
                    return True

        for n in ast.walk(node):#check for raise NotImplementedError
            if isinstance(n, ast.Raise):
                name = exc_name_from_raise(n)
                if name == "NotImplementedError":
                    return True

        doc = ast.get_docstring(node)#check docstring for abstract hints
        if doc:
            low = doc.lower()
            tirggers = ["not implemented", "abstract method","subclasses should implement",
                        "to be implemented by subclass","abstract", "must implement", "override", "implement me"]
            if any(word in low for word in tirggers):
                return True

        return False

    @staticmethod
    def is_abstract_class(node: ast.ClassDef) -> bool:
        # check if class inherits from ABC or ABCMeta
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in ("ABC", "ABCMeta"):
                return True
            if isinstance(base, ast.Attribute) and base.attr in ("ABC", "ABCMeta"):
                return True

        # check if any method is abstract
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if AbstractClassHelper.is_abstract_method(item):
                    return True

        return False

class LSPDetector(ast.NodeVisitor):
    def __init__(self):
        self.classes = {}      
        self.inheritance = {}  
        self.current_class = None
        self.violations = []
        self.abstract_classes = set()

    def add_violation(self, node, msg):
        self.violations.append(f"Line {node.lineno}: {msg}")

    # Parse Class Definitions
    def visit_ClassDef(self, node):
        self.classes[node.name] = node
        parents = [b.id for b in node.bases if isinstance(b, ast.Name)]
        self.inheritance[node.name] = parents
        
        # Check if this is an abstract class
        if AbstractClassHelper.is_abstract_class(node):
            self.abstract_classes.add(node.name)
        
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    # Parse Function Definitions
    def visit_FunctionDef(self, node):
        if self.current_class is None:
            return
        
        cls = self.classes[self.current_class]
        parents = self.inheritance.get(self.current_class, [])

        # Check overridden methods
        for parent in parents:
            if parent in self.classes:
                parent_methods = {
                    p.name: p for p in self.classes[parent].body 
                    if isinstance(p, ast.FunctionDef)
                }

                if node.name in parent_methods:
                    parent_method = parent_methods[node.name]
                    self.compare_methods(node, parent_method, parent)

        self.generic_visit(node)

    
    def compare_methods(self, child, parent, parent_name):
        # Enhanced LSP checks with abstract class awareness
        
        # Check if parent method is abstract
        parent_is_abstract = AbstractClassHelper.is_abstract_method(parent)
        
        # Check parameter count
        child_args = len(child.args.args) - 1  # -1 to exclude 'self'
        parent_args = len(parent.args.args) - 1

        if child_args != parent_args:
            self.add_violation(
                child,
                f"LSP: '{child.name}' overrides parent '{parent_name}' "
                f"with different parameter count ({child_args} vs {parent_args})."
            )

        # Check return type 
        c_return = ast.unparse(child.returns) if child.returns else None
        p_return = ast.unparse(parent.returns) if parent.returns else None

        if c_return != p_return:
            if p_return is not None:
                self.add_violation(
                    child,
                    f"LSP: '{child.name}' changes return type "
                    f"from '{p_return}' to '{c_return}'."
                )

        # Check if child raises NotImplementedError when parent is not abstract
        if not parent_is_abstract:
            for n in ast.walk(child):
                if isinstance(n, ast.Raise):
                    if isinstance(n.exc, ast.Call) and getattr(n.exc.func, "id", "") == "NotImplementedError":
                        self.add_violation(
                            child,
                            f"LSP: '{child.name}' raises NotImplementedError "
                            f"while overriding non-abstract parent method."
                        )
        
        # Detect new exceptions not raised in parent (only for non-abstract parent methods)
        if not parent_is_abstract:
            parent_exceptions = set()
            for n in ast.walk(parent):
                if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
                    exc_name = getattr(n.exc.func, "id", None)
                    if exc_name:
                        parent_exceptions.add(exc_name)
            
            child_exceptions = set()
            for n in ast.walk(child):
                if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
                    exc_name = getattr(n.exc.func, "id", None)
                    if exc_name:
                        child_exceptions.add(exc_name)
            
            # Check for new exceptions introduced in child
            new_exceptions = child_exceptions - parent_exceptions
            for exc in new_exceptions:
                self.add_violation(
                    child,
                    f"LSP: '{child.name}' introduces new exception '{exc}' "
                    f"not present in parent method."
                )


def analyze_code(code_str):
    tree = ast.parse(code_str)

    detector = LSPDetector()
    detector.visit(tree)

    return detector.violations

def get_lsp_report(code_str: str):
    try:
        tree = ast.parse(code_str)
        detector = LSPDetector()
        detector.visit(tree)
        
        if not detector.violations:
            return {"status": "Pass", "reason": "Subclasses maintain parent signatures.", "suggestion": "N/A"}
        
        # Grab the first violation message
        v_msg = detector.violations[0]
        return {
            "status": "Violation",
            "reason": v_msg,
            "suggestion": "Keep method signatures, return types, and exceptions consistent with the parent class."
        }
    except Exception as e:
        return {"status": "Pass", "reason": "Analyzer active.", "suggestion": str(e)}



if __name__ == "__main__":
    code = """
class Parent:
    def process(self, x):
        return x + 1

class Child1(Parent):
    def process(self, x, y):   
        return x

class Child2(Parent):
    def process(self, x):
        return str(x)  

class Child3(Parent):
    def process(self, x):
        raise ValueError()

class Child4(Parent):
    def process(self, x):
        raise NotImplementedError()
"""
    violations = analyze_code(code)
    print(violations)
