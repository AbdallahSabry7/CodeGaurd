import ast

from schemas import AgentState
from tools import analysis_tool, execute_code_tool , score_report, ConvergenceController , differential_check
import re


def validate_translator_code(state: AgentState) -> dict:
	iterations = state.get("refactor_iterations", 0)
	code = (state.get("original_code_converted", "") if iterations == 0
			else (state.get("refactored_code")[-1] if state.get("refactored_code") else ""))
	try:
		ast.parse(code)
		return {"translator_syntax_error": None}
	except SyntaxError as e:
		return {
			"translator_syntax_error": f"SyntaxError at line {e.lineno}: {e.msg}",
			"syntax_iterations": state.get("syntax_iterations", 0) + 1,   
		}

def validate_refactored_code(state: AgentState) -> dict:
    if state.get("refactored_code"):
        code = state["refactored_code"][-1]
    else:
        code = ""
    try:
        ast.parse(code)
        return {"refactor_syntax_error": None}
    except SyntaxError as e:
        return {"refactor_syntax_error": f"SyntaxError at line {e.lineno}: {e.msg}"}

def analyzer_function(state: AgentState) -> str:
    if state.get("refactored_code"):
        code_to_analyze = state["refactored_code"][-1]
    elif state.get("original_code_converted"):
        code_to_analyze = state["original_code_converted"]
    else:
        code_to_analyze = state["original_code"]

    iterations = state.get("refactor_iterations", 0)
    response = analysis_tool.invoke({"code": code_to_analyze})
    if iterations == 0:
        return {"analyzer_report": response, "original_analyzer_report": response}
    else:
        return {"analyzer_report": response }
    
def executer_function(state: AgentState) -> str:
    if state.get("refactored_code"):
        code_to_execute = state["refactored_code"][-1]
    elif state.get("original_code_converted"):
        code_to_execute = state["original_code_converted"]
    else:
        code_to_execute = state["original_code"]
    response = execute_code_tool.invoke({"code": code_to_execute})
    return {"execution_result": response}


SUPPORTED = {"python", "java", "cpp"}

UNSUPPORTED_SIGNALS = {
    "kotlin":     [r'\bfun\s+\w+\s*\(', r'\bval\s+\w+', r'\bvar\s+\w+', r'\bdata\s+class\b', r'\bobject\s+\w+'],
    "rust":       [r'\bfn\s+\w+\s*\(', r'\blet\s+mut\b', r'\bimpl\s+\w+', r'println!\s*\(', r'\buse\s+std::'],
    "go":         [r'\bfunc\s+\w+\s*\(', r'\bpackage\s+main\b', r'\w+\s*:=\s*\w+', r'\bfmt\.'],
    "javascript": [r'\bconst\s+\w+\s*=', r'\blet\s+\w+\s*=', r'=>\s*[{\w]', r'console\.log', r'\brequire\s*\('],
    "typescript": [r':\s*(string|number|boolean)\s*[=;,)]', r'\binterface\s+\w+\s*\{', r'\btype\s+\w+\s*='],
    "ruby":       [r'\bdef\s+\w+.*\n.*\bend\b', r'\bputs\s+', r'^\s*end\s*$', r'\battr_accessor\b'],
    "csharp":     [r'\bnamespace\s+\w+', r'\busing\s+System', r'Console\.Write', r'\bpublic\s+static\s+void\s+Main'],
    "swift":      [r'\bguard\s+.+\belse\b', r'\bvar\s+\w+\s*:\s*\w+', r'\bfunc\s+\w+.*->\s*\w+', r'\boptional\b'],
}

# Compiled once at module load — avoids recompiling on every call
_UNSUPPORTED_COMPILED = {
    lang: [re.compile(p, re.MULTILINE) for p in patterns]
    for lang, patterns in UNSUPPORTED_SIGNALS.items()
}

_SUPPORTED_SIGNALS = {
    # (pattern, language, score)
    "cpp": [
        # ... your existing patterns ...
        (re.compile(r'^\s*(public|private|protected)\s*:\s*$', re.MULTILINE), 9),  # access-specifier labels
        (re.compile(r'\bvirtual\b'),                                          7),
        (re.compile(r'\boverride\b'),                                         7),
        (re.compile(r'\)\s*const\b'),                                         6),  # const member fns
        (re.compile(r':\s*(public|private|protected)\s+\w+'),                 7),  # C++ inheritance
        (re.compile(r'\bclass\s+\w+[^:{\n]*\{'),                              7),  # "class X {" (brace, not colon)
        (re.compile(r'\}\s*;\s*$', re.MULTILINE),                             5),  # class/struct close "};"
    ],
    "java": [
        (re.compile(r'\bpublic\s+class\s+\w+'),                  10),
        (re.compile(r'public\s+static\s+void\s+main'),           10),
        (re.compile(r'\bimport\s+java\.'),                        10),
        (re.compile(r'System\.out\.print'),                        8),
        (re.compile(r'@Override|@Autowired|@Entity'),              8),
        (re.compile(r'\bextends\b|\bimplements\b'),                6),
        (re.compile(r'(private|public|protected)\s+\w+\s+\w+\s*[;(=]'), 5),
        (re.compile(r'new\s+\w+\s*\('),                            2),
    ],
    "python": [
        # ... keep def/from/self/class patterns ...
        # block headers only — not any trailing colon:
        (re.compile(r'^\s*(def|class|if|elif|else|for|while|try|except|finally|with)\b.*:\s*$', re.MULTILINE), 6),
        # type hints: a name : type, but NOT an access specifier label:
        (re.compile(r'\b(?!public|private|protected)\w+\s*:\s*(int|str|float|bool|list|dict)\b'), 5),
        (re.compile(r'\bprint\s*\('), 3),
        # drop "^\s{4}\w+" entirely — every brace language indents too
    ],
}

