from __future__ import annotations
import ast
import json
import re
import os
import tempfile
import shutil
from langchain_core.tools import tool
from ISP_detect import get_isp_report
from Liskov_Substitution_Principle import get_lsp_report
from OCP_Detection_Final import get_ocp_report
from dependancy_principle import get_dip_report
from SRP_Detection_Final import get_srp_report
from clean_code import analyze_code_string
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import docker
import docker.errors


DOCKER_IMAGE = "python:3.11-slim"
OUTPUT_LIMIT = 4_000
TIMEOUT_SEC  = 10
MEM_LIMIT    = "128m"
CPU_QUOTA    = 50_000
PIDS_LIMIT   = 64

BLOCKED_PATTERNS: list[str] = [
    "import os", "import sys", "import subprocess", "import socket",
    "import requests", "import urllib", "import http", "import ftplib",
    "import smtplib", "import shutil", "__import__", "open(", "eval(",
    "exec(", "compile(", "globals(", "locals(", "vars(", "getattr(",
    "setattr(", "delattr(", "breakpoint(", "input(", "importlib",
    "ctypes", "pickle", "marshal", "pty", "popen", "Popen",
]


class FailReason(str, Enum):
    SAFETY_BLOCKED   = "safety_blocked"
    SYNTAX_ERROR     = "syntax_error"
    TIMEOUT          = "timeout"
    OOM_KILLED       = "oom_killed"
    RUNTIME_ERROR    = "runtime_error"
    DOCKER_UNAVAIL   = "docker_unavailable"
    IMAGE_NOT_FOUND  = "image_not_found"
    DOCKER_API_ERROR = "docker_api_error"
    IO_ERROR         = "io_error"
    UNEXPECTED       = "unexpected"
    EMPTY_CODE       = "empty_code"

@dataclass
class ExecutionResult:
    success:     bool
    stdout:      str                  = ""
    stderr:      str                  = ""
    exit_code:   int                  = 0
    fail_reason: Optional[FailReason] = None
    notes:       list[str]            = field(default_factory=list)

    @classmethod
    def ok(cls, stdout: str = "", stderr: str = "") -> "ExecutionResult":
        return cls(success=True, stdout=stdout, stderr=stderr, exit_code=0)

    @classmethod
    def fail(
        cls,
        reason: FailReason,
        stderr: str = "",
        stdout: str = "",
        exit_code: int = -1,
        notes: Optional[list[str]] = None,
    ) -> "ExecutionResult":
        return cls(
            success=False,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            fail_reason=reason,
            notes=notes or [],
        )

    def to_tool_string(self) -> str:
        if self.success:
            out = "PASS: Code executed successfully (exit 0)"
            if self.stdout.strip():
                out += f"\nOutput:\n{self.stdout}"
            if self.stderr.strip():
                out += f"\nWarnings:\n{self.stderr}"
            return out

        hints = {
            FailReason.TIMEOUT:         "Check for infinite loops or blocking calls.",
            FailReason.OOM_KILLED:      "Code used too much memory.",
            FailReason.SAFETY_BLOCKED:  "Code was blocked by the safety filter.",
            FailReason.SYNTAX_ERROR:    "Fix syntax errors before running.",
            FailReason.DOCKER_UNAVAIL:  "Docker daemon is not running or not accessible.",
            FailReason.IMAGE_NOT_FOUND: f"Run: docker pull {DOCKER_IMAGE}",
            FailReason.EMPTY_CODE:      "No code was provided.",
        }

        parts = [f"FAIL [{self.fail_reason.value}] (exit {self.exit_code})"]

        if self.fail_reason in hints:
            parts.append(f"Hint: {hints[self.fail_reason]}")
        if self.notes:
            parts.append("Notes: " + " | ".join(self.notes))
        if self.stdout.strip():
            parts.append(f"Stdout:\n{self.stdout}")
        if self.stderr.strip():
            parts.append(f"Stderr:\n{self.stderr}")

        return "\n".join(parts)

