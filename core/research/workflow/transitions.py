"""Domain transition functions — the only way ledger statuses may change.

Repository code never accepts arbitrary status strings; it calls these pure
functions. Terminal statuses cannot be moved back into a running state by
ordinary commands; redo creates a new attempt or forks a child run.
"""

from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class NodeAttemptStatus(str, Enum):
    STARTING = "starting"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    STALE = "stale"


class HandoffStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    WAITING_HUMAN = "waiting_human"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HumanTaskStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVISED = "revised"
    CANCELLED = "cancelled"


class ArtifactReceiptStatus(str, Enum):
    MATERIALIZED = "materialized"
    VERIFIED = "verified"


class BudgetReceiptStatus(str, Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    FAILED = "failed"
    VOIDED = "voided"


_TERMINAL_RUN = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.ARCHIVED}

RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.WAITING_HUMAN,
            RunStatus.BLOCKED,
            RunStatus.RECONCILIATION_REQUIRED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_HUMAN,
            RunStatus.BLOCKED,
            RunStatus.RECONCILIATION_REQUIRED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_HUMAN: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.BLOCKED,
            RunStatus.RECONCILIATION_REQUIRED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.BLOCKED: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.WAITING_HUMAN,
            RunStatus.RECONCILIATION_REQUIRED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RECONCILIATION_REQUIRED: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.WAITING_HUMAN,
            RunStatus.BLOCKED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.ARCHIVED,
        }
    ),
    RunStatus.SUCCEEDED: frozenset({RunStatus.ARCHIVED}),
    RunStatus.FAILED: frozenset({RunStatus.ARCHIVED}),
    RunStatus.CANCELLED: frozenset({RunStatus.ARCHIVED}),
    RunStatus.ARCHIVED: frozenset(),
}


def can_transition_run(current: RunStatus, target: RunStatus) -> bool:
    if current == target:
        return True
    return target in RUN_TRANSITIONS.get(current, frozenset())


def require_run_transition(current: RunStatus, target: RunStatus) -> None:
    if not can_transition_run(current, target):
        raise ValueError(f"illegal run transition {current.value} -> {target.value}")


NODE_ATTEMPT_TRANSITIONS: dict[NodeAttemptStatus, frozenset[NodeAttemptStatus]] = {
    NodeAttemptStatus.STARTING: frozenset(
        {
            NodeAttemptStatus.DISPATCHING,
            NodeAttemptStatus.RUNNING,
            NodeAttemptStatus.WAITING_HUMAN,
            NodeAttemptStatus.BLOCKED,
            NodeAttemptStatus.FAILED,
            NodeAttemptStatus.CANCELLED,
        }
    ),
    NodeAttemptStatus.DISPATCHING: frozenset(
        {
            NodeAttemptStatus.RUNNING,
            NodeAttemptStatus.WAITING_HUMAN,
            NodeAttemptStatus.SUCCEEDED,
            NodeAttemptStatus.BLOCKED,
            NodeAttemptStatus.FAILED,
            NodeAttemptStatus.CANCELLED,
        }
    ),
    NodeAttemptStatus.RUNNING: frozenset(
        {
            NodeAttemptStatus.WAITING_HUMAN,
            NodeAttemptStatus.SUCCEEDED,
            NodeAttemptStatus.FAILED,
            NodeAttemptStatus.BLOCKED,
            NodeAttemptStatus.CANCELLED,
        }
    ),
    NodeAttemptStatus.WAITING_HUMAN: frozenset(
        {
            NodeAttemptStatus.RUNNING,
            NodeAttemptStatus.SUCCEEDED,
            NodeAttemptStatus.FAILED,
            NodeAttemptStatus.BLOCKED,
            NodeAttemptStatus.CANCELLED,
        }
    ),
    NodeAttemptStatus.BLOCKED: frozenset({NodeAttemptStatus.CANCELLED, NodeAttemptStatus.STALE}),
    NodeAttemptStatus.SUCCEEDED: frozenset({NodeAttemptStatus.STALE}),
    NodeAttemptStatus.FAILED: frozenset({NodeAttemptStatus.STALE}),
    NodeAttemptStatus.CANCELLED: frozenset(),
    NodeAttemptStatus.STALE: frozenset(),
}


