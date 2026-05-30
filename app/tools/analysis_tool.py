from langchain_core.tools import tool
from services import get_isp_report, get_lsp_report, get_ocp_report, get_dip_report, get_srp_report, analyze_code_string, estimate_complexity

import json

@tool
def analysis_tool(code: str) -> str:
    """
    Analyze a Python code snippet across three dimensions in a single call.
    Call this tool ONCE with the full source code. Do not call it multiple times.

    The tool returns three clearly labeled sections:

    === Complexity ===
    Time and space complexity estimates per function.

    === SOLID ===
    Violations of the five SOLID principles:
    - SRP: Single Responsibility — class/function does more than one job
    - OCP: Open/Closed — requires modification instead of extension
    - LSP: Liskov Substitution — subclass breaks parent contract
    - ISP: Interface Segregation — interface forces unused method implementation
    - DIP: Dependency Inversion — high-level modules depend on concrete classes

    === Clean Code ===
    Code smell score and issues: naming, function length, duplication,
    comments, formatting, and overall readability.

    Args:
        code: The full Python source code to analyze.

    Returns:
        A single string with all three labeled sections.
    """
    time_complexity, space_complexity = estimate_complexity(code)
    complexity_report = (
        f"Time Complexity: {time_complexity}\n"
        f"Space Complexity: {space_complexity}"
    )
    solid_results = {
        "SRP": get_srp_report(code),
        "OCP": get_ocp_report(code),
        "LSP": get_lsp_report(code),
        "ISP": get_isp_report(code),
        "DIP": get_dip_report(code),
    }
    clean_code_results = analyze_code_string(code)

    return (
        f"=== Complexity ===\n{complexity_report}\n\n"
        f"=== SOLID ===\n{json.dumps(solid_results, indent=2)}\n\n"
        f"=== Clean Code ===\n{clean_code_results}"
    )
