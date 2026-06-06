import re

from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AgentState
from prompts import (
    CPP_TO_PYTHON_PROMPT,
    PYTHON_TO_CPP_PROMPT,
    JAVA_TO_PYTHON_PROMPT,
    PYTHON_TO_JAVA_PROMPT,
    SYNTAX_ERROR_PROMPT,
)
from llms import LLM

_INTO_PYTHON = {"cpp": CPP_TO_PYTHON_PROMPT, "java": JAVA_TO_PYTHON_PROMPT}
_OUT_OF_PYTHON = {"cpp": PYTHON_TO_CPP_PROMPT, "java": PYTHON_TO_JAVA_PROMPT}


def _strip_fences(raw: str) -> str:
    fenced = re.search(r"```(?:[a-zA-Z+]+)?\s*\n(.*?)```", raw, re.DOTALL)
    return fenced.group(1).strip() if fenced else raw.strip()


def _run_translator(code: str, prompt: str, error: str | None = None):
    user = f"Code:\n{code}"
    if error:
        user += f"\n\nErrors:\n{error}"
    response = LLM.invoke([SystemMessage(content=prompt), HumanMessage(content=user)])
    if not response.content:
        raise ValueError("LLM did not return any content in the response.")
    return _strip_fences(response.content), response


def translate_to_python(state: AgentState) -> AgentState:
    """Front: user's language -> Python. Runs once, before analysis."""
    lang = state.get("source_language", "")
    error = state.get("translator_syntax_error")
    if lang == "python":
        return {"original_code_converted": state.get("original_code", "")}
    if lang not in _INTO_PYTHON:
        raise ValueError(f"Unsupported source language: {lang}")
    base = state.get("original_code_converted") if error else state.get("original_code", "")
    prompt = SYNTAX_ERROR_PROMPT if error else _INTO_PYTHON[lang]
    code, response = _run_translator(base, prompt, error)
    return {
        "messages": [response],
        "original_code_converted": code,
        "translator_syntax_error": None,
    }


def translate_from_python(state: AgentState) -> AgentState:
    """Back: Python -> user's language. Runs once, after refactoring is done."""
    lang = state.get("source_language", "")
    error = state.get("translator_syntax_error")
    if lang == "python":
        return {}
    if lang not in _OUT_OF_PYTHON:
        raise ValueError(f"Unsupported target language: {lang}")
    prompt = SYNTAX_ERROR_PROMPT if error else _OUT_OF_PYTHON[lang]
    code, response = _run_translator(state.get("refactored_code", ""), prompt, error)
    return {
        "messages": [response],
        "refactored_code": code,
        "translator_code": code,
        "translator_syntax_error": None,
    }