
import sys
import os
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from Liskov_Substitution_Principle import get_lsp_report


PARAM_COUNT_VIOLATION = """
class Animal:
    def process(self, x: int) -> object:
        return x

class BadDog(Animal):
    def process(self, x, y):
        return x
"""

PARAM_COUNT_PASS = """
class Animal:
    def process(self, x: int) -> object:
        return x

class Dog(Animal):
    def process(self, x: int) -> object:
        return x * 2
"""

PARAM_TYPE_VIOLATION = """
class Animal:
    def process(self, x: int) -> object:
        return x

class Dog(Animal):
    def process(self, x: str) -> object:  # str is not a supertype of int
        return x
"""

PARAM_TYPE_PASS = """
class Animal:
    def process(self, x: bool) -> object:
        return x

class Dog(Animal):
    def process(self, x: int) -> object:  # int is supertype of bool — OK
        return x
"""

RETURN_TYPE_VIOLATION = """
class Base:
    def run(self) -> int:
        return 42

class Broken(Base):
    def run(self) -> str:   # str is NOT a subtype of int
        return "oops"
"""

RETURN_TYPE_PASS = """
class Base:
    def get(self) -> object:
        return 1

class Child(Base):
    def get(self) -> int:   # int is subtype of object — covariance satisfied
        return 2
"""

NOT_IMPLEMENTED_VIOLATION = """
class Base:
    def run(self):
        print("running")

class Child(Base):
    def run(self):
        raise NotImplementedError()
"""

NOT_IMPLEMENTED_PASS = """
from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def run(self): pass

class Child(Base):
    def run(self):
        print("running")  # concrete implementation — no violation
"""

REMOVES_RETURN_VIOLATION = """
class Base:
    def compute(self) -> int:
        return 42

class Child(Base):
    def compute(self):
        print("computing")   # never returns a value
"""

REMOVES_RETURN_PASS = """
class Base:
    def compute(self) -> int:
        return 42

class Child(Base):
    def compute(self) -> int:
        return 99
"""

BINDING_TYPE_VIOLATION = """
class A:
    @classmethod
    def test(cls):
        pass

class B(A):
    def test(self):   # drops classmethod
        pass
"""

BINDING_TYPE_PASS = """
class A:
    @classmethod
    def test(cls):
        pass

class B(A):
    @classmethod
    def test(cls):
        pass
"""

KWONLY_VIOLATION = """
class Base:
    def run(self, *, verbose=False): pass

class Child(Base):
    def run(self, *, debug=False): pass  # renamed kwonly param
"""

KWONLY_PASS = """
class Base:
    def run(self, *, verbose=False): pass

class Child(Base):
    def run(self, *, verbose=False): pass
"""

REMOVES_DEFAULT_VIOLATION = """
class Base:
    def connect(self, host, port=8080): pass

class Child(Base):
    def connect(self, host, port): pass  # removes default
"""

REMOVES_DEFAULT_PASS = """
class Base:
    def connect(self, host, port=8080): pass

class Child(Base):
    def connect(self, host, port=9090): pass  # changes default value — OK
"""

FORWARD_DECLARED_VIOLATION = """
class EarlyChild(LateParent):
    def greet(self, name: int) -> str:
        return str(name)

class LateParent:
    def greet(self, name: str) -> str:
        return name
"""

FORWARD_DECLARED_PASS = """
class LateParent:
    def greet(self, name: str) -> str:
        return name

class EarlyChild(LateParent):
    def greet(self, name: str) -> str:
        return name.upper()
"""

NEW_EXCEPTION_VIOLATION = """
class Base:
    def load(self, path):
        return open(path).read()

class Child(Base):
    def load(self, path):
        if not path:
            raise FileNotFoundError()
        return open(path).read()
"""

NEW_EXCEPTION_PASS = """
class Base:
    def load(self, path):
        raise FileNotFoundError()

class Child(Base):
    def load(self, path):
        # does real work, raises the same exception the parent does
        data = open(path).read()
        if not data:
            raise FileNotFoundError()
        return data
"""

ALWAYS_RAISES_VIOLATION = """
class Base:
    def save(self, data):
        self.db.write(data)

class Child(Base):
    def save(self, data):
        raise RuntimeError("not supported")
"""

ALWAYS_RAISES_PASS = """
class Base:
    def save(self, data):
        self.db.write(data)

class Child(Base):
    def save(self, data):
        self.cache.write(data)
"""

