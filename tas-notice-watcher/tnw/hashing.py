"""Deterministic hashing helpers.

Every hash in this project is sha256. Content hashes are computed over a
canonical JSON encoding so that key order, whitespace and unicode form can
never change a hash without the underlying values changing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(fields: dict[str, Any]) -> str:
    """sha256 over the canonical JSON encoding of ``fields``."""
    return sha256_text(canonical_json(fields))
