"""Stable server-side ID generation with fixed prefixes (spec 5.6)."""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    if prefix not in ("run", "cmd", "nr", "act", "evt", "ho", "ht", "ar", "br", "rec", "anchor", "kinv"):
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}-{uuid.uuid4().hex}"
