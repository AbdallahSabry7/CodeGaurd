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


BLOCKED_PATTERNS = [
    'os.system', 'subprocess', 'shutil.rmtree',
    'socket', '__import__', 'open(',
]


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
    if match:
        return match.group(1).strip()
    return None


def run_in_docker(code: str) -> dict:
    client = docker.from_env()
    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, "code_to_test.py")

    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(code)

        output = client.containers.run(
            image="python:3.11-slim",
            command="python /code/code_to_test.py",
            volumes={temp_dir: {'bind': '/code', 'mode': 'ro'}},
            mem_limit="128m",
            cpu_quota=50000,
            network_disabled=True,
            read_only=True,
            remove=True,
            stdout=True,
            stderr=True,
            detach=False,
            timeout=10
        )
        return {
            "success": True,
            "stdout": output.decode('utf-8', errors='replace')[:2000],
            "stderr": "",
            "exit_code": 0
        }

    except docker.errors.ContainerError as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": e.stderr.decode('utf-8', errors='replace')[:2000],
            "exit_code": 1
        }
    except docker.errors.ImageNotFound:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Docker image 'python:3.11-slim' not found. Run: docker pull python:3.11-slim",
            "exit_code": -1
        }
    except docker.errors.DockerException as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Docker error: {str(e)}",
            "exit_code": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Unexpected error: {str(e)}",
            "exit_code": -1
        }
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
    is_safe, reason = is_code_safe(code)
    if not is_safe:
        return f"FAIL: Safety check blocked execution\nReason: {reason}"

    result = run_in_docker(code)

    if result['success']:
        stdout_info = f"\nOutput:\n{result['stdout']}" if result['stdout'] else ""
        return f"PASS: Code executed successfully{stdout_info}"
    else:
        return f"FAIL: Execution failed\nError:\n{result['stderr']}"


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
validator_tool = [execute_code_tool]
