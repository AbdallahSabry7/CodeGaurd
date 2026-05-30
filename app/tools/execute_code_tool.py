from langchain_core.tools import tool
from services import _strip_fences, _inject_installer, run_in_docker, check_code , ExecutionResult , FailReason


@tool
def execute_code_tool(code: str) -> str:
    """
    Execute Python code in a secure Docker container and return the result.
    Missing third-party libraries are installed automatically via pip before
    execution. Dangerous imports and calls are hard-blocked. Code that is valid
    but uses sandbox-incompatible patterns (file I/O, stdin, os, sys) is treated
    as PASS with a note rather than a failure — the code is correct, just
    unrunnable in this environment.

    Args:
        code: Python source code to execute (plain or markdown-fenced).

    Returns:
        String describing execution result with PASS/FAIL and details.
    """
    # 1. Strip markdown fences
    code = _strip_fences(code)

    # 2. AST check on raw user code before any injection
    status, reason = check_code(code)

    if status == "dangerous":
        fail_reason = (
            FailReason.EMPTY_CODE    if reason == "empty_code"
            else FailReason.SYNTAX_ERROR if reason.startswith("SyntaxError")
            else FailReason.SAFETY_BLOCKED
        )
        return ExecutionResult.fail(fail_reason, stderr=reason).to_tool_string()

    if status == "skip":
        return (
            "PASS: Execution skipped — code is syntactically valid and logically correct "
            "but uses patterns that cannot run in this sandbox "
            f"({reason}). No execution errors detected."
        )

    # 3. status == "ok" — inject pip bootstrap then run
    code = _inject_installer(code)
    return run_in_docker(code).to_tool_string()