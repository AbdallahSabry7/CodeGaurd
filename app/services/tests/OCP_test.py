import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from OCP_Detection_Final import get_ocp_report


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
        ("isinstance on exception — OK", """
def handle(err):
    if isinstance(err, ValueError):
        return 'bad value'
    if isinstance(err, (KeyError, IndexError)):
        return 'missing'
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
        ("callable dispatch", """
def execute(handler):
    if callable(handler):
        handler()
    else:
        handler.run()
""", "Violation"),
        ("issubclass dispatch", """
def process(cls):
    if issubclass(cls, Animal):
        return 'animal'
    return 'other'
""", "Violation"),
        ("getattr on 'type' attribute", """
def process(msg):
    if getattr(msg, 'type', None) == 'error':
        log_error(msg)
""", "Violation"),
        ("tracked-var dispatch (kind = obj.kind)", """
def dispatch(obj):
    kind = obj.kind
    if kind == 'circle':
        draw_circle(obj)
    elif kind == 'square':
        draw_square(obj)
""", "Violation"),
        ("tracked-var from subscript", """
def route(msg):
    action = msg['action']
    if action == 'create':
        do_create()
    elif action == 'delete':
        do_delete()
""", "Violation"),
        ("BoolOp type dispatch", """
def process(shape):
    if shape.kind == 'circle' or shape.kind == 'ellipse':
        draw_oval(shape)
""", "Violation"),
        ("startswith type dispatch", """
def handle(event):
    if event.type.startswith('mouse'):
        handle_mouse(event)
""", "Violation"),
        ("match-case on type variable", """
def execute(action):
    match action:
        case 'run': do_run()
        case 'stop': do_stop()
        case 'pause': do_pause()
""", "Violation"),
        ("match-case class patterns", """
def process(shape):
    match shape:
        case Circle(): draw_circle(shape)
        case Square(): draw_square(shape)
""", "Violation"),
        ("long elif chain (depth 2)", """
def compute(op, a, b):
    if op == 'add':
        return a + b
    elif op == 'sub':
        return a - b
    elif op == 'mul':
        return a * b
""", "Violation"),
        ("type-dispatch dict", """
HANDLERS = {
    Circle: handle_circle,
    Square: handle_square,
    Triangle: handle_triangle,
}
""", "Violation"),
        ("dict subscript type()", """
result = HANDLERS[type(obj)](obj)
""", "Violation"),
        ("clean polymorphic code", """
class Shape:
    def area(self): raise NotImplementedError

class Circle(Shape):
    def area(self): return 3.14 * self.r ** 2

class Square(Shape):
    def area(self): return self.side ** 2
""", "Pass"),
        ("clean singledispatch — OK", """
from functools import singledispatch

@singledispatch
def process(obj):
    raise NotImplementedError

@process.register(Circle)
def _(obj):
    draw_circle(obj)
""", "Pass"),
    ]

    passed = failed = 0
    print("\n" + "═" * 78)
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
                ctx = (f"{v['class'] or ''} "
                       f"{'/ ' + v['function'] + '()' if v['function'] else ''}").strip()
                print(f"     [{v['severity']:6}] line {v['line']:3}  {v['type']:<40}  {ctx}")
        else:
            print(f"     {report['reason']}")
        print("─" * 78)

    print(f"\n  RESULTS: {passed} passed, {failed} failed out of {len(_SAMPLES)}")
    print("═" * 78)