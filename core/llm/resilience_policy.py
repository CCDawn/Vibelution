# -*- coding: utf-8 -*-
"""Single owner of the LLM resilience ladder: stage order and category vocabulary.

Before this module, the ladder's order invariants lived only in comments and a
private frozenset spread across three files (``core/llm/client.py`` transport
retry budget, ``core/llm/recovery.py`` category→action vocabulary, and
``core/orchestration/turn_llm_adapter.py`` fallback-switch gate). This module
consolidates the *order and vocabulary*; execution logic stays where it is.

Layering diagram — route level vs continuation level:

    ┌─ route 层（一个 LLM turn 内的尝试阶梯，本模块owned）──────────────────┐
    │                                                                      │
    │  TRANSPORT_RETRY ──► DEGRADED_RETRY ──► FALLBACK_SWITCH ──► TURN_TERMINAL
    │                                                                      │
    │  core/llm/client.py        同 profile 能力降级      单跳备路由        │
    │  transport 重试预算          每动作每回合一次        仅在 transport    │
    │  (profile.retry_policy)     (动作词汇在             预算耗尽后,       │
    │  耗尽前原地重试               recovery.py)           仅主路由        │
    │                                                     切一次            │
    │                                    终态: 全路由耗尽 / fail_fast /   │
    │                                    context_length_error 触发压缩 /  │
    │                                    兜底播报(turn_diagnostics.py)     │
    └──────────────────────────────────────────────────────────────────────┘
    ┌─ 续跑层（跨 turn 的会话级判定，不同抽象级，不并入本模块）─────────────┐
    │  stuck 检测与续跑循环: core/web/services/session/worker.py           │
    │                       + core/web/services/session/turn_stuck_analyzer.py │
    │  它们判断"整个 turn 是否卡死、是否重新拉起"，不参与 route 内的阶段    │
    │  排序，因此不进入 ResilienceStage。                                   │
    └──────────────────────────────────────────────────────────────────────┘

Stage semantics: ``CATEGORY_STAGES`` maps each known error category to the
*earliest ladder stage that handles it*. ``FALLBACK_SWITCH`` is an escalation
stage: no category maps to it directly, but the transport-retry categories
escalate into it once ``core/llm/client.py``'s transport retry budget is
exhausted (single hop, primary route only — enforced in
``core/orchestration/turn_llm_adapter.py``).

This module is vocabulary and order only: it owns no retry loop, raises no
LLM error, and performs no I/O.
"""

from __future__ import annotations

from enum import IntEnum, unique
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "CATEGORY_STAGES",
    "CONNECTION_BACKOFF_CAP_CATEGORIES",
    "DEGRADED_RETRY_CATEGORIES",
    "FALLBACK_SWITCH_CATEGORIES",
    "ResilienceStage",
    "can_switch_fallback",
    "stage_for_category",
    "stage_rank",
]


@unique
class ResilienceStage(IntEnum):
    """Ordered route-level resilience ladder.

    The declaration order IS the designed execution order:
    transport retries run before any same-profile capability degradation, a
    degraded retry precedes the explicit fallback switch, and the fallback
    target is the last hop before the turn goes terminal.
    """

    TRANSPORT_RETRY = 0
    DEGRADED_RETRY = 1
    FALLBACK_SWITCH = 2
    TURN_TERMINAL = 3


