"""Persistence records — thin rows, no domain logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    team_id: str
    workflow_id: str
    workflow_version_id: str
    thread_id: str
    project_id: str
    question_id: str
    status: str
    run_version: int
    last_event_sequence: int
    input_snapshot_json: str
    input_snapshot_hash: str
    safety_limits_json: str
    binding_snapshot_set_id: str
    active_node_id: str | None
    parent_run_id: str | None
    forked_from_checkpoint_id: str | None
    completion_kind: str | None
    terminal_reason: str | None
    blocked_problem_json: str | None
    created_at_ms: int
    updated_at_ms: int
    completed_at_ms: int | None


@dataclass(frozen=True)
class CommandRecord:
    command_id: str
    run_id: str
    team_id: str
    node_id: str | None
    command_kind: str
    expected_run_version: int
    accepted_run_version: int | None
    idempotency_key: str
    request_hash: str
    request_json: str
    requested_by_json: str
    status: str
    result_json: str | None
    problem_json: str | None
    created_at_ms: int
    completed_at_ms: int | None


@dataclass(frozen=True)
class NodeAttemptRecord:
    node_run_id: str
    run_id: str
    node_id: str
    attempt: int
    actor_kind: str
    status: str
    command_id: str
    binding_snapshot_id: str | None
    input_snapshot_hash: str
    pending_action_id: str | None
    execution_anchor_id: str | None
    retry_of_node_run_id: str | None
    problem_json: str | None
    started_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    sequence: int
    event_id: str
    run_version: int
    event_type: str
    actor_json: str
    correlation_id: str
    causation_id: str | None
    payload_json: str
    occurred_at_ms: int


@dataclass(frozen=True)
class OutboxRecord:
    action_id: str
    run_id: str
    command_id: str | None
    node_run_id: str | None
    action_kind: str
    idempotency_key: str
    payload_json: str
    status: str
    attempt_count: int
    available_at_ms: int
    lease_owner: str | None
    lease_expires_at_ms: int | None
    last_problem_json: str | None
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True)
class CatalogRunAuthorization:
    """Immutable approval evidence for one real catalog batch scope."""

    authorization_id: str
    team_id: str
    plan_id: str
    batch_scope_json: str
    scope_hash: str
    approved_by: str
    approved_at_ms: int
    readiness_report_sha256: str
    record_hash: str
    created_at_ms: int
