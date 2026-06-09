"""Raw-LLM baseline: a single naive prompt, NO AST detectors, NO verification.

This is baseline (a) from the evaluation plan — the thing CodeGuard must beat.

It talks to Groq / OpenRouter through the OpenAI-compatible Chat Completions API
using only the standard library (urllib), so it has zero extra dependencies.

If no API key is configured (e.g. offline / CI), it falls back to a deterministic
offline stub so the whole harness still runs end-to-end and produces a report.
The stub is clearly NOT a real baseline — it just lets you smoke-test the harness.
Set CODEGUARD_EVAL_REQUIRE_LLM=1 to make a missing key a hard error instead.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.error


class LLMUnavailable(RuntimeError):
    pass


def _provider_config():
    """Return (base_url, api_key, model) from env, or None if unavailable."""
    # Prefer OpenRouter, fall back to Groq — both OpenAI-compatible.
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
        return (
            "https://api.groq.com/openai/v1",
            groq,
            model or "llama-3.3-70b-versatile",
        )
    return None


def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 1200) -> str:
    cfg = _provider_config()
    if cfg is None:
        raise LLMUnavailable("No OPENROUTER_API_KEY or GROQ_API_KEY in environment")
    base_url, api_key, model = cfg
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare in front of Groq/OpenRouter blocks the default
            # "Python-urllib/x.y" agent with error 1010, so present a normal one.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) codeguard-eval/1.0",
        },
        method="POST",
    )
    # Retry on 429 (rate limit) with backoff, honoring Retry-After when present.
    last_err = None
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
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


def _require_real() -> bool:
    return os.getenv("CODEGUARD_EVAL_REQUIRE_LLM", "0") == "1"


def _maybe_stub(kind: str):
    if _require_real():
        raise
    return None


def _extract_json(text: str):
    """Pull the first JSON object/array out of an LLM response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Task-specific baseline predictors
# ---------------------------------------------------------------------------

VALID_TIERS = ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)", "O(2^n)"]


def predict_complexity(code: str) -> str:
    prompt = (
        "You are a complexity analyzer. Reply with ONLY the dominant worst-case "
        "time complexity of the function, chosen from this exact list: "
        + ", ".join(VALID_TIERS)
        + ". Reply with the bare label, nothing else.\n\nCODE:\n" + code
    )
    try:
        out = _chat([{"role": "user", "content": prompt}]).strip()
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
        out = _chat([{"role": "user", "content": prompt}])
        parsed = _extract_json(out)
        if isinstance(parsed, list):
            return [x for x in parsed if x in labels]
        return []
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
        out = _chat([{"role": "user", "content": prompt}])
        parsed = _extract_json(out)
        if isinstance(parsed, list):
            return [x for x in parsed if x in labels]
        return []
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
# Offline deterministic stubs (heuristic; only used when no API key)
# ---------------------------------------------------------------------------


def _stub_complexity(code: str) -> str:
    depth = 0
    max_depth = 0
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("for ") or s.startswith("while "):
            indent = (len(line) - len(line.lstrip())) // 4
            max_depth = max(max_depth, indent + 1)
    if "sort" in code:
        return "O(n log n)"
    loops = code.count("for ") + code.count("while ")
    if loops == 0:
        return "O(1)"
    if loops == 1:
        return "O(n)"
    return "O(n^2)"


def _stub_multilabel(code: str, labels: list[str]) -> list[str]:
    # Trivial heuristic so offline runs are non-degenerate but clearly fake.
    out = []
    if "SRP" in labels and code.count("def ") >= 4:
        out.append("SRP")
    if "long_method" in labels and len(code.splitlines()) > 25:
        out.append("long_method")
    return out
