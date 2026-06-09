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


import re

SUPPORTED = {"python", "java", "cpp"}

# ----------------------------------------------------------------------
# Tunable decision parameters
# ----------------------------------------------------------------------
MIN_SCORE = 3        # below this -> unknown (no real signal)
MARGIN_OK = 3        # absolute lead over the runner-up that is "safe"
DOMINANCE = 0.55     # OR: best/(sum of positive scores) above this -> safe
UNSUPPORTED_MIN = 2  # distinct unsupported signals required to flag it

# ----------------------------------------------------------------------
# Noise stripping
# ----------------------------------------------------------------------
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_SLASH = re.compile(r"//[^\n]*")
_DQ_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"')
_SQ_STRING = re.compile(r"'(?:\\.|[^'\\\n])*'")
_TRIPLE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'', re.DOTALL)
_PREPROC = re.compile(
    r"#\s*(include|define|pragma|ifndef|ifdef|endif|undef|error|line)\b"
)


def _strip_noise(code: str) -> str:
    # Triple-quoted python strings / docstrings first
    code = _TRIPLE.sub('""', code)
    # Block comments /* ... */
    code = _BLOCK_COMMENT.sub(" ", code)
    # Normal single/double quoted strings -> keep the quotes so prefixes (f", etc.) survive
    code = _DQ_STRING.sub('""', code)
    code = _SQ_STRING.sub("''", code)
    # // line comments
    code = _LINE_COMMENT_SLASH.sub(" ", code)
    # '#' comments: drop them, BUT preserve C/C++ preprocessor directives
    out_lines = []
    for line in code.split("\n"):
        hidx = line.find("#")
        if hidx == -1:
            out_lines.append(line)
            continue
        stripped = line[hidx:].lstrip("#").strip()
        # is it a preprocessor directive?
        if _PREPROC.match(line[hidx:].replace(" ", "", 0)) or _PREPROC.match(line.strip()):
            out_lines.append(line)  # keep whole line
        else:
            out_lines.append(line[:hidx])  # cut the comment
    return "\n".join(out_lines)


def _c(pattern: str):
    return re.compile(pattern, re.MULTILINE)


# ----------------------------------------------------------------------
# Positive signals:  (compiled_regex, weight, occurrence_cap)
# ----------------------------------------------------------------------
_SIGNALS = {
    "cpp": [
        (_c(r"#include\s*[<\"]"),                       12, 2),
        (_c(r"\busing\s+namespace\s+std\b"),            10, 1),
        (_c(r"\bstd::"),                                 7, 3),
        (_c(r"\bcout\s*<<"),                             9, 2),
        (_c(r"\bcin\s*>>"),                              9, 2),
        (_c(r"\bendl\b"),                                4, 2),
        (_c(r"\bnullptr\b"),                             6, 1),
        (_c(r"\btemplate\s*<"),                          7, 1),
        (_c(r"\bvirtual\b"),                             5, 2),
        (_c(r"\boverride\b"),                            4, 2),
        (_c(r"#define\b|#pragma\b|#ifndef\b"),           6, 2),
        (_c(r"^\s*(public|private|protected)\s*:\s*$"),  6, 2),
        (_c(r"\bint\s+main\s*\("),                       6, 1),
        (_c(r"\b(vector|map|set|pair|string)\s*<"),      5, 3),
        (_c(r"\b(int|void|bool|double|char|float|auto)\s+\w+\s*\([^;{}]*\)\s*(const)?\s*\{"), 4, 2),
        (_c(r"->"),                                      1, 3),
        (_c(r"::"),                                      2, 3),
        (_c(r"\bprintf\s*\(|\bscanf\s*\("),              2, 2),
        (_c(r"\bclass\s+\w+[^:\n{]*\{"),                 5, 2),
        (_c(r"\}\s*;\s*$"),                              3, 2),
    ],
    "java": [
        (_c(r"\bpublic\s+class\s+\w+"),                  11, 1),
        (_c(r"\bpublic\s+static\s+void\s+main\s*\("),    11, 1),
        (_c(r"\bimport\s+java\."),                       11, 2),
        (_c(r"\bimport\s+javax\."),                       9, 2),
        (_c(r"^\s*package\s+[\w.]+\s*;"),                 7, 1),
        (_c(r"\bSystem\.out\.print"),                     9, 2),
        (_c(r"@Override|@Autowired|@Entity|@SpringBootApplication|@RestController|@Test"), 7, 2),
        (_c(r"\b(extends|implements)\b"),                 4, 2),
        (_c(r"\bString\s*\[\s*\]\s*\w+"),                 6, 1),
        (_c(r"\b(String|Integer|Boolean|Double|ArrayList|HashMap|List|Map|Optional)\b"), 3, 3),
        (_c(r"\b(public|private|protected)\s+(static\s+)?(final\s+)?[\w<>\[\]]+\s+\w+\s*[;=(]"), 4, 3),
        (_c(r"\bnew\s+\w+\s*\("),                         2, 2),
        (_c(r"\bvoid\s+\w+\s*\([^;{}]*\)\s*\{"),          3, 2),
        (_c(r"\bfinal\b"),                                2, 2),
        (_c(r"\bnull\b"),                                 1, 2),
    ],
    "python": [
        (_c(r"^\s*(async\s+)?def\s+\w+\s*\("),            8, 3),
        (_c(r"^\s*class\s+\w+\s*[:(]"),                   7, 2),
        (_c(r"^\s*from\s+[\w.]+\s+import\b"),             9, 2),
        (_c(r"^\s*import\s+\w+(\s*$|\s+as\b|\s*,)"),       5, 3),
        (_c(r"\b__init__\b"),                             7, 1),
        (_c(r"__name__\s*==\s*[\"']__main__[\"']"),       10, 1),
        (_c(r"\bself\b"),                                 5, 3),
        (_c(r"\bprint\s*\("),                             4, 3),
        (_c(r"\belif\b"),                                 7, 2),
        (_c(r"\b(None|True|False)\b"),                    3, 3),
        (_c(r"^\s*@\w+\s*$"),                             3, 2),
        (_c(r"\blambda\b"),                               4, 1),
        (_c(r"\bdef\s+__\w+__\b"),                        4, 2),
        (_c(r"\b\w+\s*:\s*(int|str|float|bool|list|dict|List|Dict|Optional|Tuple|Set)\b"), 4, 3),
        (_c(r"\)\s*->\s*[\w\[\], .]+:"),                   6, 1),
        (_c(r"^\s*(if|for|while|with|try|except|finally|else|elif)\b.*:\s*$"), 3, 4),
        (_c(r"\bprint\b(?!\s*\()"),                       1, 1),
    ],
}

