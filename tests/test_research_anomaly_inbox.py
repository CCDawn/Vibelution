"""R4.3 anomaly inbox: ordering invariant, dedup merge, severity table, service.

Covers the fail-closed contract gates (unknown kind, missing/wrong severity,
broken ordering, unmerged duplicates, timestamp integrity), the dedup/merge
rule (same scope+kind keeps the earliest firstSeen), the table-driven
severity mapping, and the pure aggregation service (heartbeat-stale code
mapping, taxonomy human-required action families, awaiting-human gate,
disputed/escalation/drift/retry-budget companion inputs, empty state).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from core.research.workflow.contracts import (
    ANOMALY_KIND_BLOCKED_RUN,
    ANOMALY_KIND_BUDGET_EXHAUSTED,
    ANOMALY_KIND_CLAIM_DISPUTED,
    ANOMALY_KIND_HEARTBEAT_STALE,
    ANOMALY_KIND_NEEDS_HUMAN_GATE,
    ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
    ANOMALY_KIND_SEVERITY,
    ANOMALY_KINDS,
    ANOMALY_SEVERITIES,
    DEFAULT_RETRY_TAXONOMY,
    AnomalyInbox,
    AnomalyInboxItem,
    AnomalyInboxScope,
    ContractValidationError,
    HumanActionFamily,
    RetryOutcomeClass,
)
from core.web.services.team_workflow.research_runtime import anomaly_inbox_service

_GENERATED_AT = "2026-08-28T01:00:00Z"

_TEAM_QUESTION = {"teamId": "team-1", "questionId": "Q-1"}


def _problem(
    code: str,
    *,
    message: str = "problem",
    source_kind: str = "formal_run",
    source_id: str | None = "run-1",
    detected_at: str = "2026-08-28T00:30:00Z",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "category": "integrity",
        "severity": "warning",
        "message": message,
        "recoverable": True,
        "sourceKind": source_kind,
        "sourceId": source_id,
        "detectedAt": detected_at,
    }
    payload.update(extra)
    return payload


def _state(
    problems: list[dict[str, Any]] | None = None,
    *,
    awaiting_human_count: int = 0,
) -> dict[str, Any]:
    return {
        **_TEAM_QUESTION,
        "computedAt": _GENERATED_AT,
        "awaitingHumanCount": awaiting_human_count,
        "problems": list(problems or []),
    }


def _item(
    kind: str,
    *,
    scope: AnomalyInboxScope | None = None,
    first_seen_at: str = "2026-08-28T00:10:00Z",
    last_seen_at: str = "2026-08-28T00:20:00Z",
    summary: str = "summary",
    evidence: tuple[str, ...] = ("problem:test",),
    recommended_action: str | None = None,
) -> AnomalyInboxItem:
    return AnomalyInboxItem.create(
        kind=kind,
        scope=scope or AnomalyInboxScope(teamId="team-1", questionId="Q-1"),
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        summary=summary,
        evidence=evidence,
        recommended_action=recommended_action,
    )


# -- severity mapping is table-driven and closed ----------------------------


def test_severity_table_covers_the_closed_kind_set() -> None:
    assert set(ANOMALY_KIND_SEVERITY) == ANOMALY_KINDS
    assert set(ANOMALY_KIND_SEVERITY.values()) <= ANOMALY_SEVERITIES


@pytest.mark.parametrize(
    ("kind", "severity"),
    sorted(ANOMALY_KIND_SEVERITY.items()),
)
def test_item_severity_is_derived_from_the_frozen_table(
    kind: str, severity: str
) -> None:
    item = _item(kind)
    assert item.severity == severity


def test_from_dict_rejects_missing_severity() -> None:
    payload = _item(ANOMALY_KIND_BLOCKED_RUN).to_dict()
    payload.pop("severity")
    with pytest.raises(ContractValidationError, match="severity"):
        AnomalyInboxItem.from_dict(payload)


@pytest.mark.parametrize("severity", sorted(ANOMALY_SEVERITIES - {"critical"}))
def test_from_dict_rejects_severity_that_contradicts_the_table(
    severity: str,
) -> None:
    payload = _item(ANOMALY_KIND_BLOCKED_RUN).to_dict()
    payload["severity"] = severity
    with pytest.raises(ContractValidationError, match="frozen mapping"):
        AnomalyInboxItem.from_dict(payload)


# -- fail-closed contract gates ---------------------------------------------


def test_from_dict_rejects_unknown_kind() -> None:
    payload = _item(ANOMALY_KIND_BLOCKED_RUN).to_dict()
    payload["kind"] = "mystery_signal"
    with pytest.raises(ContractValidationError, match="kind must be one of"):
        AnomalyInboxItem.from_dict(payload)


def test_from_dict_rejects_unparseable_timestamp() -> None:
    payload = _item(ANOMALY_KIND_BLOCKED_RUN).to_dict()
    payload["lastSeenAt"] = "not-a-timestamp"
    with pytest.raises(ContractValidationError, match="ISO-8601"):
        AnomalyInboxItem.from_dict(payload)


def test_from_dict_rejects_last_seen_before_first_seen() -> None:
    with pytest.raises(ContractValidationError, match="lastSeenAt"):
        _item(
            ANOMALY_KIND_BLOCKED_RUN,
            first_seen_at="2026-08-28T00:30:00Z",
            last_seen_at="2026-08-28T00:20:00Z",
        )


def test_item_rejects_empty_scope_and_empty_evidence() -> None:
    with pytest.raises(ContractValidationError, match="scope"):
        _item(
            ANOMALY_KIND_BLOCKED_RUN,
            scope=AnomalyInboxScope(),
        )
    with pytest.raises(ContractValidationError, match="evidence"):
        _item(ANOMALY_KIND_BLOCKED_RUN, evidence=())


def test_item_rejects_action_family_outside_the_taxonomy() -> None:
    with pytest.raises(ContractValidationError, match="recommendedAction"):
        _item(
            ANOMALY_KIND_HEARTBEAT_STALE,
            recommended_action="rewrite_history",
        )


def test_inbox_from_dict_rejects_invariant_violating_order() -> None:
    low = _item(
        ANOMALY_KIND_HEARTBEAT_STALE,
        last_seen_at="2026-08-28T00:40:00Z",
    )
    high = _item(
        ANOMALY_KIND_BLOCKED_RUN,
        last_seen_at="2026-08-28T00:20:00Z",
    )
    payload = {
        "schemaVersion": 1,
        "ruleId": "anomaly_inbox_rule.v1",
        "generatedAt": _GENERATED_AT,
        "items": [low.to_dict(), high.to_dict()],
    }
    with pytest.raises(ContractValidationError, match="ordering invariant"):
        AnomalyInbox.from_dict(payload)


def test_inbox_from_dict_rejects_unmerged_duplicates() -> None:
    first = _item(ANOMALY_KIND_BLOCKED_RUN, last_seen_at="2026-08-28T00:20:00Z")
    second = _item(ANOMALY_KIND_BLOCKED_RUN, last_seen_at="2026-08-28T00:30:00Z")
    payload = {
        "schemaVersion": 1,
        "ruleId": "anomaly_inbox_rule.v1",
        "generatedAt": _GENERATED_AT,
        "items": [first.to_dict(), second.to_dict()],
    }
    with pytest.raises(ContractValidationError, match="unmerged duplicate"):
        AnomalyInbox.from_dict(payload)


def test_inbox_from_dict_rejects_unknown_schema_version_and_rule() -> None:
    base = {
        "generatedAt": _GENERATED_AT,
        "items": [],
    }
    with pytest.raises(ContractValidationError, match="schemaVersion"):
        AnomalyInbox.from_dict({**base, "schemaVersion": 2, "ruleId": "anomaly_inbox_rule.v1"})
    with pytest.raises(ContractValidationError, match="ruleId"):
        AnomalyInbox.from_dict({**base, "schemaVersion": 1, "ruleId": "other_rule.v1"})


# -- ordering invariant and dedup merge -------------------------------------


def test_mixed_signal_inbox_is_sorted_by_the_invariant() -> None:
    state = _state(
        [
            _problem(
                "collection_run_needs_continue",
                source_kind="collection_run",
                source_id="run-coll",
                detected_at="2026-08-28T00:30:00Z",
            ),
            _problem(
                "review_heartbeat_stale",
                source_kind="meeting_round",
                source_id="round-2",
                detected_at="2026-08-28T00:40:00Z",
                lastHeartbeatAt="2026-08-28T00:45:00Z",
            ),
            _problem(
                "budget_exceeded",
                source_kind="formal_run",
                source_id="run-formal",
                detected_at="2026-08-28T00:20:00Z",
            ),
            # informational, never becomes an item
            _problem(
                "formal_run_status_unknown",
                source_kind="formal_run",
                source_id="run-formal",
                detected_at="2026-08-28T00:20:00Z",
            ),
        ],
        awaiting_human_count=1,
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    observed = [(item.kind, item.lastSeenAt) for item in inbox.items]
    # critical first (blocked_run 00:30 > budget 00:20), then high by
    # lastSeenAt desc (gate 01:00, heartbeat 00:45).
    assert observed == [
        (ANOMALY_KIND_BLOCKED_RUN, "2026-08-28T00:30:00Z"),
        (ANOMALY_KIND_BUDGET_EXHAUSTED, "2026-08-28T00:20:00Z"),
        ("needs_human_gate", "2026-08-28T01:00:00Z"),
        (ANOMALY_KIND_HEARTBEAT_STALE, "2026-08-28T00:45:00Z"),
    ]
    assert AnomalyInbox.from_dict(inbox.to_dict()) == inbox


def test_same_scope_and_kind_items_merge_keeping_earliest_first_seen() -> None:
    state = _state(
        [
            _problem(
                "review_dispatch_heartbeat_stale",
                source_kind="review_dispatch_attempt",
                source_id="attempt-1",
                detected_at="2026-08-28T00:10:00Z",
                lastHeartbeatAt="2026-08-28T00:10:00Z",
            ),
            _problem(
                "review_dispatch_heartbeat_stale",
                source_kind="review_dispatch_attempt",
                source_id="attempt-2",
                detected_at="2026-08-28T00:50:00Z",
                lastHeartbeatAt="2026-08-28T00:50:00Z",
            ),
        ]
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    assert len(inbox.items) == 1
    merged = inbox.items[0]
    assert merged.kind == ANOMALY_KIND_HEARTBEAT_STALE
    assert merged.firstSeenAt == "2026-08-28T00:10:00Z"
    assert merged.lastSeenAt == "2026-08-28T00:50:00Z"
    assert merged.evidence == (
        "problem:review_dispatch_heartbeat_stale",
        "source:review_dispatch_attempt:attempt-1",
        "source:review_dispatch_attempt:attempt-2",
    )


def test_create_merges_and_keeps_representative_summary() -> None:
    older = _item(
        ANOMALY_KIND_BLOCKED_RUN,
        first_seen_at="2026-08-28T00:05:00Z",
        last_seen_at="2026-08-28T00:05:00Z",
        summary="oldest observation",
        evidence=("problem:collection_run_needs_continue",),
    )
    newer = _item(
        ANOMALY_KIND_BLOCKED_RUN,
        first_seen_at="2026-08-28T00:40:00Z",
        last_seen_at="2026-08-28T00:40:00Z",
        summary="newer observation",
        evidence=("problem:collection_run_needs_continue", "source:collection_run:run-2"),
    )
    inbox = AnomalyInbox.create([newer, older], generated_at=_GENERATED_AT)
    assert len(inbox.items) == 1
    merged = inbox.items[0]
    assert merged.summary == "oldest observation"
    assert merged.firstSeenAt == "2026-08-28T00:05:00Z"
    assert merged.lastSeenAt == "2026-08-28T00:40:00Z"
    assert merged.evidence == (
        "problem:collection_run_needs_continue",
        "source:collection_run:run-2",
    )


def test_scope_order_breaks_last_seen_ties_deterministically() -> None:
    run_b = AnomalyInboxScope(teamId="team-1", questionId="Q-1", runId="run-b")
    run_a = AnomalyInboxScope(teamId="team-1", questionId="Q-1", runId="run-a")
    inbox = AnomalyInbox.create(
        [
            _item(ANOMALY_KIND_BLOCKED_RUN, scope=run_b),
            _item(ANOMALY_KIND_BLOCKED_RUN, scope=run_a),
        ],
        generated_at=_GENERATED_AT,
    )
    assert [item.scope.runId for item in inbox.items] == ["run-a", "run-b"]


# -- heartbeat-stale kind mapping -------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "generation_heartbeat_stale",
        "review_heartbeat_stale",
        "review_dispatch_heartbeat_stale",
    ],
)
def test_heartbeat_stale_problem_codes_map_to_heartbeat_kind(code: str) -> None:
    state = _state([_problem(code, source_kind="review_dispatch_attempt", source_id="attempt-9")])
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    assert len(inbox.items) == 1
    item = inbox.items[0]
    assert item.kind == ANOMALY_KIND_HEARTBEAT_STALE
    assert item.severity == "high"
    assert item.recommendedAction == HumanActionFamily.RETRY_NODE.value
    assert item.evidence[0] == f"problem:{code}"


def test_meeting_scoped_heartbeat_carries_meeting_round_scope() -> None:
    state = _state(
        [
            _problem(
                "generation_heartbeat_stale",
                source_kind="meeting_round",
                source_id="round-11",
                detected_at="2026-08-28T00:40:00Z",
                lastHeartbeatAt="2026-08-28T00:41:00Z",
            )
        ]
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    item = inbox.items[0]
    assert item.scope.meetingRoundId == "round-11"
    assert item.lastSeenAt == "2026-08-28T00:41:00Z"


# -- taxonomy human_required mapping ----------------------------------------


@pytest.mark.parametrize(
    "code",
    sorted(
        DEFAULT_RETRY_TAXONOMY.codes_for_outcome_class(RetryOutcomeClass.HUMAN_REQUIRED)
    ),
)
def test_human_required_codes_map_to_inbox_kinds_and_action_families(
    code: str,
) -> None:
    state = _state(
        [
            _problem(
                code,
                source_kind="collection_run"
                if code == "collection_run_needs_continue"
                else "formal_run",
                source_id="run-1",
            )
        ]
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    assert len(inbox.items) == 1
    item = inbox.items[0]
    entry = DEFAULT_RETRY_TAXONOMY.entry(code)
    assert entry.outcome_class is RetryOutcomeClass.HUMAN_REQUIRED
    if code == "budget_exceeded":
        # budget exhaustion carries its own inbox kind.
        assert item.kind == ANOMALY_KIND_BUDGET_EXHAUSTED
    else:
        assert item.kind == ANOMALY_KIND_BLOCKED_RUN
        assert item.severity == "critical"
    assert item.recommendedAction == entry.human_actions[0].value
    assert item.evidence[0] == f"problem:{code}"


def test_budget_exceeded_maps_to_budget_exhausted_kind() -> None:
    state = _state(
        [_problem("budget_exceeded", source_kind="formal_run", source_id="run-1")]
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    item = inbox.items[0]
    assert item.kind == ANOMALY_KIND_BUDGET_EXHAUSTED
    assert item.severity == "critical"
    assert item.recommendedAction == HumanActionFamily.RECONCILE_RUN.value
    assert item.scope.runId == "run-1"


# -- companion inputs and service boundaries --------------------------------


def test_awaiting_human_count_becomes_one_gate_item() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(awaiting_human_count=3), generated_at=_GENERATED_AT
    )
    assert len(inbox.items) == 1
    item = inbox.items[0]
    assert item.kind == "needs_human_gate"
    assert item.recommendedAction is None
    assert item.evidence == ("awaitingHumanCount:3",)


def test_disputed_claims_count_into_one_claim_disputed_item() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        disputed_claims=[
            {"claimId": "claim-b", "beliefState": "disputed", "lastEvaluatedAt": "2026-08-28T00:30:00Z"},
            {"claimId": "claim-a", "beliefState": "disputed"},
            {"claimId": "claim-c", "beliefState": "supported"},  # never counted
        ],
        generated_at=_GENERATED_AT,
    )
    assert len(inbox.items) == 1
    item = inbox.items[0]
    assert item.kind == ANOMALY_KIND_CLAIM_DISPUTED
    assert item.evidence == (
        "claim:claim-a",
        "claim:claim-b",
        "disputedClaimCount:2",
    )


def test_retry_budget_exhaustion_produces_per_node_items() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        retry_exhausted_nodes=[
            {"runId": "run-1", "nodeId": "node-a"},
            {"runId": "run-1", "nodeId": "node-b"},
        ],
        generated_at=_GENERATED_AT,
    )
    assert [item.kind for item in inbox.items] == [
        ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
        ANOMALY_KIND_RETRY_BUDGET_EXHAUSTED,
    ]
    assert [item.scope.nodeId for item in inbox.items] == ["node-a", "node-b"]
    # The charged retry budget can never succeed again, so the recommendation
    # is the ledger-authority rebuild family, not another doomed retry_node.
    assert all(
        item.recommendedAction == HumanActionFamily.RECONCILE_RUN.value
        for item in inbox.items
    )


def test_non_flagged_only_escalations_and_empty_inputs_are_ignored() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        review_escalations=[{"status": "executed", "reason": "not an inbox signal"}],
        drift_sentinel_hits=[],
        disputed_claims=[],
        generated_at=_GENERATED_AT,
    )
    assert inbox.items == ()


def test_empty_state_yields_the_legal_empty_inbox() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(None, generated_at=_GENERATED_AT)
    assert inbox.items == ()
    assert inbox.schemaVersion == 1
    assert AnomalyInbox.from_dict(inbox.to_dict()) == inbox
    empty = AnomalyInbox.empty(generated_at=_GENERATED_AT)
    assert empty.items == ()


def test_service_accepts_dataclass_like_state_without_mutation() -> None:
    problems = [
        _problem(
            "collection_run_needs_continue",
            source_kind="collection_run",
            source_id="run-9",
        )
    ]
    state = SimpleNamespace(
        **_TEAM_QUESTION,
        computedAt=_GENERATED_AT,
        awaitingHumanCount=0,
        problems=problems,
    )
    inbox = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    assert [item.kind for item in inbox.items] == [ANOMALY_KIND_BLOCKED_RUN]
    # pure projection: the input snapshot is untouched
    assert problems == [
        _problem(
            "collection_run_needs_continue",
            source_kind="collection_run",
            source_id="run-9",
        )
    ]


def test_same_inputs_with_fixed_generated_at_are_deterministic() -> None:
    state = _state(
        [
            _problem("budget_exceeded", source_kind="formal_run", source_id="run-1"),
            _problem("review_heartbeat_stale", source_kind="meeting_round", source_id="r-1"),
        ],
        awaiting_human_count=1,
    )
    first = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    second = anomaly_inbox_service.build_anomaly_inbox(state, generated_at=_GENERATED_AT)
    assert first.to_dict() == second.to_dict()


# -- breakpoint escalations (convergence / digest TTL / gate waits) ----------


def test_convergence_exhausted_becomes_one_human_gate_item() -> None:
    state = {
        **_TEAM_QUESTION,
        "computedAt": _GENERATED_AT,
        "convergence": {
            "lifecycle": "completed",
            "outcome": "exhausted",
            "actionability": "waiting_user",
            "updatedAt": "2026-08-28T00:30:00Z",
            "roundIndex": 5,
            "roundBudget": 5,
            "latestHypothesisRoundId": "round-5",
        },
    }
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        state, generated_at=_GENERATED_AT
    )
    assert [item.kind for item in inbox.items] == [ANOMALY_KIND_NEEDS_HUMAN_GATE]
    item = inbox.items[0]
    assert item.severity == "high"
    assert item.summary.startswith("收敛评审轮预算已耗尽（第 5/5 轮）")
    assert "convergence:exhausted" in item.evidence
    assert "convergenceRound:5/5" in item.evidence
    assert item.firstSeenAt == "2026-08-28T00:30:00Z"


def test_convergence_not_exhausted_stays_silent() -> None:
    state = {
        **_TEAM_QUESTION,
        "computedAt": _GENERATED_AT,
        "convergence": {
            "lifecycle": "waiting_human",
            "outcome": "none",
            "actionability": "waiting_user",
        },
    }
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        state, generated_at=_GENERATED_AT
    )
    assert inbox.items == ()


def test_auto_advanced_convergence_no_longer_yields_exhausted_gate_item() -> None:
    """The budget-exhaustion auto-advance removes the human gate item: both
    terminal outcomes it can record (accepted -> succeeded, gate blocked ->
    rejected) project away from ``exhausted``/``waiting_user``, so the same
    question's inbox is empty afterwards."""
    exhausted_state = {
        **_TEAM_QUESTION,
        "computedAt": _GENERATED_AT,
        "convergence": {
            "lifecycle": "completed",
            "outcome": "exhausted",
            "actionability": "waiting_user",
            "updatedAt": "2026-08-28T00:30:00Z",
            "roundIndex": 5,
            "roundBudget": 5,
            "latestHypothesisRoundId": "round-5",
        },
    }
    before = anomaly_inbox_service.build_anomaly_inbox(
        exhausted_state, generated_at=_GENERATED_AT
    )
    assert [item.kind for item in before.items] == [ANOMALY_KIND_NEEDS_HUMAN_GATE]

    def _post_advance_state(outcome: str) -> dict[str, Any]:
        return {
            **_TEAM_QUESTION,
            "computedAt": _GENERATED_AT,
            "convergence": {
                "lifecycle": "completed",
                "outcome": outcome,
                "actionability": "terminal",
                "updatedAt": "2026-08-28T00:35:00Z",
                "roundIndex": 5,
                "roundBudget": 5,
                "latestHypothesisRoundId": "round-5",
                "accepted": outcome == "succeeded",
            },
        }

    for outcome in ("succeeded", "rejected"):
        after = anomaly_inbox_service.build_anomaly_inbox(
            _post_advance_state(outcome), generated_at=_GENERATED_AT
        )
        assert after.items == (), outcome


