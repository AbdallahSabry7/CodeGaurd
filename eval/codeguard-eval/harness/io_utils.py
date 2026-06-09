"""Small IO helpers: JSONL loading and results writing."""
from __future__ import annotations

import json
import os
from typing import Iterator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")


def load_jsonl(path: str) -> list[dict]:
    """Load a .jsonl file (one JSON object per line, '#'-comment lines skipped)."""
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(json.loads(line))
    return rows


def ensure_results_dir() -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return RESULTS_DIR


def write_json(name: str, obj) -> str:
    ensure_results_dir()
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    return path


def iter_dataset(rel_path: str) -> Iterator[dict]:
    yield from load_jsonl(rel_path)
