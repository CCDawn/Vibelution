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


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


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
        for text in [_coerce_text(part).strip().lower()]
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
    if isinstance(value, bool) or value is None:
        value = default
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

    policy = tool_policy if isinstance(tool_policy, Mapping) else {}
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
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for raw_key, raw_budget in value.items():
        key = _coerce_text(raw_key).strip().lower()
        if not key:
            continue
        normalized[key] = _positive_int(raw_budget, default=0)
    return normalized