def _mute_state(round_id: str = "meeting-1") -> dict[str, Any]:
    return {
        "meetingStatus": "awaiting_approval",
        "digestAt": "2026-08-28T00:00:00Z",
        "digestAtSource": "digestDraft.generatedAt",
        "ttlMs": 2_700_000,
        "overdueMs": 1_800_000,
        "meetingRoundId": round_id,
    }


def test_digest_ttl_overdue_becomes_meeting_scoped_gate_item() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        digest_ttl_overdues=[_mute_state()],
        generated_at=_GENERATED_AT,
    )
    assert [item.kind for item in inbox.items] == [ANOMALY_KIND_NEEDS_HUMAN_GATE]
    item = inbox.items[0]
    assert item.scope.meetingRoundId == "meeting-1"
    assert "纪要审批等待超过 TTL" in item.summary
    assert "meetingDigestTtlOverdue:meeting-1" in item.evidence
    assert "digestAtSource:digestDraft.generatedAt" in item.evidence
    assert "ttlMs:2700000" in item.evidence
    assert "overdueMs:1800000" in item.evidence
    assert item.firstSeenAt == "2026-08-28T00:00:00Z"
    assert item.lastSeenAt == _GENERATED_AT


def test_digest_ttl_overdue_without_round_id_is_skipped() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        digest_ttl_overdues=[{**_mute_state(), "meetingRoundId": ""}],
        generated_at=_GENERATED_AT,
    )
    assert inbox.items == ()


