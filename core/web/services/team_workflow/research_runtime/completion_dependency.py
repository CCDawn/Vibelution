"""Resume business completion after execution, without starting another turn.

Session owns execution; Registry owns invocation evidence; the adapter owns
artifact verification and Ledger completion. This envelope is a durable cursor
for the latter, never another copy of a Session transcript or receipt.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from typing import Any

from core.research.workflow.contracts import PendingAction
from .challenge_turn_policy import current_challenge_task_resume_problem
from .domain_ports import AgentTaskHandle

COMPLETION_PENDING = "agent_completion_dependency_pending"


class CompletionDependencyPending(RuntimeError):
    def __init__(self, message: str, *, snapshot: dict[str, Any], handle: AgentTaskHandle | None = None):
        super().__init__(message)
        self.snapshot = dict(snapshot)
        self.handle = handle
        self.resume: dict[str, Any] = {}


def completion_resume(action: PendingAction) -> tuple[AgentTaskHandle, dict[str, Any]] | None:
    problem = current_challenge_task_resume_problem()
    if problem.get("code") != COMPLETION_PENDING:
        return None
    cursor = problem.get("completionResume") or {}
    if (cursor.get("actionId") != action.action_id
            or cursor.get("nodeRunId") != action.node_run_id
            or cursor.get("inputSnapshotHash") != action.input_snapshot_hash):
        raise ValueError("completion resume does not match the original action")
    handle = AgentTaskHandle(**cursor["handle"])
    if not handle.session_id or not handle.turn_id or handle.scoped_handles:
        raise ValueError("completion resume requires one bound Session turn")
    return replace(handle, scoped_handles=()), dict(cursor["reservation"])


def bind_completion_resume(error: CompletionDependencyPending, action: PendingAction,
                           handle: AgentTaskHandle, reservation: dict[str, Any]) -> None:
    handle = error.handle or handle
    if handle.scoped_handles:
        raise ValueError("scalar completion resume cannot replace a candidate fan-out")
    error.resume = {
        "actionId": action.action_id,
        "nodeRunId": action.node_run_id,
        "inputSnapshotHash": action.input_snapshot_hash,
        "handle": asdict(handle),
        "reservation": dict(reservation),
    }


def receipt_delivery_state(uow: Any, action: PendingAction, handle: AgentTaskHandle) -> tuple[set[str], list[list[Any]]]:
    rows = uow.repository.execute(
        "SELECT action_id, status, updated_at_ms FROM outbox_actions WHERE run_id = ? AND action_kind = 'reconcile' "
        "AND json_extract(payload_json, '$.kind') = 'challenge_model_invocation_receipt_persist' "
        "AND json_extract(payload_json, '$.receipt.scope.formalNodeRunId') = ? "
        "AND json_extract(payload_json, '$.receipt.scope.sessionId') = ? "
        "AND json_extract(payload_json, '$.receipt.scope.turnId') = ? ORDER BY action_id",
        (action.run_id, action.node_run_id, handle.session_id, handle.turn_id),
    ).fetchall()
    return {str(row[1]) for row in rows}, [[row[0], row[2]] for row in rows if row[1] == "succeeded"]


def defer_completion(store: Any, *, outbox: Any, action: PendingAction,
                     error: CompletionDependencyPending, owner: str, now_ms: int) -> None:
    """Wait on receipt delivery, not the model retry counter or execution clock."""
    from .block_projection import apply_node_run_block
    handle = AgentTaskHandle(**error.resume["handle"])
    compensation: str | None = None

    def mutate(uow):
        nonlocal compensation
        statuses, delivered = receipt_delivery_state(uow, action, handle)
        previous = json.loads(outbox.last_problem_json or "{}")
        # Delivery can commit between the Registry read and this transaction.
        # Allow one fresh read in that race; a permanently missing readback is
        # then exposed instead of polling an already-finished delivery forever.
        pending = bool(statuses & {"pending", "leased"}) or (
            bool(delivered) and delivered != previous.get("deliveredReceipts")
        )
        problem = {
            "code": COMPLETION_PENDING,
            "detail": str(error),
            "dependency": "model_invocation_receipt",
            "dependencyStatus": "pending" if pending else "unavailable",
            "deliveredReceipts": delivered,
            "executionStatus": str(error.snapshot.get("terminalStatus") or ""),
            "completionResume": error.resume,
        }
        encoded = json.dumps(problem, ensure_ascii=False)
        if pending:
            uow.repository.requeue_outbox(outbox.action_id, owner, now_ms,
                                         retry_at_ms=now_ms + 5_000, problem_json=encoded,
                                         reset_attempts=True)
        else:
            if not uow.repository.fail_outbox(outbox.action_id, owner, now_ms, encoded):
                return
            # Do not rewrite Session/Task or its execution anchor to failed.
            apply_node_run_block(uow, run_id=action.run_id, node_run_id=action.node_run_id,
                                 node_id=action.node_id, problem=problem, now_ms=now_ms,
                                 actor_id=owner, correlation_id=action.action_id,
                                 update_attempt=False)
            # Same-transaction compensation: without it the attempt's budget
            # reservation stays 'reserved' forever and its full estimate keeps
            # occupying the stage admission window (zombie attempt lockout).
            from .budget_authority_adapter import (
                compensate_terminal_attempt_reservation_in_uow,
            )
            compensation = compensate_terminal_attempt_reservation_in_uow(
                uow, run_id=action.run_id, node_run_id=action.node_run_id,
                reason="completion_dependency_unavailable_compensation",
                correlation_id=action.action_id, now_ms=now_ms,
            )

    store.submit(mutate, force_flush=True).result(timeout=30)
    if compensation in {"settled", "voided"}:
        from .adapter_dispatch_worker import _record_scene_event
        _record_scene_event(
            "completion_dependency.reservation_compensated",
            outcome=compensation,
            fields={"runId": action.run_id, "nodeRunId": action.node_run_id,
                    "reservationId": f"reservation-{action.node_run_id}",
                    "result": compensation},
        )


def wake_receipt_completion(uow: Any, *, receipt: dict[str, Any], now_ms: int) -> None:
    """A matching delivery wakes only the original, still-current completion."""
    scope = receipt["scope"]
    run_id, node_run_id = receipt["runId"], receipt["nodeRunId"]
    attempt = uow.repository.get_attempt(node_run_id)
    run = uow.repository.get_run(run_id)
    if run is None or attempt is None or run.status not in {"running", "blocked"}:
        return
    latest = uow.repository.latest_attempt(run_id, attempt.node_id)
    if latest is None or latest.node_run_id != node_run_id or attempt.status != "running":
        return
    rows = uow.repository.execute(
        "SELECT action_id, last_problem_json FROM outbox_actions "
        "WHERE run_id = ? AND node_run_id = ? AND action_kind = 'adapter_dispatch' "
        "AND status IN ('pending', 'failed')", (run_id, node_run_id),
    ).fetchall()
    for action_id, raw in rows:
        problem = json.loads(raw or "{}")
        cursor = problem.get("completionResume") or {}
        handle = cursor.get("handle") or {}
        if (problem.get("code") != COMPLETION_PENDING
                or cursor.get("nodeRunId") != node_run_id
                or handle.get("session_id") != scope.get("sessionId")
                or handle.get("turn_id") != scope.get("turnId")
                or handle.get("task_id") != scope.get("taskId")):
            continue
        if run.status == "blocked":
            run_problem = json.loads(run.blocked_problem_json or "{}")
            if (run.active_node_id != attempt.node_id
                    or run_problem.get("code") != COMPLETION_PENDING):
                continue
            uow.repository.update_run_status(
                run_id, run.team_id, "running", now_ms, blocked_problem_json=None,
            )
        uow.repository.execute(
            "UPDATE outbox_actions SET status='pending', available_at_ms=?, "
            "lease_owner=NULL, lease_expires_at_ms=NULL, attempt_count=0, updated_at_ms=? WHERE action_id=?",
            (now_ms, now_ms, action_id),
        )
        from core.research.workflow.ledger import EventRecord
        from .ids import new_id
        sequence = uow.repository.advance_last_sequence(run_id, 1, now_ms)
        if sequence is not None:
            uow.repository.insert_event(EventRecord(
                run_id=run_id, sequence=sequence, event_id=new_id("evt"),
                run_version=run.run_version, event_type="node_completion_resumed",
                actor_json=json.dumps({"actorType": "system", "actorId": "receipt-persistence-worker"}),
                correlation_id=action_id, causation_id=None,
                payload_json=json.dumps({"nodeRunId": node_run_id, "nodeId": attempt.node_id,
                                         "sessionId": scope["sessionId"], "turnId": scope["turnId"]}),
                occurred_at_ms=now_ms,
            ))
