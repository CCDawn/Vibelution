"""Shared fixtures for Workflow Ledger tests (T1-T6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.research.workflow.ledger import (
    CommandRecord,
    EventRecord,
    NodeAttemptRecord,
    OutboxRecord,
    RunRecord,
    WorkflowLedgerStore,
)

FIXED_NOW_MS = 1_750_000_000_000


def open_ledger_store(path: Path, **overrides: Any) -> WorkflowLedgerStore:
    store = WorkflowLedgerStore(
        path,
        queue_size=int(overrides.get("queue_size", 64)),
        enqueue_timeout_ms=int(overrides.get("enqueue_timeout_ms", 100)),
        read_pool_capacity=int(overrides.get("read_pool_capacity", 2)),
    )
    store.open()
    return store


def build_run_record(
    run_id: str = "run-test",
    *,
    team_id: str = "research-team",
    workflow_id: str = "challenge-cup-research",
    workflow_version_id: str = "challenge-cup-research-v2.1.0",
    thread_id: str | None = None,
    status: str = "created",
    run_version: int = 1,
    last_event_sequence: int = 0,
    input_snapshot_hash: str = "a" * 64,
    parent_run_id: str | None = None,
    created_at_ms: int = FIXED_NOW_MS,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        team_id=team_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        thread_id=thread_id or f"thread-{run_id}",
        project_id="challenge-sci-096",
        question_id="SCI-096",
        status=status,
        run_version=run_version,
        last_event_sequence=last_event_sequence,
        input_snapshot_json=json.dumps({"snapshotHash": input_snapshot_hash}),
        input_snapshot_hash=input_snapshot_hash,
        safety_limits_json=json.dumps(
            {
                "stageTokens": 250000,
                "maxToolCalls": 300,
                "maxSeconds": 21600,
                "autoRetries": 2,
            }
        ),
        binding_snapshot_set_id="binding-set-1",
        active_node_id=None,
        parent_run_id=parent_run_id,
        forked_from_checkpoint_id=None,
        completion_kind=None,
        terminal_reason=None,
        blocked_problem_json=None,
        created_at_ms=created_at_ms,
        updated_at_ms=created_at_ms,
        completed_at_ms=None,
    )


def build_command_record(
    command_id: str = "cmd-1",
    *,
    run_id: str = "run-test",
    team_id: str = "research-team",
    node_id: str | None = "source_finding",
    command_kind: str = "start_node",
    expected_run_version: int = 1,
    accepted_run_version: int | None = 1,
    idempotency_key: str = "key-1",
    request_hash: str = "h" * 64,
    status: str = "accepted",
    created_at_ms: int = FIXED_NOW_MS,
) -> CommandRecord:
    return CommandRecord(
        command_id=command_id,
        run_id=run_id,
        team_id=team_id,
        node_id=node_id,
        command_kind=command_kind,
        expected_run_version=expected_run_version,
        accepted_run_version=accepted_run_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        request_json=json.dumps({"command": command_kind}),
        requested_by_json=json.dumps({"actorType": "user", "actorId": "u-1"}),
        status=status,
        result_json=None,
        problem_json=None,
        created_at_ms=created_at_ms,
        completed_at_ms=None,
    )


def build_attempt_record(
    node_run_id: str = "nr-test-1",
    *,
    run_id: str = "run-test",
    node_id: str = "source_finding",
    attempt: int = 1,
    actor_kind: str = "agent",
    status: str = "starting",
    command_id: str = "cmd-1",
    input_snapshot_hash: str = "a" * 64,
    started_at_ms: int = FIXED_NOW_MS,
    problem_json: str | None = None,
) -> NodeAttemptRecord:
    return NodeAttemptRecord(
        node_run_id=node_run_id,
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind=actor_kind,
        status=status,
        command_id=command_id,
        binding_snapshot_id=None,
        input_snapshot_hash=input_snapshot_hash,
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=problem_json,
        started_at_ms=started_at_ms,
        updated_at_ms=started_at_ms,
        finished_at_ms=None,
    )


def build_outbox_record(
    action_id: str = "act-1",
    *,
    run_id: str = "run-test",
    command_id: str = "cmd-1",
    action_kind: str = "graph_dispatch",
    status: str = "pending",
    available_at_ms: int = FIXED_NOW_MS,
    idempotency_key: str | None = None,
) -> OutboxRecord:
    return OutboxRecord(
        action_id=action_id,
        run_id=run_id,
        command_id=command_id,
        node_run_id=None,
        action_kind=action_kind,
        idempotency_key=idempotency_key or f"outbox:{action_id}",
        payload_json=json.dumps({"actionId": action_id}),
        status=status,
        attempt_count=0,
        available_at_ms=available_at_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=FIXED_NOW_MS,
        updated_at_ms=FIXED_NOW_MS,
    )


def build_event_record(
    sequence: int,
    *,
    run_id: str = "run-test",
    run_version: int = 1,
    event_type: str = "run_created",
    event_id: str | None = None,
    correlation_id: str = "corr-1",
) -> EventRecord:
    return EventRecord(
        run_id=run_id,
        sequence=sequence,
        event_id=event_id or f"evt-{sequence}",
        run_version=run_version,
        event_type=event_type,
        actor_json=json.dumps({"actorType": "system", "actorId": "ledger"}),
        correlation_id=correlation_id,
        causation_id=None,
        payload_json=json.dumps({"sequence": sequence}),
        occurred_at_ms=FIXED_NOW_MS,
    )