# ----------------------------------------------------------------------
# Negative / cross-penalty signals: (regex, lang_to_penalize, penalty, cap)
# ----------------------------------------------------------------------
_NEGATIVE = [
    (_c(r"#include"),                 "python", -12, 1),
    (_c(r"#include"),                 "java",   -12, 1),
    (_c(r"\bstd::"),                  "python", -8, 1),
    (_c(r"\bstd::"),                  "java",   -8, 1),
    (_c(r"\b(cout|cin|endl|nullptr)\b"), "python", -6, 1),
    (_c(r"\b(cout|cin|endl|nullptr)\b"), "java",   -6, 1),
    (_c(r"\bimport\s+java\."),        "python", -10, 1),
    (_c(r"\bimport\s+java\."),        "cpp",    -10, 1),
    (_c(r"\bSystem\.out"),            "python", -6, 1),
    (_c(r"\bSystem\.out"),            "cpp",    -6, 1),
    (_c(r"^\s*def\s+\w+"),            "java",   -8, 1),
    (_c(r"^\s*def\s+\w+"),            "cpp",    -6, 1),
    (_c(r"\belif\b"),                 "java",   -5, 1),
    (_c(r"\belif\b"),                 "cpp",    -5, 1),
    (_c(r"\bpublic\s+class\b"),       "python", -6, 1),
    (_c(r";\s*$"),                    "python", -2, 3),
    (_c(r"\}\s*$"),                   "python", -1, 3),
]