def _gate_wait(
    *,
    gate_kind: str = "knowledge_handoff",
    since: str = "2026-08-28T00:00:00Z",
    threshold: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "gateKind": gate_kind,
        "gateId": extra.pop("gateId", gate_kind),
        "since": since,
        "runId": "run-1",
    }
    if threshold is not None:
        entry["thresholdMs"] = threshold
    entry.update(extra)
    return entry


def test_gate_wait_over_threshold_becomes_gate_item_with_run_scope() -> None:
    # 00:00 -> 01:00 = 3600s waited, past the explicit 30min threshold.
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        gate_waits=[_gate_wait(requestId="req-1")],
        gate_wait_threshold_ms=30 * 60 * 1000,
        generated_at=_GENERATED_AT,
    )
    assert [item.kind for item in inbox.items] == [ANOMALY_KIND_NEEDS_HUMAN_GATE]
    item = inbox.items[0]
    assert item.scope.runId == "run-1"
    assert "人工门 knowledge_handoff 等待已超过阈值" in item.summary
    assert "humanGateWait:knowledge_handoff:knowledge_handoff" in item.evidence
    assert "waitedMs:3600000" in item.evidence
    assert "thresholdMs:1800000" in item.evidence
    assert "gateRequest:req-1" in item.evidence


def test_gate_wait_honors_threshold_parameter_and_entry_threshold() -> None:
    # 45min wait: silent at a 60min threshold, escalated at 30min.
    silent = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        gate_waits=[_gate_wait(since="2026-08-28T00:15:00Z")],
        gate_wait_threshold_ms=60 * 60 * 1000,
        generated_at=_GENERATED_AT,
    )
    assert silent.items == ()
    escalated = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        gate_waits=[_gate_wait(since="2026-08-28T00:15:00Z")],
        gate_wait_threshold_ms=30 * 60 * 1000,
        generated_at=_GENERATED_AT,
    )
    assert len(escalated.items) == 1
    # Entry-level thresholdMs wins over the caller default.
    entry = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        gate_waits=[
            _gate_wait(since="2026-08-28T00:15:00Z", threshold=10 * 60 * 1000)
        ],
        gate_wait_threshold_ms=60 * 60 * 1000,
        generated_at=_GENERATED_AT,
    )
    assert len(entry.items) == 1
    assert "thresholdMs:600000" in entry.items[0].evidence


