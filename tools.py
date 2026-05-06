import ast
import json
import re
import os
import docker
import tempfile
import shutil
from langchain_core.tools import tool
from ISP_detect import get_isp_report
from Liskov_Substitution_Principle import get_lsp_report
from OCP_Detection_Final import get_ocp_report
from dependancy_principle import get_dip_report
from SRP_Detection_Final import get_srp_report
from clean_code import analyze_code_string
from dataclasses import dataclass


BLOCKED_PATTERNS = [
    'os.system',
    'subprocess',
    'shutil.rmtree',
    'socket.',
    '__import__',
    'importlib',
    'ctypes',
    'eval(',
    'exec(',
]

DOCKER_IMAGE = "python:3.11-slim"
OUTPUT_LIMIT = 2000


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int


def is_code_safe(code: str) -> tuple[bool, str]:
    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            return False, f"Blocked pattern found: {pattern}"
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    return True, "OK"


def extract_code(message_content: str) -> str | None:
    match = re.search(r'```python\n(.*?)```', message_content, re.DOTALL)
    return match.group(1).strip() if match else None


def _fail(stderr: str, exit_code: int = -1) -> ExecutionResult:
    return ExecutionResult(success=False, stdout="", stderr=stderr, exit_code=exit_code)


def run_in_docker(code: str) -> ExecutionResult:
    try:
        client = docker.from_env()
    except docker.errors.DockerException as e:
        return _fail(f"Cannot connect to Docker daemon: {e}")

    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, "code_to_test.py")

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
    except OSError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _fail(f"Failed to write code to temp file: {e}")

    try:
        container = client.containers.run(
            image=DOCKER_IMAGE,
            command="python /code/code_to_test.py",
            volumes={temp_dir: {"bind": "/code", "mode": "ro"}},
            mem_limit="128m",
            cpu_quota=50000,
            pids_limit=64,
            network_disabled=True,
            read_only=True,
            detach=True,
        )

        try:
            result = container.wait(timeout=10)
            exit_code = result.get("StatusCode", 1)

            stdout_bytes = container.logs(stdout=True, stderr=False)
            stderr_bytes = container.logs(stdout=False, stderr=True)

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            truncated_out = len(stdout) > OUTPUT_LIMIT
            truncated_err = len(stderr) > OUTPUT_LIMIT

            return ExecutionResult(
                success=(exit_code == 0),
                stdout=stdout[:OUTPUT_LIMIT] + ("\n[output truncated]" if truncated_out else ""),
                stderr=stderr[:OUTPUT_LIMIT] + ("\n[output truncated]" if truncated_err else ""),
                exit_code=exit_code,
            )

        except Exception:
            container.kill()
            return _fail("Execution timed out", exit_code=-1)

        finally:
            container.remove(force=True)

    except docker.errors.ContainerError as e:
        raw_stderr = e.stderr
        if raw_stderr is None:
            stderr_text = str(e)
        elif isinstance(raw_stderr, bytes):
            stderr_text = raw_stderr.decode("utf-8", errors="replace")
        else:
            stderr_text = str(raw_stderr)

        raw_stdout = getattr(e, "output", None)
        if raw_stdout and isinstance(raw_stdout, bytes):
            stdout_text = raw_stdout.decode("utf-8", errors="replace")[:OUTPUT_LIMIT]
        else:
            stdout_text = ""

        stderr_trimmed = stderr_text[:OUTPUT_LIMIT]

        return ExecutionResult(
            success=False,
            stdout=stdout_text,
            stderr=stderr_trimmed,
            exit_code=e.exit_status if hasattr(e, "exit_status") else 1,
        )

    except docker.errors.ImageNotFound:
        return _fail(
            f"Docker image '{DOCKER_IMAGE}' not found. "
            f"Pull it first with: docker pull {DOCKER_IMAGE}"
        )

    except docker.errors.APIError as e:
        return _fail(f"Docker API error: {e}")

    except docker.errors.DockerException as e:
        return _fail(f"Docker error: {e}")

    except Exception as e:
        return _fail(f"Unexpected error during execution: {type(e).__name__}: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@tool
def execute_code_tool(code: str) -> str:
    """
    Execute Python code in a secure Docker container and return the result.

    Args:
        code: Python source code to execute

    Returns:
        String describing execution result (PASS or FAIL with details)
    """
    fenced = re.search(r'```(?:python)?\n(.*?)```', code, re.DOTALL)
    if fenced:
        code = fenced.group(1).strip()

    is_safe, reason = is_code_safe(code)
    if not is_safe:
        return f"FAIL: Safety check blocked execution\nReason: {reason}"

    result = run_in_docker(code)

    if result.success:
        stdout_info = f"\nOutput:\n{result.stdout}" if result.stdout.strip() else ""
        return f"PASS: Code executed successfully{stdout_info}"

    parts = [f"FAIL: Execution failed (exit code {result.exit_code})"]

    if result.stdout.strip():
        parts.append(f"Stdout:\n{result.stdout}")

    if result.stderr.strip():
        parts.append(f"Stderr:\n{result.stderr}")

    return "\n".join(parts)


@tool
def complexity_analyzer_tool(code: str) -> str:
    """
    Analyze a Python code snippet and estimate its time and space complexity.
    Input must be valid Python code.
    """
    from complexity import estimate_complexity
    time_complexity, space_complexity = estimate_complexity(code)
    return (
        f"Time Complexity: {time_complexity}\n"
        f"Space Complexity: {space_complexity}"
    )


@tool
def solid_analysis_tool(code: str) -> dict:
    """
    Analyze Python code for SOLID violations.

    INPUT:
    - code (str): Full raw source code.

    OUTPUT:
    - Structured violation report.
    """
    results = {
        "SRP": get_srp_report(code),
        "OCP": get_ocp_report(code),
        "LSP": get_lsp_report(code),
        "ISP": get_isp_report(code),
        "DIP": get_dip_report(code),
    }
    return json.dumps(results, indent=2)


@tool
def clean_code_analysis_tool(code: str) -> dict:
    """
    Tool wrapper that calls internal clean code analysis functions.
    """
    return analyze_code_string(code)


analysis_tools = [complexity_analyzer_tool, solid_analysis_tool, clean_code_analysis_tool]
validator_tool = [complexity_analyzer_tool, solid_analysis_tool, clean_code_analysis_tool, execute_code_tool]