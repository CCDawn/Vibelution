"""Model-family tool-call budgets for Agent tool policies.

Mature agent runtimes adapt tool budgets to model priors (e.g. DeepSeek tends
to explore with more tools). Policy may still set an explicit base
``maxCallsPerTurn`` and optional per-family overrides.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

# Built-in defaults when policy has no per-family map entry.
# Tuned from observed tool-use intensity of common coding models.
DEFAULT_MAX_CALLS_BY_MODEL_FAMILY: dict[str, int] = {
    "deepseek": 64,
    "claude": 40,
    "openai": 32,
    "gemini": 48,
    "qwen": 48,
    "llama": 40,
    "mistral": 40,
    "default": 32,
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


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value = _decode_binary(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _flag_enabled(value: Any, default: bool = True) -> bool:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        nested = value.get("enabled")
        if nested is None:
            nested = value.get("visible")
        return _coerce_bool(nested, default)
    return _coerce_bool(value, default)


def _identity_text(value: Any) -> str:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        for key in ("model", "id", "name", "provider", "profileId", "profile_id"):
            text = _coerce_text(value.get(key)).strip()
            if text:
                return text
        return ""
    return _coerce_text(value).strip()


_POLICY_KEYS = (
    "maxCallsPerTurn",
    "max_calls_per_turn",
    "maxCallsPerTurnByModelFamily",
    "max_calls_per_turn_by_model_family",
)
_POLICY_ENVELOPES = ("policy", "toolPolicy", "tool_policy", "config", "payload")
_FAMILY_ENVELOPES = ("families", "items", "overrides", "byFamily", "by_family")


def _as_mapping(value: Any) -> dict[str, Any]:
    value = _maybe_json(value)
    if not isinstance(value, Mapping):
        return {}
    mapping = dict(value)
    if any(key in mapping for key in _POLICY_KEYS):
        return mapping
    for envelope in _POLICY_ENVELOPES:
        if envelope not in mapping:
            continue
        nested = _as_mapping(mapping.get(envelope))
        if nested:
            return nested
    return mapping


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def detect_model_family(
    *,
    model: str = "",
    provider: str = "",
    profile_id: str = "",
) -> str:
    """Best-effort vendor/family key from model id, provider, or profile id."""

    haystack = " ".join(
        text
        for part in (model, provider, profile_id)
        for text in [_identity_text(part).lower()]
        if text
    )
    if not haystack:
        return "default"
    checks = (
        ("deepseek", ("deepseek", "ds-")),
        ("claude", ("claude", "anthropic")),
        ("openai", ("openai", "gpt-4", "gpt-5", "gpt-3", "o1", "o3", "o4")),
        ("gemini", ("gemini", "google")),
        ("qwen", ("qwen", "dashscope", "tongyi")),
        ("llama", ("llama", "meta-llama")),
        ("mistral", ("mistral", "mixtral")),
    )
    for family, needles in checks:
        if any(needle in haystack for needle in needles):
            return family
    return "default"


def _positive_int(value: Any, *, default: int = 0) -> int:
    value = _maybe_json(value)
    if isinstance(value, bool) or value is None:
        value = default
    value = _decode_binary(value)
    if isinstance(value, bool) or value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        try:
            parsed = int(default)
        except (TypeError, ValueError):
            return 0
    return max(0, parsed)


def _budget_from_entry(raw_budget: Any, *, default: int = 0) -> int | None:
    raw_budget = _maybe_json(raw_budget)
    if isinstance(raw_budget, bool):
        return None
    if isinstance(raw_budget, Mapping):
        if not _flag_enabled(raw_budget, True):
            return None
        nested = _first_present(
            raw_budget.get("maxCallsPerTurn"),
            raw_budget.get("max_calls_per_turn"),
            raw_budget.get("maxCalls"),
            raw_budget.get("max_calls"),
            raw_budget.get("value"),
            raw_budget.get("budget"),
        )
        if nested is None:
            return None
        return _positive_int(nested, default=default)
    return _positive_int(raw_budget, default=default)


def _known_family_key(key: str) -> bool:
    return key == "default" or key in DEFAULT_MAX_CALLS_BY_MODEL_FAMILY


def resolve_max_calls_per_turn(
    tool_policy: Mapping[str, Any] | None,
    *,
    model: str = "",
    provider: str = "",
    profile_id: str = "",
) -> tuple[int, str]:
    """Resolve the effective per-turn tool budget and the profile key used.

    Returns:
        (max_calls_per_turn, budget_profile_key)

    Rules:
    1. Base ``maxCallsPerTurn`` from policy; 0 means unlimited (no hard cap).
    2. If unlimited, return 0 without family overrides.
    3. Else prefer ``maxCallsPerTurnByModelFamily[family]``, then
       ``...["default"]``, then built-in family defaults, then base.
    """

    policy = _as_mapping(tool_policy)
    base = _positive_int(
        _first_present(policy.get("maxCallsPerTurn"), policy.get("max_calls_per_turn")),
        default=0,
    )
    family = detect_model_family(model=model, provider=provider, profile_id=profile_id)
    if base <= 0:
        return 0, family

    overrides = normalize_max_calls_by_model_family(
        _first_present(
            policy.get("maxCallsPerTurnByModelFamily"),
            policy.get("max_calls_per_turn_by_model_family"),
        )
    )
    if overrides:
        if family in overrides:
            return _positive_int(overrides.get(family), default=base), family
        if "default" in overrides:
            return _positive_int(overrides.get("default"), default=base), family
        # Explicit empty-or-partial maps still win over silent family upgrade.

    # Only auto-adapt when the policy still uses the common session base (32).
    # Explicit low/high bases (e.g. tests with maxCallsPerTurn=1) stay as written.
    family_default = DEFAULT_MAX_CALLS_BY_MODEL_FAMILY.get(family)
    if family_default is not None and family != "default" and base == 32:
        return int(family_default), family
    return base, family


def default_max_calls_by_model_family_payload() -> dict[str, int]:
    """Serializable default map for new session tool policies."""

    return dict(DEFAULT_MAX_CALLS_BY_MODEL_FAMILY)


def normalize_max_calls_by_model_family(value: Any) -> dict[str, int]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        mapping = dict(value)
        has_family_key = any(_known_family_key(_coerce_text(key).strip().lower()) for key in mapping)
        if not has_family_key:
            for envelope in _FAMILY_ENVELOPES:
                if envelope in mapping:
                    return normalize_max_calls_by_model_family(mapping.get(envelope))
        normalized: dict[str, int] = {}
        for raw_key, raw_budget in mapping.items():
            key = _coerce_text(raw_key).strip().lower()
            if not key or key in _FAMILY_ENVELOPES:
                continue
            budget = _budget_from_entry(raw_budget, default=0)
            if budget is None:
                continue
            normalized[key] = budget
        return normalized
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return {}
    try:
        iterator = list(value)
    except TypeError:
        return {}
    normalized: dict[str, int] = {}
    for item in iterator:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            if not _flag_enabled(item, True):
                continue
            key = _coerce_text(
                _first_present(
                    item.get("family"),
                    item.get("name"),
                    item.get("id"),
                    item.get("modelFamily"),
                    item.get("model_family"),
                )
            ).strip().lower()
            if not key:
                continue
            budget = _budget_from_entry(item, default=0)
            if budget is None:
                continue
            normalized[key] = budget
            continue
        key = _coerce_text(item).strip().lower()
        if key:
            normalized[key] = DEFAULT_MAX_CALLS_BY_MODEL_FAMILY.get(key, 0)
    return normalized
