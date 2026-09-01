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
PER_CALL_MIN_MS = 300_000
PER_CALL_MAX_MS = 600_000
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


def _operator_override_ms() -> int | None:
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
        return {
            "perCallBudgetMs": override,
            "latencyP95Ms": 0,
            "sampleCount": 0,
            "sampleSource": "operator_env",
            "overrideEnv": _PER_CALL_OVERRIDE_ENV,
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
    # One model call per serial speaker plus one digest/review call.  A later
    # durable driver may lower this only when its execution graph proves calls
    # are parallel; this conservative projection never assumes parallelism.
    planned_serial_call_count = max(1, len(participants)) * rounds + 1
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
