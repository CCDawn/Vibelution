"""T1 RED: contract serialization — frozen dataclasses, camelCase API
boundary, canonical JSON hash stability."""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import (
    ActorReadiness,
    ActorRef,
    BudgetReadiness,
    CommandOffer,
    CommandReceipt,
    CommandRequest,
    ExecutionAnchor,
    ExecutionReceipt,
    NodeReadiness,
    PendingAction,
    ReadinessBlocker,
    Remediation,
    RemediationKind,
    WorkflowCommandKind,
    WorkflowEventEnvelope,
    WorkflowEventType,
    WorkflowProblem,
    WorkflowProblemCategory,
    canonical_json,
    sha256_hex,
)
from core.research.workflow.models import ActorKind, ArtifactRef
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_command_request_hash_is_stable_and_scope_exact() -> None:
    request = CommandRequest(
        command_id="cmd-skip",
        run_id="run-1",
        team_id="research-team",
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        expected_run_version=17,
        idempotency_key="ui:run-1:source_finding:start:v17",
        payload={"extra": 1},
        requested_by=ActorRef("user", "u-1"),
        requested_at_ms=FIXED_NOW_MS,
    )
    hash_a = request.request_hash()
    hash_b = request.request_hash()
    assert hash_a == hash_b
    assert len(hash_a) == 64
    # 相同业务字段、不同服务端时间/commandId 不改变 hash。
    again = CommandRequest(
        command_id="cmd-different",
        run_id="run-1",
        team_id="research-team",
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        expected_run_version=17,
        idempotency_key="ui:run-1:source_finding:start:v17",
        payload={"extra": 1},
        requested_by=ActorRef("user", "u-1"),
        requested_at_ms=FIXED_NOW_MS + 1000,
    )
    assert again.request_hash() == hash_a
    # payload 改变则 hash 改变。
    changed = CommandRequest(
        command_id="cmd-x",
        run_id="run-1",
        team_id="research-team",
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        expected_run_version=17,
        idempotency_key="ui:run-1:source_finding:start:v17",
        payload={"extra": 2},
        requested_by=ActorRef("user", "u-1"),
        requested_at_ms=FIXED_NOW_MS,
    )
    assert changed.request_hash() != hash_a


def test_command_offer_dict_uses_camel_case() -> None:
    offer = CommandOffer(
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        available=True,
        label="开始任务",
        reason_code="",
        blocker_ids=(),
        idempotency_key="ui:offer-1",
        expected_run_version=17,
        payload={},
    )
    payload = offer.to_dict()
    assert payload["expectedRunVersion"] == 17
    assert payload["idempotencyKey"] == "ui:offer-1"
    assert payload["command"] == "start_node"


def test_command_receipt_roundtrip() -> None:
    receipt = CommandReceipt(
        command_id="cmd-1",
        run_id="run-1",
        status="accepted",
        accepted_run_version=18,
        idempotency_key="k",
        latest_event_sequence=74,
    )
    payload = receipt.to_dict()
    assert payload["acceptedRunVersion"] == 18
    assert payload["latestEventSequence"] == 74


def test_execution_anchor_completeness_per_actor() -> None:
    agent = ExecutionAnchor(
        anchor_id="anchor-1",
        node_run_id="nr-1",
        actor_kind=ActorKind.AGENT,
        agent_id="agent-1",
        session_id="session-1",
        session_attempt=1,
        task_id="task-1",
        turn_id="turn-1",
    )
    assert agent.is_complete()
    incomplete = ExecutionAnchor(
        anchor_id="anchor-2",
        node_run_id="nr-2",
        actor_kind=ActorKind.AGENT,
        agent_id="agent-1",
        session_id="",
        task_id="",
        turn_id="",
    )
    assert not incomplete.is_complete()
    assert incomplete.missing_fields() == ("session_id", "session_attempt", "task_id", "turn_id")
    system = ExecutionAnchor(
        anchor_id="anchor-3", node_run_id="nr-3", actor_kind=ActorKind.SYSTEM, system_action_id="act-1"
    )
    assert system.is_complete()
    human = ExecutionAnchor(
        anchor_id="anchor-4", node_run_id="nr-4", actor_kind=ActorKind.HUMAN, human_task_id="ht-1"
    )
    assert human.is_complete()


