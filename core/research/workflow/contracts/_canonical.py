"""Shared canonical helpers for research workflow contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Canonical JSON: UTF-8, sorted object keys, no extra whitespace."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_hex(payload: Mapping[str, Any]) -> str:
    """Stable content hash over canonical JSON."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
