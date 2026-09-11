# -*- coding: utf-8 -*-
"""Profile routing helpers for LLM recovery."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from config import AppConfig

from .recovery import LLMRecoveryDecision


_PROVIDER_RETRY_ACTIONS = {"retry_with_backoff", "retry_after_backoff"}


def attach_recovery_fallback(
    decision: LLMRecoveryDecision,
    *,
    config: Optional[AppConfig],
    role: str = "primary",
    current_profile_id: Optional[str] = None,
) -> LLMRecoveryDecision:
    if config is None:
        return decision
    fallback = select_recovery_profile(
        config,
        role=role,
        current_profile_id=current_profile_id,
        action=decision.action,
    )
    if not fallback:
        return decision
    return replace(decision, fallback_profile_id=fallback)


def select_recovery_profile(
    config: AppConfig,
    *,
    role: str = "primary",
    current_profile_id: Optional[str] = None,
    action: str,
) -> Optional[str]:
    llm_config = config.llm
    current_id = current_profile_id or llm_config.get_role_profile_id(role)
    current_profile = llm_config.get_profile(current_id)
    current_provider = llm_config.get_provider(current_profile.provider_id)

    # An operator declaration wins over the ranking heuristic. It still has to be
    # usable for this recovery action: a declared route that cannot serve the
    # action (say, a smaller context window for compress_context) falls through
    # to the heuristic rather than silently degrading the recovery.
    declared_id = _declared_fallback_id(current_profile, current_id)
    if declared_id:
        declared_score = _usable_candidate_score(
            config,
            llm_config,
            declared_id,
            action=action,
            current_profile=current_profile,
            current_provider=current_provider,
            declared=True,
        )
        if declared_score is not None and declared_score > 0:
            return declared_id

    candidates = []
    for profile_id in llm_config.profiles:
        if profile_id == current_id:
            continue
        score = _usable_candidate_score(
            config,
            llm_config,
            profile_id,
            action=action,
            current_profile=current_profile,
            current_provider=current_provider,
        )
        if score is None or score <= 0:
            continue
        candidates.append((score, profile_id))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _declared_fallback_id(current_profile, current_id: str) -> str:
    """Return the profile's declared fallback, ignoring a self-reference."""

    declared = str(getattr(current_profile, "fallback", "") or "").strip()
    return "" if not declared or declared == current_id else declared


def _usable_candidate_score(
    config: AppConfig,
    llm_config,
    profile_id: str,
    *,
    action: str,
    current_profile,
    current_provider,
    declared: bool = False,
) -> Optional[int]:
    """Score one candidate route, or None when it is not resolvable at all."""

    profile = llm_config.profiles.get(profile_id)
    if profile is None:
        return None
    try:
        provider = llm_config.get_provider(profile.provider_id)
    except Exception:
        return None
    if provider.requires_api_key and not config.get_api_key_for_profile(profile_id=profile_id):
        return None
    return _score_candidate(
        action=action,
        profile=profile,
        provider=provider,
        current_profile=current_profile,
        current_provider=current_provider,
        declared=declared,
    )


def _score_candidate(
    *,
    action: str,
    profile,
    provider,
    current_profile,
    current_provider,
    declared: bool = False,
) -> int:
    profile_id = str(getattr(profile, "profile_id", "") or "")
    score = 1
    if provider.provider_id != current_provider.provider_id:
        score += 2
    # A declared fallback is explicit operator intent, so it does not also have to
    # carry the `fallback*` id prefix the ranking heuristic relies on.
    explicit_fallback = declared or profile_id.startswith("fallback")
    if explicit_fallback:
        score += 1

    if action in {"disable_tools", "disable_tools_and_retry_without_streaming"}:
        if profile.tool_calling_mode == "disabled":
            score += 5
        if not profile.streaming:
            score += 3
        return score

    if action == "retry_without_streaming":
        if not profile.streaming:
            score += 5
        return score

    if action == "compress_context":
        context_window = int(provider.context_window or 0)
        if context_window <= int(current_provider.context_window or 0):
            return 0
        score += 5 + min(context_window // 1000, 1000)
        return score

    if action in _PROVIDER_RETRY_ACTIONS:
        if provider.provider_id == current_provider.provider_id:
            return 0
        if not explicit_fallback:
            return 0
        return score

    return 0


__all__ = ["attach_recovery_fallback", "select_recovery_profile"]