def _strip_fences(code: str) -> str:
    fenced = re.search(r"```(?:python)?\s*\n(.*?)```", code, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return code.strip()

def is_code_safe(code: str) -> tuple[bool, str]:
    if not code or not code.strip():
        return False, "empty_code"

    if "\x00" in code:
        return False, "Code contains null bytes"

    code_lower = code.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in code or pattern.lower() in code_lower:
            return False, f"Blocked pattern: '{pattern}'"

    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except ValueError as e:
        return False, f"Invalid code: {e}"

    return True, "OK"

def _decode(data: Optional[bytes]) -> str:
    if not data:
        return ""
    return data.decode("utf-8", errors="replace")

def _truncate(text: str, label: str = "") -> str:
    if len(text) > OUTPUT_LIMIT:
        suffix = f"\n[{label} truncated at {OUTPUT_LIMIT} chars]" if label else "\n[truncated]"
        return text[:OUTPUT_LIMIT] + suffix
    return text

def run_in_docker(code: str) -> ExecutionResult:
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as e:
        return ExecutionResult.fail(
            FailReason.DOCKER_UNAVAIL,
            stderr=f"Cannot connect to Docker daemon: {e}",
        )

    temp_dir  = tempfile.mkdtemp(prefix="codeguard_")
    temp_file = os.path.join(temp_dir, "code_to_test.py")

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
    except OSError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return ExecutionResult.fail(FailReason.IO_ERROR, stderr=f"Cannot write temp file: {e}")

    container = None
    try:
        try:
            container = client.containers.run(
                image=DOCKER_IMAGE,
                command=["python", "-u", "/code/code_to_test.py"],
                volumes={temp_dir: {"bind": "/code", "mode": "ro"}},
                mem_limit=MEM_LIMIT,
                memswap_limit=MEM_LIMIT,
                cpu_quota=CPU_QUOTA,
                pids_limit=PIDS_LIMIT,
                network_disabled=True,
                read_only=True,
                detach=True,
                stderr=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
            )
        except docker.errors.ImageNotFound:
            return ExecutionResult.fail(
                FailReason.IMAGE_NOT_FOUND,
                stderr=f"Image '{DOCKER_IMAGE}' not found.",
            )
        except docker.errors.APIError as e:
            return ExecutionResult.fail(FailReason.DOCKER_API_ERROR, stderr=f"API error: {e}")
        wait_result: dict    = {}
        wait_exception: list = []

        def _wait():
            try:
                wait_result["res"] = container.wait()
            except Exception as exc:
                wait_exception.append(exc)

        waiter = threading.Thread(target=_wait, daemon=True)
        waiter.start()
        waiter.join(timeout=TIMEOUT_SEC)

        if waiter.is_alive():
            try:
                container.kill()
            except Exception:
                pass
            return ExecutionResult.fail(
                FailReason.TIMEOUT,
                stderr=f"Container killed after {TIMEOUT_SEC}s timeout.",
                exit_code=-1,
            )

        if wait_exception:
            return ExecutionResult.fail(
                FailReason.UNEXPECTED,
                stderr=f"Error waiting for container: {wait_exception[0]}",
            )

        exit_code = wait_result["res"].get("StatusCode", 1)
        stdout    = _truncate(_decode(container.logs(stdout=True,  stderr=False)), "stdout")
        stderr    = _truncate(_decode(container.logs(stdout=False, stderr=True)),  "stderr")

        notes = []
        try:
            state = client.api.inspect_container(container.id).get("State", {})
            if state.get("OOMKilled"):
                return ExecutionResult.fail(
                    FailReason.OOM_KILLED,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    notes=["Container was OOM-killed — exceeded memory limit."],
                )
            if state.get("Error"):
                notes.append(f"Container error: {state['Error']}")
        except Exception:
            pass

        if exit_code == 0:
            return ExecutionResult.ok(stdout=stdout, stderr=stderr)

        return ExecutionResult.fail(
            FailReason.RUNTIME_ERROR,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            notes=notes,
        )

    except docker.errors.DockerException as e:
        return ExecutionResult.fail(FailReason.DOCKER_API_ERROR, stderr=f"Docker error: {e}")

    except Exception as e:
        return ExecutionResult.fail(
            FailReason.UNEXPECTED,
            stderr=f"{type(e).__name__}: {e}",
        )

    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)

@tool
def execute_code_tool(code: str) -> str:
    """
    Execute Python code in a secure Docker container and return the result.

    Args:
        code: Python source code to execute (plain or markdown-fenced)

    Returns:
        String describing execution result with PASS/FAIL and details
    """
    code = _strip_fences(code)

    is_safe, reason = is_code_safe(code)
    if not is_safe:
        fail_reason = (
            FailReason.EMPTY_CODE       if reason == "empty_code"
            else FailReason.SYNTAX_ERROR    if reason.startswith("SyntaxError")
            else FailReason.SAFETY_BLOCKED
        )
        return ExecutionResult.fail(fail_reason, stderr=reason).to_tool_string()

    return run_in_docker(code).to_tool_string()


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