def test_pending_action_and_execution_receipt_roundtrip() -> None:
    pending = PendingAction(
        action_id="act-1",
        run_id="run-1",
        node_run_id="nr-1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="bs-1",
        budget_policy_hash="b" * 64,
    )
    decoded = PendingAction.from_dict(pending.to_dict())
    assert decoded == pending

    problem = WorkflowProblem(
        code="source_candidates_missing",
        category=WorkflowProblemCategory.USER_FIXABLE,
        title="没有可提炼的资料",
        detail="资料权威存储中没有属于当前运行的候选资料。",
        retryable=False,
        scope={"teamId": "research-team", "runId": "run-1", "nodeId": "source_finding"},
        remediation=Remediation(
            kind=RemediationKind.NAVIGATE_NODE,
            label="返回资料寻找",
            target_node_id="source_finding",
        ),
    )
    receipt = ExecutionReceipt(
        action_id="act-1",
        node_run_id="nr-1",
        outcome="failed",
        artifact_receipt_ids=(),
        execution_anchor_id=None,
        budget_receipt_id=None,
        problem=problem,
        completed_at_ms=FIXED_NOW_MS,
    )
    decoded_receipt = ExecutionReceipt.from_dict(receipt.to_dict())
    assert decoded_receipt.action_id == "act-1"
    assert decoded_receipt.problem is not None
    assert decoded_receipt.problem.code == "source_candidates_missing"
    assert decoded_receipt.problem.remediation is not None
    assert decoded_receipt.problem.remediation.target_node_id == "source_finding"

    with pytest.raises(ValueError):
        decoded_receipt.assert_matches("act-other", "nr-1")


def test_node_readiness_roundtrip_and_cache_key() -> None:
    readiness = NodeReadiness(
        run_id="run-1",
        team_id="research-team",
        node_id="source_extraction",
        run_version=17,
        ready=False,
        evaluated_at_ms=FIXED_NOW_MS,
        domain_revision_vector={"source_collection": "rev-1"},
        accepted_handoff_ids=("ho-1",),
        input_artifact_refs=(
            ArtifactRef("source_candidate_batch:abc", "batch", "1.0", "h" * 64),
        ),
        actor=ActorReadiness(configured=True, resolvable=True, binding_snapshot_id="bs-1", agent_id="a-1"),
        budget=BudgetReadiness(policy_hash="p-1", available=True, reason="ok"),
        blockers=(
            ReadinessBlocker(
                code="source_candidates_missing",
                title="没有可提炼的资料",
                detail="候选资料缺失",
                remediation=Remediation(
                    kind=RemediationKind.NAVIGATE_NODE,
                    label="返回资料寻找",
                    target_node_id="source_finding",
                ),
            ),
        ),
    )
    decoded = NodeReadiness.from_dict(readiness.to_dict())
    assert decoded.ready is False
    assert decoded.blockers[0].code == "source_candidates_missing"
    assert decoded.actor.agent_id == "a-1"
    assert decoded.cache_key() == readiness.cache_key()
    # revision vector 变化后缓存键不同。
    changed = NodeReadiness(
        run_id="run-1",
        team_id="research-team",
        node_id="source_extraction",
        run_version=17,
        ready=False,
        evaluated_at_ms=FIXED_NOW_MS,
        domain_revision_vector={"source_collection": "rev-2"},
        accepted_handoff_ids=(),
        input_artifact_refs=(),
        actor=readiness.actor,
        budget=readiness.budget,
    )
    assert changed.cache_key() != readiness.cache_key()


def test_event_envelope_roundtrip() -> None:
    envelope = WorkflowEventEnvelope(
        event_id="evt-1",
        sequence=5,
        team_id="research-team",
        workflow_id="challenge-cup-research",
        workflow_version_id="v2.1.0",
        run_id="run-1",
        run_version=17,
        event_type=WorkflowEventType.NODE_STARTING,
        actor={"actorType": "system", "actorId": "ledger"},
        correlation_id="corr-1",
        causation_id=None,
        payload={"nodeRunId": "nr-1"},
        occurred_at_ms=FIXED_NOW_MS,
    )
    decoded = WorkflowEventEnvelope.from_dict(envelope.to_dict())
    assert decoded == envelope


def test_canonical_json_deterministic() -> None:
    first = canonical_json({"b": 2, "a": {"d": 1, "c": 2}})
    second = canonical_json({"a": {"c": 2, "d": 1}, "b": 2})
    assert first == second
    parsed = json.loads(first)
    assert list(parsed.keys()) == ["a", "b"]
    assert sha256_hex({"x": 1}) == sha256_hex({"x": 1})