def test_gate_wait_with_unusable_since_is_skipped() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        gate_waits=[_gate_wait(since="not-a-timestamp")],
        generated_at=_GENERATED_AT,
    )
    assert inbox.items == ()


# -- budget precheck block + one-click extend CTA ----------------------------


def _precheck_block(**overrides: Any) -> dict[str, Any]:
    block = {
        "code": "budget_precheck_insufficient",
        "detail": "阶段 hypothesis 预算预检不足",
        "stageId": "hypothesis",
        "nodeId": "hf_hypothesis",
        "runId": "run-7",
        "stageLimitTokens": 300_000,
        "stageConsumedTokens": 280_000,
        "remainingTokens": 20_000,
        "referenceTokens": 280_000,
        "suggestedExtensionTokens": 260_000,
        "occurredAt": "2026-08-28T00:45:00Z",
    }
    block.update(overrides)
    return block


def test_budget_precheck_block_becomes_critical_budget_item() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(),
        budget_precheck_blocks=[_precheck_block()],
        generated_at=_GENERATED_AT,
    )
    assert [item.kind for item in inbox.items] == [ANOMALY_KIND_BUDGET_EXHAUSTED]
    item = inbox.items[0]
    assert item.severity == "critical"
    assert item.scope.runId == "run-7"
    assert item.scope.nodeId == "hf_hypothesis"
    assert item.recommendedAction == HumanActionFamily.RETRY_NODE.value
    assert "problem:budget_precheck_insufficient" in item.evidence
    assert "stage:hypothesis" in item.evidence
    assert "suggestedExtensionTokens:260000" in item.evidence
    assert "remainingTokens:20000" in item.evidence


