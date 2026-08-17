"""Session-level Turn Status Bar tail composition (injectable sections).

Blocks are appended at the **message list tail** only (never mid-list) so
provider automatic prefix cache can still grow with pure-append tool trails.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

# Stable block ids (session UI + wire payload).
BLOCK_BUDGET = "budget"
BLOCK_CLOCK = "clock"
BLOCK_GIT_BRIEF = "git_brief"
BLOCK_GIT_PATHS = "git_paths"
BLOCK_RUN_DIGEST = "run_digest"
BLOCK_CACHE_HINT = "cache_hint"
BLOCK_IDENTITY = "identity"

ALL_BLOCKS: tuple[str, ...] = (
    BLOCK_BUDGET,
    BLOCK_CLOCK,
    BLOCK_GIT_BRIEF,
    BLOCK_GIT_PATHS,
    BLOCK_RUN_DIGEST,
    BLOCK_CACHE_HINT,
    BLOCK_IDENTITY,
)

# Lean defaults: only cheap always-on telemetry.
DEFAULT_BLOCKS: dict[str, bool] = {
    BLOCK_BUDGET: True,
    BLOCK_CLOCK: True,
    BLOCK_GIT_BRIEF: False,
    BLOCK_GIT_PATHS: False,
    BLOCK_RUN_DIGEST: False,
    BLOCK_CACHE_HINT: False,
    BLOCK_IDENTITY: False,
}

DEFAULT_LIMITS: dict[str, int] = {
    "gitPathsMax": 12,
    "runDigestToolsMax": 8,
    "maxTailChars": 2500,
}

CONFIG_VERSION = 1


def default_turn_status_tail_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "enabled": True,
        "blocks": dict(DEFAULT_BLOCKS),
        "limits": dict(DEFAULT_LIMITS),
    }


def _decode_binary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def _maybe_json(value: Any) -> Any:
    value = _decode_binary(value)
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    value = _decode_binary(value)
    if isinstance(value, str):
        return value
    return str(value)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return value
    return None


def _camel_block_id(key: str) -> str:
    return "".join(
        part.capitalize() if index else part
        for index, part in enumerate(key.split("_"))
    )


def _normalize_block_id(value: Any) -> str:
    text = _coerce_text(value).strip().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    lowered = text.lower()
    if lowered in ALL_BLOCKS:
        return lowered
    camel_lookup = {_camel_block_id(key).lower(): key for key in ALL_BLOCKS}
    return camel_lookup.get(lowered, lowered)


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _unwrap_config(value: Any) -> Mapping[str, Any] | None:
    parsed = _as_mapping(value)
    if parsed is None:
        return None
    if "enabled" in parsed or "blocks" in parsed or "limits" in parsed:
        return parsed
    nested = _mapping_get(parsed, "config", "payload", "settings")
    inner = _as_mapping(nested)
    if inner is not None:
        return inner
    return parsed


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value = _decode_binary(value)
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _block_flag(value: Any, default: bool) -> bool:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return _coerce_bool(_mapping_get(value, "enabled"), default)
    return _coerce_bool(value, default)


def _coerce_positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    value = _decode_binary(value)
    if isinstance(value, bool) or value is None:
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
    return max(minimum, min(maximum, number))


def _coerce_blocks(value: Any) -> dict[str, bool]:
    value = _maybe_json(value)
    blocks = dict(DEFAULT_BLOCKS)
    if isinstance(value, Mapping):
        nested = _mapping_get(value, "blocks", "items")
        has_block_key = any(key in value or _camel_block_id(key) in value for key in ALL_BLOCKS)
        if nested is not None and not has_block_key:
            return _coerce_blocks(nested)
        for key in ALL_BLOCKS:
            camel = _camel_block_id(key)
            if key in value:
                blocks[key] = _block_flag(value.get(key), DEFAULT_BLOCKS[key])
            elif camel in value:
                blocks[key] = _block_flag(value.get(camel), DEFAULT_BLOCKS[key])
        return blocks
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return blocks
    try:
        iterator = list(value)
    except TypeError:
        return blocks
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            name = _normalize_block_id(
                _mapping_get(item, "id", "block", "name", "key") or next(iter(item), "")
            )
            enabled = _block_flag(item, default=True)
        else:
            name = _normalize_block_id(item)
            enabled = True
        if name in blocks:
            blocks[name] = enabled
    return blocks


def _coerce_limits(value: Any) -> dict[str, int]:
    parsed = _as_mapping(value) or {}
    if parsed and "gitPathsMax" not in parsed and "git_paths_max" not in parsed:
        nested = _mapping_get(parsed, "limits", "items")
        inner = _as_mapping(nested)
        if inner is not None:
            parsed = inner
    limits = dict(DEFAULT_LIMITS)
    limits["gitPathsMax"] = _coerce_positive_int(
        parsed.get("gitPathsMax", parsed.get("git_paths_max")),
        DEFAULT_LIMITS["gitPathsMax"],
        minimum=1,
        maximum=40,
    )
    limits["runDigestToolsMax"] = _coerce_positive_int(
        parsed.get("runDigestToolsMax", parsed.get("run_digest_tools_max")),
        DEFAULT_LIMITS["runDigestToolsMax"],
        minimum=1,
        maximum=24,
    )
    limits["maxTailChars"] = _coerce_positive_int(
        parsed.get("maxTailChars", parsed.get("max_tail_chars")),
        DEFAULT_LIMITS["maxTailChars"],
        minimum=400,
        maximum=12_000,
    )
    return limits


def normalize_turn_status_tail_config(raw: Any | None) -> dict[str, Any]:
    """Normalize client/session payload into a stable config dict."""

    base = default_turn_status_tail_config()
    parsed = _unwrap_config(raw) if raw is not None else None
    if parsed is None:
        return base

    enabled = _coerce_bool(_mapping_get(parsed, "enabled"), True)
    return {
        "version": CONFIG_VERSION,
        "enabled": enabled,
        "blocks": _coerce_blocks(_mapping_get(parsed, "blocks")),
        "limits": _coerce_limits(_mapping_get(parsed, "limits")),
    }


def block_enabled(config: Mapping[str, Any] | None, block_id: str) -> bool:
    normalized = normalize_turn_status_tail_config(config)
    if not normalized.get("enabled", True):
        return False
    key = _normalize_block_id(block_id)
    blocks = normalized.get("blocks") if isinstance(normalized.get("blocks"), Mapping) else {}
    return bool(blocks.get(key, DEFAULT_BLOCKS.get(key, False)))


def clone_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    return deepcopy(normalize_turn_status_tail_config(config))
