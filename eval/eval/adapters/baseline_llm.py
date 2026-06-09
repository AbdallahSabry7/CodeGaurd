"""Raw-LLM baseline: a single prompt, NO AST detectors, NO verification.

This is baseline (a) from the evaluation plan -- the thing CodeGuard must beat.
It talks to Groq / OpenRouter via the OpenAI-compatible Chat Completions API
using only the standard library (urllib), so it has zero extra dependencies.

Improvements vs the original baseline
-------------------------------------
* Response CACHING + raw-output LOGGING (results/logs/) so a baseline run is
  reproducible and auditable -- the README's reproducibility claim was false
  for the baseline before, because it called a live, non-deterministic LLM with
  no record of what came back.
* Optional FAIR chain-of-thought mode (BASELINE_COT=1): the original forced the
  model to emit a bare label with no reasoning, which handicaps the baseline and
  invites the 'you beat a strawman' critique. With CoT on, the model may reason
  and we extract the final answer.
* The offline stub is unchanged in spirit but clearly flagged as NOT a baseline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from harness.io_utils import LOGS_DIR, ensure_logs_dir


class LLMUnavailable(RuntimeError):
    pass


def _provider_config():
    """Return (base_url, api_key, model) from env, or None if unavailable."""
    openrouter = os.getenv("OPENROUTER_API_KEY")
    groq = os.getenv("GROQ_API_KEY")
    model = os.getenv("BASELINE_MODEL")
    if openrouter:
        return (
            os.getenv("openai_api_base", "https://openrouter.ai/api/v1"),
            openrouter,
            model or "openai/gpt-oss-120b",
        )
    if groq:
        return ("https://api.groq.com/openai/v1", groq, model or "llama-3.3-70b-versatile")
    return None


def _cot() -> bool:
    return os.getenv("BASELINE_COT", "0") == "1"


def _require_real() -> bool:
    return os.getenv("CODEGUARD_EVAL_REQUIRE_LLM", "0") == "1"


# --- caching / logging -----------------------------------------------------

_CACHE = None


def _cache_path() -> str:
    return os.path.join(LOGS_DIR, "llm_cache.json")


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    ensure_logs_dir()
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    except (OSError, json.JSONDecodeError):
        _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    if _CACHE is None:
        return
    ensure_logs_dir()
    with open(_cache_path(), "w", encoding="utf-8") as fh:
        json.dump(_CACHE, fh)


def _log_raw(key: str, prompt: str, response: str) -> None:
    ensure_logs_dir()
    with open(os.path.join(LOGS_DIR, "llm_raw.log"), "a", encoding="utf-8") as fh:
        fh.write(f"### {key}\n--- prompt ---\n{prompt}\n--- response ---\n{response}\n\n")


def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 1200) -> str:
    cfg = _provider_config()
    if cfg is None:
        raise LLMUnavailable("No OPENROUTER_API_KEY or GROQ_API_KEY in environment")
    base_url, api_key, model = cfg

    cache = _load_cache()
    ckey = hashlib.sha256(
        json.dumps({"m": model, "t": temperature, "mt": max_tokens, "msgs": messages}, sort_keys=True).encode()
    ).hexdigest()
    if ckey in cache:
        return cache[ckey]

    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) codeguard-eval/2.0",
        },
        method="POST",
    )
    last_err = None
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                cache[ckey] = content
                _save_cache()
                _log_raw(ckey, json.dumps(messages)[:2000], content)
                return content
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code != 429:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                delay = float(retry_after) if retry_after else float(min(2 ** attempt, 60))
            except (TypeError, ValueError):
                delay = float(min(2 ** attempt, 60))
            time.sleep(delay + 0.5)
    raise last_err


def _extract_json(text: str):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Task-specific baseline predictors
# ---------------------------------------------------------------------------

VALID_TIERS = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)", "O(2^n)", "O(n!)"]


def predict_complexity(code: str) -> str:
    if _cot():
        prompt = (
            "Determine the dominant worst-case time complexity of the function. "
            "Think briefly step by step, then on the FINAL line output exactly "
            "'ANSWER: <tier>' where <tier> is one of: " + ", ".join(VALID_TIERS)
            + ".\n\nCODE:\n" + code
        )
    else:
        prompt = (
            "You are a complexity analyzer. Reply with ONLY the dominant worst-case "
            "time complexity of the function, chosen from this exact list: "
            + ", ".join(VALID_TIERS) + ". Reply with the bare label, nothing else.\n\nCODE:\n" + code
        )
    try:
        out = _chat([{"role": "user", "content": prompt}]).strip()
        if _cot():
            m = re.search(r"ANSWER:\s*(.+)$", out, re.MULTILINE)
            out = (m.group(1).strip() if m else out)
        for tier in VALID_TIERS:
            if tier.lower() in out.lower():
                return tier
        return out
    except (LLMUnavailable, urllib.error.URLError, KeyError):
        if _require_real():
            raise
        return _stub_complexity(code)


def predict_solid(code: str, labels: list[str]) -> list[str]:
    prompt = (
        "Analyze the code for SOLID principle violations. "
        "Return a JSON array containing only the violated principles, using these "
        f"exact codes: {labels}. Return [] if none. JSON only.\n\nCODE:\n" + code
    )
    try:
        parsed = _extract_json(_chat([{"role": "user", "content": prompt}]))
        return [x for x in parsed if x in labels] if isinstance(parsed, list) else []
    except (LLMUnavailable, urllib.error.URLError, KeyError):
        if _require_real():
            raise
        return _stub_multilabel(code, labels)


def predict_smells(code: str, labels: list[str]) -> list[str]:
    prompt = (
        "Detect code smells. Return a JSON array using only these exact codes: "
        f"{labels}. Return [] if none. JSON only.\n\nCODE:\n" + code
    )
    try:
        parsed = _extract_json(_chat([{"role": "user", "content": prompt}]))
        return [x for x in parsed if x in labels] if isinstance(parsed, list) else []
    except (LLMUnavailable, urllib.error.URLError, KeyError):
        if _require_real():
            raise
        return _stub_multilabel(code, labels)


def refactor(code: str) -> str:
    prompt = (
        "Refactor the following Python code for clean code and SOLID principles. "
        "Preserve behavior exactly. Return ONLY the refactored code, no prose, no fences.\n\n" + code
    )
    try:
        out = _chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=2000)
        fence = re.search(r"```(?:python)?\s*(.*?)```", out, re.DOTALL)
        return (fence.group(1) if fence else out).strip()
    except (LLMUnavailable, urllib.error.URLError, KeyError):
        if _require_real():
            raise
        return code  # offline stub: identity refactor (trivially behavior-preserving)


# ---------------------------------------------------------------------------
# Offline deterministic stubs (heuristic; ONLY used when no API key).
# These are NOT a baseline -- they only let the harness run end-to-end in CI.
# ---------------------------------------------------------------------------

def _stub_complexity(code: str) -> str:
    if "sort" in code:
        return "O(n log n)"
    loops = code.count("for ") + code.count("while ")
    if loops == 0:
        return "O(1)"
    if loops == 1:
        return "O(n)"
    return "O(n^2)"


def _stub_multilabel(code: str, labels: list[str]) -> list[str]:
    out = []
    if "SRP" in labels and code.count("def ") >= 4:
        out.append("SRP")
    if "long_method" in labels and len(code.splitlines()) > 25:
        out.append("long_method")
    return out