ASSERT_PRECONDITION_VIOLATION = """
class Base:
    def process(self, value):
        return value * 2

class Child(Base):
    def process(self, value):
        assert value > 0, "must be positive"
        return value * 2
"""

ASSERT_PRECONDITION_PASS = """
class Base:
    def process(self, value):
        assert value > 0
        return value * 2

class Child(Base):
    def process(self, value):
        return value * 2
"""

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    examples = [
        # violations
        ("Param count      VIOLATION — extra positional arg      (BadDog)",      PARAM_COUNT_VIOLATION,      "Violation"),
        ("Param type       VIOLATION — contravariance broken      (Dog/str→int)", PARAM_TYPE_VIOLATION,       "Violation"),
        ("Return type      VIOLATION — non-subtype return         (Broken)",      RETURN_TYPE_VIOLATION,      "Violation"),
        ("NotImplemented   VIOLATION — overrides concrete method  (Child)",       NOT_IMPLEMENTED_VIOLATION,  "Violation"),
        ("Removes return   VIOLATION — drops non-None return      (Child)",       REMOVES_RETURN_VIOLATION,   "Violation"),
        ("Binding type     VIOLATION — drops classmethod          (B)",           BINDING_TYPE_VIOLATION,     "Violation"),
        ("Kwonly params    VIOLATION — renames keyword-only param (Child)",       KWONLY_VIOLATION,           "Violation"),
        ("Removes default  VIOLATION — removes parameter default  (Child)",       REMOVES_DEFAULT_VIOLATION,  "Violation"),
        ("Forward declared VIOLATION — child before parent        (EarlyChild)",  FORWARD_DECLARED_VIOLATION, "Violation"),
        ("New exception    VIOLATION — introduces new exception   (Child)",       NEW_EXCEPTION_VIOLATION,    "Violation"),
        ("Always raises    VIOLATION — removes all parent behavior(Child)",       ALWAYS_RAISES_VIOLATION,    "Violation"),
        ("Assert precon.   VIOLATION — strengthens precondition   (Child)",       ASSERT_PRECONDITION_VIOLATION, "Violation"),
        # passes
        ("Param count      PASS      — same signature             (Dog)",         PARAM_COUNT_PASS,           "Pass"),
        ("Param type       PASS      — bool→int contravariance OK (Dog)",         PARAM_TYPE_PASS,            "Pass"),
        ("Return type      PASS      — int subtype of object      (Child)",       RETURN_TYPE_PASS,           "Pass"),
        ("NotImplemented   PASS      — parent is abstract         (Child)",       NOT_IMPLEMENTED_PASS,       "Pass"),
        ("Removes return   PASS      — child still returns        (Child)",       REMOVES_RETURN_PASS,        "Pass"),
        ("Binding type     PASS      — both classmethod           (B)",           BINDING_TYPE_PASS,          "Pass"),
        ("Kwonly params    PASS      — same kwonly params         (Child)",       KWONLY_PASS,                "Pass"),
        ("Removes default  PASS      — changes value, keeps param (Child)",       REMOVES_DEFAULT_PASS,       "Pass"),
        ("Forward declared PASS      — child after parent         (EarlyChild)",  FORWARD_DECLARED_PASS,      "Pass"),
        ("New exception    PASS      — same exception as parent   (Child)",       NEW_EXCEPTION_PASS,         "Pass"),
        ("Always raises    PASS      — child provides behavior    (Child)",       ALWAYS_RAISES_PASS,         "Pass"),
        ("Assert precon.   PASS      — child relaxes, not tightens(Child)",       ASSERT_PRECONDITION_PASS,   "Pass"),
    ]

    passed = failed = 0
    failures = []

    for title, code, expected in examples:
        report = get_lsp_report(code)
        got = report["status"]
        ok = (got == expected)
        symbol = "✓" if ok else "✗"
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((title, expected, got, report))

        print(f"\n{'═' * 74}")
        print(f"  {symbol}  {title}")
        print(f"     Expected: {expected:<12}  Got: {got}")
        print("═" * 74)
        if report["violations"]:
            for v in report["violations"]:
                print(f"  [{v['severity']}] line {v['line']} — {v['message']}")
        else:
            print(f"  {report.get('reason', 'No violations found.')}")

    print(f"\n{'═' * 74}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(examples)} examples")
    if failures:
        print("\n  FAILURES:")
        for title, exp, got, report in failures:
            print(f"    ✗ {title}")
            print(f"      Expected {exp}, got {got}")
            if report["violations"]:
                for v in report["violations"]:
                    print(f"        [{v['severity']}] {v['message']}")