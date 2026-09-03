"""Server-owned wall-clock policy for Challenge Cup meetings.

The policy is a projection over existing immutable model invocation receipts.
It does not create a second receipt store or write conversation state.  A
meeting persists the resulting absolute clock once and every speaker, follow-
up round and summary reuses that clock.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from typing import Any


DEADLINE_POLICY_VERSION = "challenge_meeting_deadline.v1"
PER_CALL_MAX_MS = 600_000
# The derivation band is collapsed onto the governed cap: live meeting-speaker
# calls regularly ran 300-416s, so the former 300s derived floor truncated
# valid calls mid-flight.  Receipt-derived budgets are now always the 600s
# governed fence; as a consequence the operator config/env override only
# accepts that same cap, and lower pins are rejected by the existing
# fail-loud override contract.
PER_CALL_MIN_MS = PER_CALL_MAX_MS
DEFAULT_PER_CALL_BUDGET_MS = 450_000
# Review calls process the full bounded transcript and have observed valid
# GLM latencies up to seven minutes; use the governed cap when receipts are
# still sparse, while speaker calls retain the 450s audited default.
DEFAULT_REVIEW_PER_CALL_BUDGET_MS = PER_CALL_MAX_MS
MIN_BUCKET_SAMPLE_COUNT = 20
_PER_CALL_OVERRIDE_ENV = "VIBELUTION_CHALLENGE_MEETING_PER_CALL_BUDGET_MS"
_CHALLENGE_SCOPE_AUTHORITIES = frozenset(
    {"workflow_discussion_scope.v1", "preformal_candidate_review_scope.v1"}
)
_HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review"
_HYPOTHESIS_CANDIDATE_REF_PREFIX = "hypothesis_candidate:"
_PLANNED_CALL_COUNT_BASIS_DIGEST = "speakers_plus_digest"
_PLANNED_CALL_COUNT_BASIS_REVIEW_BUDGET = "speakers_digest_review_call_budget"


class ChallengeMeetingDeadlinePolicyError(ValueError):
    """The server cannot derive a safe Challenge meeting wall-clock policy."""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _model_ref(value: Any) -> tuple[str, str]:
    normalized = str(value or "").strip()
    provider, separator, model = normalized.partition("/")
    return (
        provider.strip().lower(),
        model.strip().lower() if separator else "",
    )


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(max(0, int(value)) for value in values)
    if not ordered:
        return 0
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _bounded_budget_from_p95(p95_ms: int) -> int:
    return max(
        PER_CALL_MIN_MS,
        min(PER_CALL_MAX_MS, int(math.ceil(max(0, p95_ms) * 1.25))),
    )


def _operator_config_override_ms() -> int | None:
    """Read the operator-configured per-call fence from ``[research]`` config.

    The packaged default is ``None`` (unconfigured).  Missing/unreadable
    config fails open to ``None`` so the derivation falls back to the env
    override and then the receipt-derived budget; an out-of-range value is
    rejected by ``_operator_override_ms`` with the same error contract as the
    env override, because a silently ignored operator fence would produce a
    meeting clock the operator does not expect.
    """

    try:
        from config.settings import get_config

        value = get_config().research.challenge_meeting_per_call_budget_ms
    except Exception:  # noqa: BLE001 - config gating must never break the policy
        return None
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) and value > 0 else None


def _operator_override_ms() -> int | None:
    config_value = _operator_config_override_ms()
    if config_value is not None:
        if not PER_CALL_MIN_MS <= config_value <= PER_CALL_MAX_MS:
            raise ChallengeMeetingDeadlinePolicyError(
                "research.challenge_meeting_per_call_budget_ms must be between "
                f"{PER_CALL_MIN_MS} and {PER_CALL_MAX_MS}"
            )
        return config_value
    raw = str(os.environ.get(_PER_CALL_OVERRIDE_ENV) or "").strip()
    if not raw:
        return None
    value = _positive_int(raw)
    if value is None or not PER_CALL_MIN_MS <= value <= PER_CALL_MAX_MS:
        raise ChallengeMeetingDeadlinePolicyError(
            f"{_PER_CALL_OVERRIDE_ENV} must be between "
            f"{PER_CALL_MIN_MS} and {PER_CALL_MAX_MS}"
        )
    return value


def _receipt_latency_samples(team_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry import (
        ReceiptResetPortError,
        list_team_model_invocation_latency_samples,
    )

    try:
        return list_team_model_invocation_latency_samples(team_id)
    except ReceiptResetPortError as exc:
        if exc.code == "receipt_scope_unavailable":
            return []
        raise


def derive_per_call_budget(
    team_id: str,
    *,
    model_refs: Sequence[str] = (),
    purpose: str = "meeting_speaker",
) -> dict[str, Any]:
    """Derive one bounded call budget from immutable receipt latency facts."""

    override = _operator_override_ms()
    if override is not None:
        config_present = _operator_config_override_ms() is not None
        return {
            "perCallBudgetMs": override,
            "latencyP95Ms": 0,
            "sampleCount": 0,
            "sampleSource": (
                "operator_config" if config_present else "operator_env"
            ),
            "overrideEnv": "" if config_present else _PER_CALL_OVERRIDE_ENV,
        }

    requested = {item for item in (_model_ref(value) for value in model_refs) if item[0]}
    samples = [dict(item) for item in _receipt_latency_samples(team_id)]
    normalized_purpose = str(purpose or "meeting_speaker").strip().lower()

    def latency_rows(*, exact_model: bool, exact_purpose: bool) -> list[int]:
        rows: list[int] = []
        for item in samples:
            provider = str(item.get("provider") or "").strip().lower()
            model = str(item.get("model") or "").strip().lower()
            sample_purpose = str(item.get("purpose") or "").strip().lower()
            if requested:
                if exact_model and (provider, model) not in requested:
                    continue
                if not exact_model and provider not in {value[0] for value in requested}:
                    continue
            if exact_purpose and sample_purpose != normalized_purpose:
                continue
            latency = _positive_int(item.get("latencyMs"))
            if latency is not None:
                rows.append(latency)
        return rows

    buckets = (
        ("provider_model_purpose_p95", latency_rows(exact_model=True, exact_purpose=True)),
        ("provider_model_p95", latency_rows(exact_model=True, exact_purpose=False)),
        ("provider_class_p95", latency_rows(exact_model=False, exact_purpose=False)),
        (
            "global_p95",
            [
                value
                for item in samples
                if (value := _positive_int(item.get("latencyMs"))) is not None
            ],
        ),
    )
    for source, latencies in buckets:
        if len(latencies) >= MIN_BUCKET_SAMPLE_COUNT:
            latency_p95_ms = _p95(latencies)
            return {
                "perCallBudgetMs": _bounded_budget_from_p95(latency_p95_ms),
                "latencyP95Ms": latency_p95_ms,
                "sampleCount": len(latencies),
                "sampleSource": source,
                "overrideEnv": "",
            }
    return {
        "perCallBudgetMs": (
            DEFAULT_REVIEW_PER_CALL_BUDGET_MS
            if normalized_purpose == "team_workflow_review"
            else DEFAULT_PER_CALL_BUDGET_MS
        ),
        "latencyP95Ms": 0,
        "sampleCount": len(samples),
        "sampleSource": "audited_default",
        "overrideEnv": "",
    }


def _participant_model_refs(agent_ids: Sequence[str]) -> list[str]:
    from core.llm.agent_runtime import agent_dialogue_model_id
    from core.web.services import agent_directory_service

    refs: list[str] = []
    for agent_id in agent_ids:
        agent = agent_directory_service.get_agent(
            str(agent_id or "").strip(), include_archived=False
        )
        model_ref = agent_dialogue_model_id(agent) if isinstance(agent, Mapping) else ""
        if model_ref and model_ref not in refs:
            refs.append(model_ref)
    return refs


def is_challenge_meeting(value: Mapping[str, Any]) -> bool:
    return isinstance(value.get("modelInvocationReceiptAuthority"), Mapping) or str(
        value.get("scopeAuthority") or ""
    ).strip() in _CHALLENGE_SCOPE_AUTHORITIES


def _hypothesis_review_finalist_count(meeting: Mapping[str, Any]) -> int:
    """Count the distinct finalists one review round would actually score."""

    finalist_ids: set[str] = set()
    for item in list(meeting.get("discussionItemRefs") or []):
        ref = str(item or "").strip()
        if not ref.startswith(_HYPOTHESIS_CANDIDATE_REF_PREFIX):
            continue
        finalist_id = ref[len(_HYPOTHESIS_CANDIDATE_REF_PREFIX) :].strip()
        if finalist_id:
            finalist_ids.add(finalist_id)
    return len(finalist_ids)


def _review_round_call_budget(meeting: Mapping[str, Any]) -> tuple[int, int] | None:
    """Return ``(finalistCount, reviewCalls)`` for a formal review, or ``None``.

    The exact Stage-1 review budget is the ``review_call_budget`` contract's
    ``n + n(n-1)/2 + 2``.  That contract counts every call and has no separate
    serial-wave number; even though the pairwise/pareto wave shares one
    bounded-concurrency execution, this conservative projection never assumes
    parallelism, so ``totalReviewCalls`` is the serial figure.  Meetings that
    are not ``hypothesis_review`` rounds — or that carry no candidate refs —
    return ``None`` and keep the legacy speakers-plus-digest estimate.
    """

    if (
        str(meeting.get("meetingType") or "").strip().lower()
        != _HYPOTHESIS_REVIEW_MEETING_TYPE
    ):
        return None
    finalist_count = _hypothesis_review_finalist_count(meeting)
    if finalist_count < 1:
        return None
    from core.research.workflow.contracts.review_call_budget import (
        MAX_BUDGET_FINALIST_COUNT,
        review_call_budget_for,
    )

    # The bounded review context truncates candidates at the same cap
    # (research_memory_context.MAX_REVIEW_CANDIDATES), so a larger selection
    # can never spend more review calls than the capped budget.
    finalist_count = min(finalist_count, MAX_BUDGET_FINALIST_COUNT)
    return finalist_count, review_call_budget_for(finalist_count).totalReviewCalls


def derive_meeting_deadline_policy(
    team_id: str,
    meeting: Mapping[str, Any],
    *,
    server_created_at_ms: int,
    outer_deadline_at_ms: int | None = None,
) -> dict[str, Any]:
    """Return the immutable policy fields for one logical Challenge meeting."""

    created_at_ms = _positive_int(server_created_at_ms)
    if created_at_ms is None:
        raise ChallengeMeetingDeadlinePolicyError(
            "server_created_at_ms must be a positive server timestamp"
        )
    participants = [
        str(item or "").strip()
        for item in list(meeting.get("participants") or [])
        if str(item or "").strip()
    ]
    rounds = _positive_int(meeting.get("rounds")) or 1
    # One model call per serial speaker plus one digest call.  A later
    # durable driver may lower this only when its execution graph proves calls
    # are parallel; this conservative projection never assumes parallelism.
    planned_serial_call_count = max(1, len(participants)) * rounds + 1
    planned_call_count_basis = _PLANNED_CALL_COUNT_BASIS_DIGEST
    review_round_budget = _review_round_call_budget(meeting)
    if review_round_budget is not None:
        # Formal candidate review: after the discussion digest, the closed
        # review round spends the exact Stage-1 budget n + n(n-1)/2 + 2
        # (review-call-budget-v1), so the linear speakers-only estimate would
        # under-count the quadratic pairwise growth and starve the fence.
        review_finalist_count, review_calls = review_round_budget
        planned_serial_call_count += review_calls
        planned_call_count_basis = _PLANNED_CALL_COUNT_BASIS_REVIEW_BUDGET
    else:
        review_finalist_count = 0
    model_refs = _participant_model_refs(participants)
    call_policy = derive_per_call_budget(
        team_id,
        model_refs=model_refs,
        purpose="meeting_speaker",
    )
    per_call_budget_ms = int(call_policy["perCallBudgetMs"])
    meeting_budget_ms = per_call_budget_ms * planned_serial_call_count
    meeting_deadline_at_ms = created_at_ms + meeting_budget_ms
    normalized_outer_deadline = _positive_int(outer_deadline_at_ms)
    effective_deadline_at_ms = min(
        value
        for value in (meeting_deadline_at_ms, normalized_outer_deadline)
        if value is not None
    )
    deadline_budget_sufficient = (
        normalized_outer_deadline is None
        or normalized_outer_deadline >= meeting_deadline_at_ms
    )
    policy_seed = {
        "deadlinePolicyVersion": DEADLINE_POLICY_VERSION,
        "plannedSerialCallCount": planned_serial_call_count,
        # Identifies which derivation produced this count without bumping
        # DEADLINE_POLICY_VERSION: persisted v1 policies are never recomputed,
        # so old meetings stay readable as-is while new meetings carry the
        # review-budget-aware basis string.
        "plannedCallCountBasis": planned_call_count_basis,
        "reviewFinalistCount": review_finalist_count,
        "perCallBudgetMs": per_call_budget_ms,
        "meetingBudgetMs": meeting_budget_ms,
        "sampleSource": call_policy["sampleSource"],
        "sampleCount": call_policy["sampleCount"],
        "latencyP95Ms": call_policy["latencyP95Ms"],
        "modelRefs": model_refs,
        "overrideEnv": call_policy["overrideEnv"],
    }
    policy_hash = hashlib.sha256(
        json.dumps(
            policy_seed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **policy_seed,
        "deadlinePolicyHash": policy_hash,
        "meetingDeadlineAtMs": meeting_deadline_at_ms,
        "outerChallengeDeadlineAtMs": normalized_outer_deadline or 0,
        "challengeDeadlineAtMs": effective_deadline_at_ms,
        "deadlineBudgetSufficient": deadline_budget_sufficient,
        **(
            {
                "deadlineProblem": {
                    "code": "deadline_budget_insufficient",
                    "availableMs": max(0, normalized_outer_deadline - created_at_ms),
                    "requiredMs": meeting_budget_ms,
                    "outerDeadlineAtMs": normalized_outer_deadline,
                    "meetingDeadlineAtMs": meeting_deadline_at_ms,
                }
            }
            if normalized_outer_deadline is not None
            and not deadline_budget_sufficient
            else {}
        ),
    }


def effective_call_deadline_at_ms(
    *,
    call_started_at_ms: int,
    per_call_budget_ms: int,
    meeting_deadline_at_ms: int | None,
    outer_deadline_at_ms: int | None,
) -> int:
    candidates = [
        int(call_started_at_ms) + int(per_call_budget_ms),
        *(
            [int(meeting_deadline_at_ms)]
            if _positive_int(meeting_deadline_at_ms) is not None
            else []
        ),
        *(
            [int(outer_deadline_at_ms)]
            if _positive_int(outer_deadline_at_ms) is not None
            else []
        ),
    ]
    return min(candidates)


__all__ = [
    "ChallengeMeetingDeadlinePolicyError",
    "DEADLINE_POLICY_VERSION",
    "DEFAULT_PER_CALL_BUDGET_MS",
    "MIN_BUCKET_SAMPLE_COUNT",
    "PER_CALL_MAX_MS",
    "PER_CALL_MIN_MS",
    "derive_meeting_deadline_policy",
    "derive_per_call_budget",
    "effective_call_deadline_at_ms",
    "is_challenge_meeting",
]
