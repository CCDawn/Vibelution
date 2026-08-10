"""Shared validation primitives for immutable workflow contracts."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


class ContractValidationError(ValueError):
    """A persisted workflow contract is incomplete or malformed."""


def require_keys(payload: Mapping[str, Any], keys: Sequence[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ContractValidationError(
            f"missing required contract fields: {', '.join(missing)}"
        )


def require_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ContractValidationError(f"{key} must be a non-empty string")
    return value


def require_int(payload: Mapping[str, Any], key: str, *, minimum: int = 0) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{key} must be an integer >= {minimum}")
    return value


def require_mapping(
    payload: Mapping[str, Any], key: str, *, non_empty: bool = True
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping) or (non_empty and not value):
        suffix = "non-empty " if non_empty else ""
        raise ContractValidationError(f"{key} must be a {suffix}object")
    return copy.deepcopy(dict(value))


def require_list(
    payload: Mapping[str, Any], key: str, *, non_empty: bool = False
) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list) or (non_empty and not value):
        suffix = "non-empty " if non_empty else ""
        raise ContractValidationError(f"{key} must be a {suffix}list")
    return copy.deepcopy(value)


def require_sha256(payload: Mapping[str, Any], key: str) -> str:
    value = require_text(payload, key).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractValidationError(f"{key} must be a lowercase sha256 hex digest")
    return value


def require_score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} must be a number between 0 and 1")
    score = float(value)
    if score < 0 or score > 1:
        raise ContractValidationError(f"{field} must be between 0 and 1")
    return score


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
