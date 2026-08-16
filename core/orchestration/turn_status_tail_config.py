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


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
    if isinstance(value, Mapping):
        return value
    return None


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _coerce_positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    if isinstance(value, bool) or value is None:
        number = default
    else:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
    return max(minimum, min(maximum, number))


def normalize_turn_status_tail_config(raw: Any | None) -> dict[str, Any]:
    """Normalize client/session payload into a stable config dict."""

    base = default_turn_status_tail_config()
    parsed = _as_mapping(raw) if raw is not None else None
    if parsed is None:
        return base

    enabled = _coerce_bool(parsed.get("enabled"), True)
    blocks_raw = _as_mapping(parsed.get("blocks")) or {}
    limits_raw = _as_mapping(parsed.get("limits")) or {}

    blocks = dict(DEFAULT_BLOCKS)
    for key in ALL_BLOCKS:
        if key in blocks_raw:
            blocks[key] = _coerce_bool(blocks_raw.get(key), DEFAULT_BLOCKS[key])
        # camelCase aliases from JS
        camel = "".join(
            part.capitalize() if index else part
            for index, part in enumerate(key.split("_"))
        )
        if camel in blocks_raw and key not in blocks_raw:
            blocks[key] = _coerce_bool(blocks_raw.get(camel), DEFAULT_BLOCKS[key])

    limits = dict(DEFAULT_LIMITS)
    limits["gitPathsMax"] = _coerce_positive_int(
        limits_raw.get("gitPathsMax", limits_raw.get("git_paths_max")),
        DEFAULT_LIMITS["gitPathsMax"],
        minimum=1,
        maximum=40,
    )
    limits["runDigestToolsMax"] = _coerce_positive_int(
        limits_raw.get("runDigestToolsMax", limits_raw.get("run_digest_tools_max")),
        DEFAULT_LIMITS["runDigestToolsMax"],
        minimum=1,
        maximum=24,
    )
    limits["maxTailChars"] = _coerce_positive_int(
        limits_raw.get("maxTailChars", limits_raw.get("max_tail_chars")),
        DEFAULT_LIMITS["maxTailChars"],
        minimum=400,
        maximum=12_000,
    )

    return {
        "version": CONFIG_VERSION,
        "enabled": enabled,
        "blocks": blocks,
        "limits": limits,
    }


def block_enabled(config: Mapping[str, Any] | None, block_id: str) -> bool:
    normalized = normalize_turn_status_tail_config(config)
    if not normalized.get("enabled", True):
        return False
    key = _coerce_text(block_id).strip().lower().replace("-", "_").replace(" ", "_")
    blocks = normalized.get("blocks") if isinstance(normalized.get("blocks"), Mapping) else {}
    return bool(blocks.get(key, DEFAULT_BLOCKS.get(key, False)))


def clone_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    return deepcopy(normalize_turn_status_tail_config(config))