# ----------------------------------------------------------------------
# Unsupported-language signals (decisive tokens)
# ----------------------------------------------------------------------
# Each entry is (pattern, weight). Weights let distinctive tokens (e.g. php
# `<?php`, rust `println!`, go `package main`) decisively outweigh tokens that
# overlap a supported language (e.g. ruby/swift `def`/`func`).
_UNSUPPORTED_SIGNALS = {
    "kotlin":     [(r"\bfun\s+\w+\s*\(", 5), (r"\bval\s+\w+", 3), (r"\bvar\s+\w+\s*[:=]", 3), (r"\bdata\s+class\b", 8), (r"\bobject\s+\w+", 4), (r"\bprintln\s*\(", 4)],
    "rust":       [(r"\bfn\s+\w+\s*\(", 5), (r"\blet\s+mut\b", 7), (r"\bimpl\s+\w+", 6), (r"println!\s*\(", 8), (r"\buse\s+std::", 6), (r"\bpub\s+fn\b", 6), (r"->\s*Result<", 6)],
    "go":         [(r"\bfunc\s+\w+\s*\(", 4), (r"\bpackage\s+main\b", 9), (r"\w+\s*:=\s*", 5), (r"\bfmt\.", 6), (r"\bimport\s*\(", 4)],
    "javascript": [(r"\bconst\s+\w+\s*=", 3), (r"\blet\s+\w+\s*=", 3), (r"=>\s*[{(\w]", 4), (r"console\.log", 7), (r"\brequire\s*\(", 4), (r"\bfunction\s+\w+\s*\(", 4)],
    "typescript": [(r":\s*(string|number|boolean)\s*[=;,)]", 4), (r"\binterface\s+\w+\s*\{", 6), (r"\btype\s+\w+\s*=", 4), (r"\bexport\s+(class|const|function|interface)\b", 5)],
    "ruby":       [(r"\bdef\s+\w+", 2), (r"\bputs\b", 5), (r"^\s*end\s*$", 4), (r"\battr_accessor\b", 6), (r"\brequire\s+[\"']", 4), (r"\.each\s+do\b", 5)],
    "csharp":     [(r"\bnamespace\s+\w+", 5), (r"\busing\s+System", 8), (r"Console\.Write", 8), (r"\bpublic\s+static\s+void\s+Main", 9), (r"\bvar\s+\w+\s*=", 2), (r"\bstring\[\]\s+args", 3)],
    "swift":      [(r"\bguard\s+.+\belse\b", 6), (r"\bfunc\s+\w+[^\n]*->\s*\w+", 6), (r"\blet\s+\w+\s*=", 2), (r"\bvar\s+\w+\s*:\s*\w+", 3)],
    "php":        [(r"<\?php", 10), (r"\$\w+\s*=", 4), (r"\becho\b", 4), (r"->\w+\s*\(", 2)],
}
_UNSUPPORTED_COMPILED = {
    lang: [(re.compile(p, re.MULTILINE), w) for p, w in pats]
    for lang, pats in _UNSUPPORTED_SIGNALS.items()
}

# Tokens that strongly belong to a SUPPORTED language; used to suppress
# false unsupported flags (e.g. a python file that mentions "func" in a string).
_SUPPORTED_GUARD = re.compile(r"#include|\bstd::|import\s+java\.|System\.out\.print|__main__|\bself\.", re.MULTILINE)


def _count(pattern, text, cap):
    n = len(pattern.findall(text))
    return min(n, cap)


def detect_language_core(code: str) -> dict:
    """Pure detection logic. Returns the same dict shape as the graph node."""
    if not code or not code.strip():
        return {"source_language": "unknown"}

    text = _strip_noise(code)

    # -- Score supported languages --
    scores = {"python": 0, "java": 0, "cpp": 0}
    for lang, signals in _SIGNALS.items():
        for pattern, weight, cap in signals:
            scores[lang] += weight * _count(pattern, text, cap)
    for pattern, lang, penalty, cap in _NEGATIVE:
        scores[lang] += penalty * _count(pattern, text, cap)

    best = max(scores, key=scores.get)
    best_score = scores[best]
    ordered = sorted(scores.values(), reverse=True)
    gap = ordered[0] - ordered[1]
    positive_sum = sum(s for s in scores.values() if s > 0) or 1
    dominance = best_score / positive_sum if best_score > 0 else 0

    # -- Unsupported detection (weighted) --
    unsupported_lang, unsupported_score, unsupported_hits = None, 0, 0
    for lang, patterns in _UNSUPPORTED_COMPILED.items():
        score, hits = 0, 0
        for pattern, weight in patterns:
            if pattern.search(text):
                score += weight
                hits += 1
        if score > unsupported_score:
            unsupported_lang, unsupported_score, unsupported_hits = lang, score, hits

    guarded = bool(_SUPPORTED_GUARD.search(text))
    supported_confident = best_score >= MIN_SCORE and (
        gap >= MARGIN_OK or dominance >= DOMINANCE or best_score >= 8
    )

    # An unsupported language wins when it has at least UNSUPPORTED_MIN distinct
    # signals AND its weighted evidence is at least as strong as the best
    # supported score -- unless a decisive supported token is present.
    if (
        unsupported_lang
        and unsupported_hits >= UNSUPPORTED_MIN
        and unsupported_score >= best_score
        and not guarded
    ):
        return {"source_language": "unsupported", "detected_language": unsupported_lang}

    # -- Resolve supported --
    if not supported_confident:
        return {"source_language": "unknown"}

    if best == "python":
        return {"source_language": "python"}
    if best == "java":
        return {"source_language": "java", "destination_language": "python"}
    if best == "cpp":
        return {"source_language": "cpp", "destination_language": "python"}
    return {"source_language": "unknown"}


def detect_language(state) -> dict:
    """Graph-node entry point (kept signature-compatible with the original)."""
    code = state.get("original_code", "") if hasattr(state, "get") else getattr(state, "original_code", "")
    return detect_language_core(code or "")
    

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