# Earliest ladder stage that handles each known error category. Categories not
# listed fall through to TURN_TERMINAL, mirroring recovery's ``fail_fast``
# default for unknown categories.
CATEGORY_STAGES: Mapping[str, ResilienceStage] = MappingProxyType(
    {
        # Gateway-level recoverable transport failures: retried in-place by the
        # client's transport budget first; escalate to the declared fallback
        # profile only after that budget is exhausted.
        "network_error": ResilienceStage.TRANSPORT_RETRY,
        "timeout": ResilienceStage.TRANSPORT_RETRY,
        "server_error": ResilienceStage.TRANSPORT_RETRY,
        "rate_limit": ResilienceStage.TRANSPORT_RETRY,
        # Capability/answer-shape degradation: one same-profile shaped retry,
        # each action at most once per turn (action vocabulary lives in
        # core/llm/recovery.py: DEGRADED_RETRY_ACTIONS).
        "empty_content_error": ResilienceStage.DEGRADED_RETRY,
        "tool_protocol_error": ResilienceStage.DEGRADED_RETRY,
        "protocol_error": ResilienceStage.DEGRADED_RETRY,
        # Answer-channel leak: internal formatting (analysis/summary envelopes,
        # legacy tool-call XML, DSML fragments) emitted as the final answer.
        # See core/llm/answer_channel_guard.py.
        "answer_channel_leak": ResilienceStage.DEGRADED_RETRY,
        # Terminal paths: no transport retry, no degradation, no fallback.
        # context_length_error exits the ladder through adapter-level context
        # compression; the rest are fail-fast or user-interrupt stops.
        "context_length_error": ResilienceStage.TURN_TERMINAL,
        "capability_error": ResilienceStage.TURN_TERMINAL,
        "quota_error": ResilienceStage.TURN_TERMINAL,
        "auth_error": ResilienceStage.TURN_TERMINAL,
        "configuration_error": ResilienceStage.TURN_TERMINAL,
        "provider_protocol_error": ResilienceStage.TURN_TERMINAL,
        "payload_protocol_error": ResilienceStage.TURN_TERMINAL,
        "user_interrupt": ResilienceStage.TURN_TERMINAL,
    }
)


def stage_for_category(category: str) -> ResilienceStage:
    """Earliest ladder stage that handles ``category`` (unknown → terminal)."""
    return CATEGORY_STAGES.get(str(category or "").strip(), ResilienceStage.TURN_TERMINAL)


def stage_rank(stage: ResilienceStage) -> int:
    """Position of ``stage`` in the ladder; lower runs earlier."""
    return int(stage)


#: Categories handled at the transport-retry stage (in-place client retries).
TRANSPORT_RETRY_CATEGORIES = frozenset(
    category for category, stage in CATEGORY_STAGES.items() if stage is ResilienceStage.TRANSPORT_RETRY
)

#: Categories handled by a one-shot same-profile capability degradation.
DEGRADED_RETRY_CATEGORIES = frozenset(
    category for category, stage in CATEGORY_STAGES.items() if stage is ResilienceStage.DEGRADED_RETRY
)

# Categories allowed to escalate into the FALLBACK_SWITCH stage once the
# transport retry budget is exhausted. Identical to the transport-retry set by
# design: only a category that first went through in-place transport retries
# may switch to the declared fallback profile (single hop, primary route only).
FALLBACK_SWITCH_CATEGORIES = TRANSPORT_RETRY_CATEGORIES

# Connection-level backoff cap subset used by core/llm/client.py's
# ``_retry_policy_backoff_seconds``: connection-shaped failures cap exponential
# backoff hard, while rate_limit waits on server-advised (longer) backoff and
# is deliberately excluded from the cap.
CONNECTION_BACKOFF_CAP_CATEGORIES = frozenset({"network_error", "timeout", "server_error"})


def can_switch_fallback(category: str) -> bool:
    """Whether ``category`` may escalate to the declared fallback profile.

    Category gate only: the adapter additionally requires a declared fallback
    profile, a retryable failure, and an exhausted transport retry budget.
    """
    return stage_for_category(category) is ResilienceStage.TRANSPORT_RETRY


# Module-level invariant: the degrade path and the fallback-escalation path are
# disjoint, so the two branches can never compete over a single failure (the
# ordering argument previously kept as a comment in turn_llm_adapter.py).
if not DEGRADED_RETRY_CATEGORIES.isdisjoint(FALLBACK_SWITCH_CATEGORIES):  # pragma: no cover
    raise ValueError(
        "resilience_policy invariant violated: DEGRADED_RETRY_CATEGORIES and "
        "FALLBACK_SWITCH_CATEGORIES must be disjoint, got "
        f"{sorted(DEGRADED_RETRY_CATEGORIES & FALLBACK_SWITCH_CATEGORIES)}"
    )
