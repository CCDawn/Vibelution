# -*- coding: utf-8 -*-
"""Route-level resilience ladder ordering is machine-checked, not comment-only.

The ladder's order invariants used to live only in comments and a private
frozenset in turn_llm_adapter.py; core/llm/resilience_policy.py is now their
single owner and these tests lock the design in place.
"""

from __future__ import annotations

from core.llm.recovery import DEGRADED_RETRY_ACTIONS, _ACTION_FOR_CATEGORY
from core.llm.resilience_policy import (
    CATEGORY_STAGES,
    CONNECTION_BACKOFF_CAP_CATEGORIES,
    DEGRADED_RETRY_CATEGORIES,
    FALLBACK_SWITCH_CATEGORIES,
    TRANSPORT_RETRY_CATEGORIES,
    ResilienceStage,
    can_switch_fallback,
    stage_for_category,
    stage_rank,
)

# Every category the route-level ladder knows about: classify_exception's
# emitted values plus the guard-raised answer_channel_leak and the adapter/
# wire-raised protocol_error.
KNOWN_CATEGORIES = frozenset(
    {
        "network_error",
        "timeout",
        "server_error",
        "rate_limit",
        "context_length_error",
        "tool_protocol_error",
        "empty_content_error",
        "protocol_error",
        "answer_channel_leak",
        "capability_error",
        "quota_error",
        "auth_error",
        "configuration_error",
        "provider_protocol_error",
        "payload_protocol_error",
        "user_interrupt",
    }
)


def test_resilience_stage_enum_matches_designed_total_order():
    """TRANSPORT_RETRY → DEGRADED_RETRY → FALLBACK_SWITCH → TURN_TERMINAL."""
    assert [stage.name for stage in ResilienceStage] == [
        "TRANSPORT_RETRY",
        "DEGRADED_RETRY",
        "FALLBACK_SWITCH",
        "TURN_TERMINAL",
    ]
    ranks = [stage_rank(stage) for stage in ResilienceStage]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
    assert stage_rank(ResilienceStage.TRANSPORT_RETRY) < stage_rank(ResilienceStage.DEGRADED_RETRY)
    assert stage_rank(ResilienceStage.DEGRADED_RETRY) < stage_rank(ResilienceStage.FALLBACK_SWITCH)
    assert stage_rank(ResilienceStage.FALLBACK_SWITCH) < stage_rank(ResilienceStage.TURN_TERMINAL)


def test_degraded_and_fallback_category_sets_are_disjoint():
    """The ordering argument from turn_llm_adapter.py, now a machine assertion.

    Degradation categories and gateway-level fallback categories never compete
    over a single failure, so degrade-before-fallback ordering is total.
    """
    assert DEGRADED_RETRY_CATEGORIES.isdisjoint(FALLBACK_SWITCH_CATEGORIES)
    assert FALLBACK_SWITCH_CATEGORIES == TRANSPORT_RETRY_CATEGORIES
    assert FALLBACK_SWITCH_CATEGORIES == frozenset(
        {"network_error", "timeout", "server_error", "rate_limit"}
    )
    assert DEGRADED_RETRY_CATEGORIES == frozenset(
        {"empty_content_error", "tool_protocol_error", "protocol_error", "answer_channel_leak"}
    )


def test_each_category_maps_to_exactly_one_stage():
    for category in KNOWN_CATEGORIES:
        stage = stage_for_category(category)
        assert isinstance(stage, ResilienceStage)
        # Idempotent: the same category always resolves to the same stage.
        assert stage_for_category(category) is stage
    # The table itself has no duplicate keys beyond dict semantics and covers
    # every known category.
    assert len(CATEGORY_STAGES) == len(set(CATEGORY_STAGES.keys()))
    assert KNOWN_CATEGORIES <= set(CATEGORY_STAGES.keys())


def test_every_known_category_has_a_stage_home():
    """All known categories (incl. leak, network/timeout/server/rate-limit,
    protocol errors) have a destination; unknown categories fall through to
    the terminal stage, mirroring recovery's ``fail_fast`` default."""
    assert KNOWN_CATEGORIES <= set(CATEGORY_STAGES.keys())
    assert stage_for_category("unknown_future_category") is ResilienceStage.TURN_TERMINAL
    assert stage_for_category("") is ResilienceStage.TURN_TERMINAL


def test_transport_categories_stage_before_degraded_and_terminal_categories():
    transport = {stage_for_category(c) for c in ("network_error", "timeout", "server_error", "rate_limit")}
    degraded = {stage_for_category(c) for c in DEGRADED_RETRY_CATEGORIES}
    terminal = {
        stage_for_category(c)
        for c in (
            "context_length_error",
            "capability_error",
            "quota_error",
            "auth_error",
            "configuration_error",
            "provider_protocol_error",
            "payload_protocol_error",
            "user_interrupt",
        )
    }
    assert transport == {ResilienceStage.TRANSPORT_RETRY}
    assert degraded == {ResilienceStage.DEGRADED_RETRY}
    assert terminal == {ResilienceStage.TURN_TERMINAL}


def test_can_switch_fallback_matches_gateway_level_categories():
    for category in ("network_error", "timeout", "server_error", "rate_limit"):
        assert can_switch_fallback(category) is True
    for category in (
        "empty_content_error",
        "tool_protocol_error",
        "protocol_error",
        "answer_channel_leak",
        "context_length_error",
        "capability_error",
        "quota_error",
        "auth_error",
        "configuration_error",
        "provider_protocol_error",
        "payload_protocol_error",
        "user_interrupt",
        "unknown_future_category",
    ):
        assert can_switch_fallback(category) is False


def test_recovery_degraded_actions_stay_aligned_with_policy_stage_map():
    """recovery owns the action vocabulary, policy owns the stage map: the
    degraded subsets must name exactly the same categories."""
    action_degraded_categories = {
        category
        for category, action in _ACTION_FOR_CATEGORY.items()
        if action in DEGRADED_RETRY_ACTIONS
    }
    assert action_degraded_categories == set(DEGRADED_RETRY_CATEGORIES)
    assert set(_ACTION_FOR_CATEGORY.keys()) <= set(CATEGORY_STAGES.keys())


def test_connection_backoff_cap_subset_matches_client_vocabulary():
    """The client's hard backoff cap is the transport categories minus
    rate_limit (which waits on server-advised backoff instead)."""
    assert CONNECTION_BACKOFF_CAP_CATEGORIES == TRANSPORT_RETRY_CATEGORIES - {"rate_limit"}
