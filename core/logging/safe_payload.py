"""Privacy-preserving summaries for payloads written to durable diagnostics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

_MAX_ARGUMENT_KEYS = 24


def _public_argument_items(value: Mapping[Any, Any]) -> list[tuple[str, Any]]:
    return sorted(
        (
            (str(key), item)
            for key, item in value.items()
            if str(key) and not str(key).startswith("_")
        ),
        key=lambda pair: pair[0],
    )


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence):
        return "array"
    return type(value).__name__


def _value_shape(value: object) -> dict[str, Any]:
    value_type = _value_type(value)
    if isinstance(value, str | bytes):
        return {"type": value_type, "length": len(value)}
    if isinstance(value, Mapping):
        items = _public_argument_items(value)
        return {
            "type": value_type,
            "count": len(items),
            "keys": [key for key, _ in items[:_MAX_ARGUMENT_KEYS]],
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        item_types = sorted({_value_type(item) for item in value})
        return {
            "type": value_type,
            "count": len(value),
            "itemTypes": item_types[:_MAX_ARGUMENT_KEYS],
        }
    return {"type": value_type}


def _canonical_hash_value(value: object, *, depth: int = 0) -> Any:
    if depth >= 8:
        return {"__type__": _value_type(value)}
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, Mapping):
        return {
            key: _canonical_hash_value(item, depth=depth + 1)
            for key, item in _public_argument_items(value)
        }
    if isinstance(value, Sequence):
        return [_canonical_hash_value(item, depth=depth + 1) for item in value]
    return {"__type__": f"{type(value).__module__}.{type(value).__qualname__}"}


def summarize_tool_arguments(tool_args: Mapping[Any, Any] | None) -> dict[str, Any]:
    """Return keys/shape/length/fingerprint only; argument values never escape."""
    payload = tool_args if isinstance(tool_args, Mapping) else {}
    items = _public_argument_items(payload)
    canonical = _canonical_hash_value(payload)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "argKeys": [key for key, _ in items[:_MAX_ARGUMENT_KEYS]],
        "argCount": len(items),
        "argShape": {key: _value_shape(value) for key, value in items[:_MAX_ARGUMENT_KEYS]},
        "argSha256": hashlib.sha256(encoded).hexdigest(),
        "valuesRedacted": True,
    }


__all__ = ["summarize_tool_arguments"]
