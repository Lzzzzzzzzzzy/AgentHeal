"""Small helpers: deterministic randomness, number normalization, hashing, JSON IO."""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any, Iterable

_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def rng_for(*parts: Any) -> random.Random:
    """A Random seeded from a stable hash of the given parts."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short_hash(*parts: Any, n: int = 8) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:n]


def extract_numbers(text: str) -> list[float]:
    """All numbers in a string, tolerant of thousands separators."""
    out = []
    for m in _NUM_RE.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def numbers_match(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def value_in_text(value: str, text: str) -> bool:
    """True if the canonical form of `value` occurs in `text` (numeric-aware)."""
    if value is None or text is None:
        return False
    v = str(value).strip()
    nums = extract_numbers(v)
    if nums and len(nums) == 1 and re.fullmatch(r"[-+]?[\d,]+(?:\.\d+)?", v.replace(" ", "")):
        target = nums[0]
        return any(numbers_match(target, x) for x in extract_numbers(text))
    return v.lower() in text.lower()


def dump_json(obj: Any, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False))


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def append_jsonl(path: str | Path, rec: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