_NEGATIVE_SIGNALS = [
    # (pattern, language_to_penalize, penalty)
    (re.compile(r'#include'),                    "python", -10),
    (re.compile(r'#include'),                    "java",   -10),
    (re.compile(r'^\s*def\s+\w+',re.MULTILINE), "java",    -8),
    (re.compile(r'^\s*def\s+\w+',re.MULTILINE), "cpp",     -5),
    (re.compile(r'System\.out'),                 "python",  -8),
    (re.compile(r'\bstd::'),                     "python",  -8),
    (re.compile(r'\bstd::'),                     "java",    -8),
    (re.compile(r'System\.out\.print'),          "cpp",     -8),
    (re.compile(r'\bimport\s+java\.'),           "python", -10),
    (re.compile(r'\bimport\s+java\.'),           "cpp",    -10),
]

_NEGATIVE_SIGNALS += [
    (re.compile(r';\s*$', re.MULTILINE),                                  "python", -6),  # statement terminators
    (re.compile(r'\}\s*;', re.MULTILINE),                                 "python", -6),  # "};"
    (re.compile(r'\{\s*$', re.MULTILINE),                                 "python", -4),  # block opener
    (re.compile(r'\boverride\b'),                                         "python", -8),
    (re.compile(r'\bvirtual\b'),                                          "python", -8),
    (re.compile(r'^\s*(public|private|protected)\s*:\s*$', re.MULTILINE), "python", -8),
]



def detect_language(state: AgentState) -> dict:
    code = state.get("original_code", "")

    # ── Empty input ───────────────────────────────────────────────
    if not code.strip():
        return {"source_language": "unknown"}

    # ── Step 1: check unsupported languages ───────────────────────
    unsupported_lang = None
    unsupported_hits = 0
    for lang, patterns in _UNSUPPORTED_COMPILED.items():
        hits = sum(1 for p in patterns if p.search(code))
        if hits >= 2 and hits > unsupported_hits:
            unsupported_lang = lang
            unsupported_hits = hits

    # ── Step 2: score supported languages ────────────────────────
    scores = {"python": 0, "java": 0, "cpp": 0}
    for lang, signals in _SUPPORTED_SIGNALS.items():
        for pattern, weight in signals:
            if pattern.search(code):
                scores[lang] += weight
    for pattern, lang, penalty in _NEGATIVE_SIGNALS:
        if pattern.search(code):
            scores[lang] += penalty  # penalty is already negative

    best = max(scores, key=scores.get)
    best_score = scores[best]
    sorted_scores = sorted(scores.values(), reverse=True)
    gap = sorted_scores[0] - sorted_scores[1]

    # ── Step 3: resolve ───────────────────────────────────────────
    if unsupported_lang:
        # Unsupported signal wins unless a supported language is
        # clearly dominant (high score + big gap)
        if best_score < 8 or gap < 4:
            return {
                "source_language": "unsupported",
            }

    if best_score < 8:
        return {
            "source_language": "unknown",
        }

    if gap < 4:
        return {
            "source_language": "unknown",
        }
    if best in SUPPORTED:
        if best == "python":
            return {"source_language": "python"}
        elif best == "java":
            return {"source_language": "java", "destination_language": "python"}
        elif best == "cpp":
            return {"source_language": "cpp", "destination_language": "python"}
    

controller = ConvergenceController()   # inject via config for DIP

def convergence_node(state: AgentState) -> dict:
    """Deterministic: score the latest report, append to history, count the loop."""
    latest = score_report(state["architect_report"]).total
    history = list(state.get("quality_scores", []))
    history.append(latest)
    return {
        "quality_scores": history,
        "improvement_loops": state.get("improvement_loops", 0)
    }

def regression_check_node(state: AgentState) -> dict:
	refactored = state["refactored_code"][-1] if state.get("refactored_code") else ""
	if not refactored:
		# Nothing was changed (or the only change was undone) → original is the answer.
		return {"regression_verdict": "SAME", "regression_report": "No refactor to verify."}
	original = state.get("original_code_converted") or state["original_code"]
	cases = state.get("test_inputs") or []
	if not cases:
		print("[regression] WARNING: characterizer produced 0 cases — nothing to check")
	result = differential_check(
		original=original,
		refactored=refactored,
		cases=cases,
		mode=state.get("test_mode", "stdio"),
		driver=state.get("test_driver", ""),
	)
	return {"regression_verdict": result.verdict, "regression_report": result.report}

def destroy_last_node(state: AgentState) -> dict:
    if not state.get("refactored_code"):
        return {}
    return {
        "refactored_code": state["refactored_code"][:-1],
        "quality_scores": state.get("quality_scores", [])[:-1],
    }