def test_extend_budget_action_carries_confirmed_contract_shape() -> None:
    action = anomaly_inbox_service.extend_budget_action(_precheck_block())
    assert action is not None
    assert action["command"] == "extend_budget"
    assert action["then"] == {"command": "retry_node", "nodeId": "hf_hypothesis"}
    assert action["requiresConfirmation"] is True
    assert "260000" in action["confirmHint"]
    # limits is directly usable as the extend_budget command payload and the
    # new total is limit + suggested (extend only accepts increases).
    assert action["params"]["limits"] == {"stageTokens": {"hypothesis": 560_000}}
    assert action["params"]["newStageTokens"] == 560_000
    assert action["params"]["suggestedExtensionTokens"] == 260_000
    assert action["params"]["runId"] == "run-7"


def test_extend_budget_action_requires_computable_contract() -> None:
    assert (
        anomaly_inbox_service.extend_budget_action(_precheck_block(stageLimitTokens=0))
        is None
    )
    assert (
        anomaly_inbox_service.extend_budget_action(
            _precheck_block(suggestedExtensionTokens=0)
        )
        is None
    )
    assert (
        anomaly_inbox_service.extend_budget_action(
            _precheck_block(code="budget_exceeded")
        )
        is None
    )


def test_attach_inbox_actions_decorates_only_matching_items() -> None:
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        _state(
            [
                _problem(
                    "review_heartbeat_stale",
                    source_kind="meeting_round",
                    source_id="r-1",
                )
            ]
        ),
        budget_precheck_blocks=[_precheck_block()],
        generated_at=_GENERATED_AT,
    )
    decorated = anomaly_inbox_service.attach_inbox_actions(
        inbox.to_dict(), blocks=[_precheck_block()]
    )
    by_kind = {item["kind"]: item for item in decorated["items"]}
    assert "action" not in by_kind["heartbeat_stale"]
    action = by_kind["budget_exhausted"]["action"]
    assert action["command"] == "extend_budget"
    # Without matching blocks the inbox payload stays verbatim.
    undecorated = anomaly_inbox_service.attach_inbox_actions(inbox.to_dict(), blocks=[])
    assert all("action" not in item for item in undecorated["items"])
    # Non-precheck blocks never decorate.
    foreign = anomaly_inbox_service.attach_inbox_actions(
        inbox.to_dict(), blocks=[_precheck_block(code="budget_exceeded")]
    )
    assert all("action" not in item for item in foreign["items"])


