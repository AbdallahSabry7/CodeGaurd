import subprocess
import json
import os
import sys
import tempfile
import ast
import re
from radon.metrics import mi_visit
from radon.raw import analyze


def naming_quality_metrics(code: str):
    naming_issues = []
    score = 100
    try:
        tree = ast.parse(code)
    except Exception as e:
        return {
            "naming_score": 0,
            "issues": [{"name": "Syntax Error", "violation": f"Code parsing failed: {str(e)}"}]
        }

    is_snake = re.compile(r'^[a-z_][a-z0-9_]*$')
    is_camel = re.compile(r'^[A-Z][a-zA-Z0-9]*$')

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not is_snake.match(node.name):
                naming_issues.append({
                    "name": node.name,
                    "line": node.lineno,
                    "type": "function",
                    "violation": f"Function '{node.name}' should be snake_case"
                })
                score -= 20

        elif isinstance(node, ast.ClassDef):
            if not is_camel.match(node.name):
                naming_issues.append({
                    "name": node.name,
                    "line": node.lineno,
                    "type": "class",
                    "violation": f"Class '{node.name}' should be CamelCase (PascalCase)"
                })
                score -= 20

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id.isupper():
                        continue
                    if not is_snake.match(target.id):
                        naming_issues.append({
                            "name": target.id,
                            "line": node.lineno,
                            "type": "variable",
                            "violation": f"Variable '{target.id}' should be snake_case"
                        })
                        score -= 10

    return {"naming_score": max(0, score), "issues": naming_issues}


def analyze_code_string(code_string):

    results = {
        "naming_quality": {"naming_score": 100, "issues": []},
        "radon": {
            "maintainability_index": 100.0,
            "raw_metrics": {
                "total_lines_of_code": 0,
                "logical_lines_of_code": 0,
                "comments": 0
            }
        },
        "pylint": []
    }

    if not code_string.strip():
        return results

    # 1. Naming
    results["naming_quality"] = naming_quality_metrics(code_string)

    # 2. Radon
    try:
        mi = mi_visit(code_string, multi=True)
        raw = analyze(code_string)
        results["radon"] = {
            "maintainability_index": mi,
            "raw_metrics": {
                "total_lines_of_code": raw.loc,
                "logical_lines_of_code": raw.lloc,
                "comments": raw.comments
            }
        }
    except Exception as e:
        print(f"2. Radon: FAILED - {e}")

    # 3. Pylint — uses environment PATH, works for everyone
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as tmp:
            tmp.write(code_string)
            tmp_path = tmp.name

        process = subprocess.run(
            [sys.executable, "-m", "pylint", tmp_path,
            "--output-format=json", "--disable=all", "--enable=C,R,W",
            "--disable=C0114,C0116,C0115"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        if process.stdout:
            results["pylint"] = json.loads(process.stdout)
            print("3. Pylint: OK")

        os.remove(tmp_path)
    except Exception as e:
        print(f"3. Pylint: FAILED - {e}")

    return results