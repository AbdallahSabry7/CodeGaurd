def _refactor_prompt(instruction: str, inputs: list[str], extra_rules: tuple[str, ...] = ()) -> str:
    return "\n".join([
        "You are a code refactoring engineer.",
        instruction,
        "",
        "You will receive:",
        *[f"{i+1}. {item}" for i, item in enumerate(inputs)],
        "",
        "## Refactoring Rules",
        "",
        "### Correctness",
        "- Address every issue you are asked to fix — no exceptions",
        "- Do not add new features or logic not implied by the directives",
        "- Do not remove or alter existing functionality",
        "- Preserve original function signatures and class names",
        "- Keep all existing imports; add only what the fixes require",
        "",
        "### SOLID Principles",
        "- SRP: Each class and function must have exactly one reason to change.",
        "  Split any class or function that handles multiple responsibilities.",
        "- OCP: Extend behavior through new classes or functions, not by modifying existing ones.",
        "  Replace hard-coded conditionals that switch on type with polymorphism or strategy pattern.",
        "- LSP: Subclasses must be fully substitutable for their parent.",
        "  Never override a method in a way that weakens preconditions or breaks the parent contract.",
        "- ISP: No class should be forced to implement methods it does not use.",
        "  Split fat interfaces into focused ones.",
        "- DIP: High-level modules must not depend on concrete classes.",
        "  Depend on abstractions (ABCs or protocols); inject dependencies rather than instantiating them inside a class.",
        "",
        "### Code Quality",
        "- Use snake_case for variables and functions, PascalCase for classes",
        "- Add type hints to every function signature and return type",
        "- Add a one-line docstring to every public function and class",
        "- Raise specific named exceptions instead of printing errors",
        "- Replace manual loops for min/max/sum/filter with Python builtins or list comprehensions",
        "- Refactor any function with more than 4 parameters to accept a dataclass or TypedDict",
        "- Remove dead code, redundant comments, and magic numbers (use named constants)",
        "- Keep functions short and focused — if a function needs a comment to explain a block, extract that block",
        "",
        "### Do Not Introduce",
        "- New SOLID violations not present in the original",
        "- Circular dependencies or unnecessary coupling between modules",
        "- Overly deep inheritance chains — prefer composition over inheritance",
        "- Global state or mutable defaults",
        "- Broad except clauses that swallow errors silently",
        *extra_rules,
        "",
        "## Output",
        "- do not include any text other than the refactored code",
        "- Output the complete refactored Python source code only.",
        "- No explanations, no commentary, no fix lists.",
        "- Do not wrap the code in markdown fences (no ```python or ```).",
        "- Output raw Python code starting from the first import or class/function definition.",
    ])


REFACTOR_SYSTEM_PROMPT = _refactor_prompt(
    instruction=(
        "You are given Python code and a prioritized list of refactor directives produced by a "
        "senior software architect who has already reviewed the latest static-analysis findings "
        "for THIS version of the code and discarded every false positive. Every directive listed "
        "is real — apply ALL of them, working from the highest severity down. The code may already "
        "be partially refactored from an earlier pass; keep those correct fixes intact and apply "
        "only what the directives now ask for."
    ),
    inputs=[
        "The code to refactor (the latest version)",
        "The architect's prioritized refactor directives (already vetted — fix every one)",
    ],
)


# Repair pass — re-entry after a syntax OR runtime error. Fix the error only.
REFACTOR_SYNTAX_PROMPT = _refactor_prompt(
    instruction=(
        "Your previously refactored code failed to compile or run. Fix ONLY the reported error "
        "so the code becomes valid and runnable. Do not change anything else and do not undo "
        "any correct refactor."
    ),
    inputs=[
        "Your previous refactored version (the code to fix)",
        "The exact SyntaxError / runtime error to fix",
    ],
    extra_rules=(
        "- Make the minimal change required to resolve the reported error",
        "- Do not re-architect or add changes beyond fixing the error",
    ),
)

REFACTOR_BEHAVIOR_PROMPT = """Your previous refactor CHANGED the program's behavior.
Below is a black-box equivalence report: inputs where the refactored code produced a
different result than the original.

Fix the refactored code so it reproduces the ORIGINAL behavior on these inputs, while
KEEPING your structural/quality improvements. Do NOT rename public (module-level,
non-underscore) functions - they are the program's contract. Return the full corrected
code only.

Equivalence report:
{behavior_diff}

Current refactored code:
{refactored_code}
"""