def test_derive_gate_waits_reads_snapshot_gates() -> None:
    state = {
        **_TEAM_QUESTION,
        "collection": {
            "requests": [
                {
                    "requestId": "req-9",
                    "handoff": {
                        "lifecycle": "waiting_human",
                        "updatedAt": "2026-08-28T00:00:00Z",
                    },
                    "childRun": {"runId": "run-3"},
                },
                {
                    "requestId": "req-ok",
                    "handoff": {"lifecycle": "completed"},
                },
            ]
        },
        "programDelivery": {
            "humanReviewStatus": "waiting_human",
            "updatedAt": "2026-08-28T00:30:00Z",
            "outputRunId": "run-9",
            "humanGates": {
                "decisions": {
                    "H1_problem_understanding": "pending",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "pending",
                    "H4_external_output": "pending",
                }
            },
        },
    }
    waits = anomaly_inbox_service.derive_gate_waits(state)
    kinds = sorted(wait["gateKind"] for wait in waits)
    assert kinds == [
        "H1_problem_understanding",
        "H3_research_plan",
        "H4_external_output",
        "knowledge_handoff",
    ]
    handoff = next(wait for wait in waits if wait["gateKind"] == "knowledge_handoff")
    assert handoff == {
        "gateKind": "knowledge_handoff",
        "gateId": "req-9",
        "since": "2026-08-28T00:00:00Z",
        "runId": "run-3",
        "requestId": "req-9",
    }
    gate = next(
        wait for wait in waits if wait["gateKind"] == "H1_problem_understanding"
    )
    assert gate["since"] == "2026-08-28T00:30:00Z"
    assert gate["runId"] == "run-9"
    assert anomaly_inbox_service.derive_gate_waits(_state()) == []


