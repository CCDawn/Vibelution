"""Canonical JSON serialization and stable content hashing.

Single source of truth for the canonical form used by content-addressed
idempotency keys (agent kernel events) and command request hashes (research
workflow ledger commands).  The rules are the ledger contract's frozen ones:

- UTF-8, ``ensure_ascii=False`` so non-ASCII content hashes on its real
  characters instead of ``\\uXXXX`` escapes;
- object keys sorted, so dict insertion order can never change a hash;
- no extra whitespace (``(",", ":")`` separators).
"""

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
