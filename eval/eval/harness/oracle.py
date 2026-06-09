"""Generated-input differential oracle.

The original harness only compared original-vs-candidate on the SAME handful of
declared test cases, so any behavior change on an UNLISTED input was invisible.
That reduces 'differential testing' to 're-running the gold tests'.

This module GENERATES extra inputs shaped like the declared cases and lets the
differential check exercise original-vs-candidate across all of them. This is
the difference between 'passes the gold tests' and 'actually preserves
behavior'. Generation is seeded, so runs are reproducible.
"""
from __future__ import annotations

import random
import string
from typing import Any


def _gen_like(sample: Any, rng: random.Random) -> Any:
    """Produce a new random value with the same shape as `sample`."""
    if isinstance(sample, bool):
        return rng.choice([True, False])
    if isinstance(sample, int):
        return rng.randint(-50, 50)
    if isinstance(sample, float):
        return round(rng.uniform(-50.0, 50.0), 3)
    if isinstance(sample, str):
        length = rng.randint(0, 8)
        return "".join(rng.choice(string.ascii_lowercase) for _ in range(length))
    if isinstance(sample, list):
        if not sample:
            return [rng.randint(-20, 20) for _ in range(rng.randint(0, 6))]
        elem = sample[0]
        return [_gen_like(elem, rng) for _ in range(rng.randint(0, 6))]
    if sample is None:
        return rng.randint(-50, 50)
    return sample  # unknown shape: reuse as-is


def generate_inputs(seed_cases: list[dict], n: int, seed: int = 1234) -> list[list]:
    """Return `n` generated arg-lists shaped like the declared cases' args."""
    if not seed_cases or n <= 0:
        return []
    rng = random.Random(seed)
    templates = [c.get("args", []) for c in seed_cases]
    out = []
    for _ in range(n):
        tmpl = rng.choice(templates)
        out.append([_gen_like(a, rng) for a in tmpl])
    return out


def build_input_set(seed_cases: list[dict], n_generated: int, seed: int = 1234):
    """Return (seed_args, generated_args)."""
    seed_args = [c.get("args", []) for c in seed_cases]
    return seed_args, generate_inputs(seed_cases, n_generated, seed)