def can_transition_node_attempt(current: NodeAttemptStatus, target: NodeAttemptStatus) -> bool:
    if current == target:
        return True
    return target in NODE_ATTEMPT_TRANSITIONS.get(current, frozenset())


def require_node_attempt_transition(current: NodeAttemptStatus, target: NodeAttemptStatus) -> None:
    if not can_transition_node_attempt(current, target):
        raise ValueError(
            f"illegal node attempt transition {current.value} -> {target.value}"
        )


HANDOFF_TRANSITIONS: dict[HandoffStatus, frozenset[HandoffStatus]] = {
    HandoffStatus.PENDING: frozenset(
        {
            HandoffStatus.READY,
            HandoffStatus.WAITING_HUMAN,
            HandoffStatus.SUPERSEDED,
            HandoffStatus.FAILED,
        }
    ),
    HandoffStatus.READY: frozenset(
        {
            HandoffStatus.ACCEPTED,
            HandoffStatus.REJECTED,
            HandoffStatus.WAITING_HUMAN,
            HandoffStatus.SUPERSEDED,
            HandoffStatus.FAILED,
        }
    ),
    HandoffStatus.WAITING_HUMAN: frozenset(
        {
            HandoffStatus.ACCEPTED,
            HandoffStatus.REJECTED,
            HandoffStatus.SUPERSEDED,
            HandoffStatus.FAILED,
        }
    ),
    HandoffStatus.ACCEPTED: frozenset({HandoffStatus.SUPERSEDED}),
    HandoffStatus.REJECTED: frozenset({HandoffStatus.SUPERSEDED}),
    HandoffStatus.SUPERSEDED: frozenset(),
    HandoffStatus.FAILED: frozenset(),
}


def can_transition_handoff(current: HandoffStatus, target: HandoffStatus) -> bool:
    if current == target:
        return True
    return target in HANDOFF_TRANSITIONS.get(current, frozenset())


def require_handoff_transition(current: HandoffStatus, target: HandoffStatus) -> None:
    if not can_transition_handoff(current, target):
        raise ValueError(f"illegal handoff transition {current.value} -> {target.value}")


OUTBOX_TRANSITIONS: dict[OutboxStatus, frozenset[OutboxStatus]] = {
    OutboxStatus.PENDING: frozenset(
        {OutboxStatus.LEASED, OutboxStatus.CANCELLED, OutboxStatus.FAILED}
    ),
    OutboxStatus.LEASED: frozenset(
        {
            OutboxStatus.PENDING,
            OutboxStatus.SUCCEEDED,
            OutboxStatus.FAILED,
            OutboxStatus.CANCELLED,
        }
    ),
    OutboxStatus.SUCCEEDED: frozenset(),
    OutboxStatus.FAILED: frozenset(),
    OutboxStatus.CANCELLED: frozenset(),
}


def can_transition_outbox(current: OutboxStatus, target: OutboxStatus) -> bool:
    if current == target:
        return True
    return target in OUTBOX_TRANSITIONS.get(current, frozenset())


def require_outbox_transition(current: OutboxStatus, target: OutboxStatus) -> None:
    if not can_transition_outbox(current, target):
        raise ValueError(f"illegal outbox transition {current.value} -> {target.value}")


HUMAN_TASK_TRANSITIONS: dict[HumanTaskStatus, frozenset[HumanTaskStatus]] = {
    HumanTaskStatus.PENDING: frozenset(
        {
            HumanTaskStatus.ACCEPTED,
            HumanTaskStatus.REJECTED,
            HumanTaskStatus.REVISED,
            HumanTaskStatus.CANCELLED,
        }
    ),
    HumanTaskStatus.ACCEPTED: frozenset(),
    HumanTaskStatus.REJECTED: frozenset(),
    HumanTaskStatus.REVISED: frozenset(),
    HumanTaskStatus.CANCELLED: frozenset(),
}


def can_transition_human_task(current: HumanTaskStatus, target: HumanTaskStatus) -> bool:
    if current == target:
        return True
    return target in HUMAN_TASK_TRANSITIONS.get(current, frozenset())


def require_human_task_transition(current: HumanTaskStatus, target: HumanTaskStatus) -> None:
    if not can_transition_human_task(current, target):
        raise ValueError(f"illegal human task transition {current.value} -> {target.value}")


def is_terminal_run(status: RunStatus) -> bool:
    return status in _TERMINAL_RUN