# -- 误触防护: explicit confirmation is mandatory for CTA execution ----------


def test_confirmation_guard_refuses_missing_confirmation() -> None:
    with pytest.raises(anomaly_inbox_service.InboxActionConfirmationError) as excinfo:
        anomaly_inbox_service.assert_extend_budget_confirmation(
            confirmed=False,
            run_id="run-7",
            stage_id="hypothesis",
            stage_limit_tokens=300_000,
            suggested_extension_tokens=260_000,
        )
    assert excinfo.value.code == "inbox_action_confirmation_required"


def test_confirmation_guard_refuses_invalid_amounts_and_targets() -> None:
    cases = [
        (
            {
                "run_id": "",
                "stage_id": "hypothesis",
                "stage_limit_tokens": 300_000,
                "suggested_extension_tokens": 260_000,
            },
            "inbox_action_run_required",
        ),
        (
            {
                "run_id": "run-7",
                "stage_id": "",
                "stage_limit_tokens": 300_000,
                "suggested_extension_tokens": 260_000,
            },
            "inbox_action_stage_required",
        ),
        (
            {
                "run_id": "run-7",
                "stage_id": "hypothesis",
                "stage_limit_tokens": 0,
                "suggested_extension_tokens": 260_000,
            },
            "inbox_action_stage_limit_invalid",
        ),
        (
            {
                "run_id": "run-7",
                "stage_id": "hypothesis",
                "stage_limit_tokens": 300_000,
                "suggested_extension_tokens": 0,
            },
            "inbox_action_extension_invalid",
        ),
    ]
    for kwargs, code in cases:
        with pytest.raises(
            anomaly_inbox_service.InboxActionConfirmationError
        ) as excinfo:
            anomaly_inbox_service.assert_extend_budget_confirmation(
                confirmed=True, **kwargs
            )
        assert excinfo.value.code == code


def test_confirmation_guard_accepts_explicit_confirmation() -> None:
    anomaly_inbox_service.assert_extend_budget_confirmation(
        confirmed=True,
        run_id="run-7",
        stage_id="hypothesis",
        stage_limit_tokens=300_000,
        suggested_extension_tokens=260_000,
    )
