"""Resume business completion after execution, without starting another turn.

Session owns execution; Registry owns invocation evidence; the adapter owns
artifact verification and Ledger completion. This envelope is a durable cursor
for the latter, never another copy of a Session transcript or receipt.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import time
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
    if handle.meeting_room_id:
        _receipt_handles(handle)
        return replace(handle, meeting_participants=tuple(handle.meeting_participants)), dict(cursor["reservation"])
    if not handle.session_id or not handle.turn_id or handle.scoped_handles:
        raise ValueError("completion resume requires one bound Session turn")
    return replace(handle, scoped_handles=(), meeting_participants=()), dict(cursor["reservation"])


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


def _receipt_handles(handle: AgentTaskHandle) -> tuple[dict[str, str], ...]:
    if not handle.meeting_room_id:
        return ({"sessionId": handle.session_id, "turnId": handle.turn_id, "taskId": handle.task_id},)
    participants = tuple(handle.meeting_participants)
    if (not handle.meeting_round_id or handle.scoped_handles or len(participants) < 2
            or len({item.get("sessionId") for item in participants}) != len(participants)
            or any(not all(item.get(key) for key in ("sessionId", "turnId", "taskId", "participantId"))
                or item["turnId"] != f"chat-room:{handle.meeting_round_id}:{item['participantId']}"
                for item in participants)):
        raise ValueError("meeting completion requires its frozen native speaker Turns")
    return participants


def receipt_delivery_state(uow: Any, action: PendingAction, handle: AgentTaskHandle) -> tuple[set[str], list[list[Any]]]:
    rows = []
    for participant in _receipt_handles(handle):
        rows.extend(_speaker_delivery_rows(uow, action, participant))
    return {str(row[1]) for row in rows}, sorted([[row[0], row[2]] for row in rows if row[1] == "succeeded"])


def _speaker_delivery_rows(uow: Any, action: PendingAction, participant: dict[str, str]) -> list:
    rows = uow.repository.execute(
        "SELECT action_id, status, updated_at_ms FROM outbox_actions WHERE run_id = ? AND action_kind = 'reconcile' "
        "AND json_extract(payload_json, '$.kind') = 'challenge_model_invocation_receipt_persist' "
        "AND json_extract(payload_json, '$.receipt.scope.formalNodeRunId') = ? "
        "AND json_extract(payload_json, '$.receipt.scope.sessionId') = ? "
        "AND json_extract(payload_json, '$.receipt.scope.turnId') = ? ORDER BY action_id",
        (action.run_id, action.node_run_id, participant["sessionId"], participant["turnId"]),
    ).fetchall()
    return rows


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
        pending = bool(handle.meeting_room_id and error.snapshot.get("meetingRunning")) or bool(statuses & {"pending", "leased"}) or (
            bool(delivered) and delivered != previous.get("deliveredReceipts")
        )
        problem = {
            "code": COMPLETION_PENDING,
            "detail": str(error),
            "dependency": "meeting" if error.snapshot.get("meetingRunning") else "model_invocation_receipt",
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
    _wake_completion(uow, run_id=receipt["runId"], node_run_id=receipt["nodeRunId"],
        scope=receipt["scope"], now_ms=now_ms)


def wake_meeting_completion(uow: Any, *, run_id: str, node_run_id: str,
                            room_id: str, round_id: str, now_ms: int) -> None:
    _wake_completion(uow, run_id=run_id, node_run_id=node_run_id, scope={},
        now_ms=now_ms, room_id=room_id, round_id=round_id)


def _wake_completion(uow: Any, *, run_id: str, node_run_id: str, scope: dict,
                     now_ms: int, room_id: str = "", round_id: str = "") -> None:
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
                or cursor.get("nodeRunId") != node_run_id):
            continue
        bound_turns = _receipt_handles(AgentTaskHandle(**handle)) if handle else ()
        if room_id:
            if handle.get("meeting_room_id") != room_id or handle.get("meeting_round_id") != round_id:
                continue
        elif not any(all(participant.get(key) == scope.get(key)
                for key in ("sessionId", "turnId", "taskId")) for participant in bound_turns):
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
                                         "sessionId": scope.get("sessionId", ""), "turnId": scope.get("turnId", ""),
                                         "roomId": room_id, "roundId": round_id}),
                occurred_at_ms=now_ms,
            ))


def _completion_redrive_candidates(repo: Any, limit: int) -> list[Any]:
    """Blocked runs whose completion cursor sits on a failed dispatch row."""
    return repo.execute(
        """
        SELECT o.action_id, o.run_id, o.node_run_id, o.payload_json,
               o.last_problem_json, r.team_id
        FROM outbox_actions o
        JOIN workflow_runs r ON r.run_id = o.run_id
        WHERE o.action_kind = 'adapter_dispatch'
          AND o.status = 'failed'
          AND json_extract(o.last_problem_json, '$.code') = ?
          AND r.status = 'blocked'
          AND json_extract(r.blocked_problem_json, '$.code') = ?
        ORDER BY o.updated_at_ms ASC, o.action_id ASC
        LIMIT ?
        """,
        (COMPLETION_PENDING, COMPLETION_PENDING, max(1, int(limit))),
    ).fetchall()


def _redrive_preconditions_hold(row: Any) -> tuple[Any, str, str, str, str] | None:
    """Read-only cursor/family/authority checks; None means keep the block.

    Fail-closed by construction: a missing or self-inconsistent cursor, a
    family without a completion authority, an authority that has not settled
    "completed", or a still-live turn all leave the run exactly as blocked.
    """

    # The outbox envelope id (row[0]) is deliberately not compared to the
    # payload identity (see _heal_pending_action_identity): heal a lag-walk
    # payload that omitted its run id instead of rejecting the row.
    _envelope_action_id, run_id, node_run_id, raw_payload, raw_problem, row_team_id = row
    try:
        action = PendingAction.from_dict(json.loads(str(raw_payload or "{}")))
        problem = json.loads(str(raw_problem or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    # The outbox envelope id is not the payload identity (see
    # _heal_pending_action_identity): heal a lag-walk payload that omitted
    # its run id instead of rejecting the row.
    if not action.run_id:
        action = replace(action, run_id=str(run_id or ""))
    if action.run_id != run_id:
        return None
    cursor = problem.get("completionResume") if isinstance(problem, dict) else None
    handle = cursor.get("handle") if isinstance(cursor, dict) else None
    if not isinstance(cursor, dict) or not isinstance(handle, dict):
        return None
    if (cursor.get("actionId") != action.action_id
            or cursor.get("nodeRunId") != action.node_run_id
            or action.node_run_id != node_run_id):
        return None
    session_id = str(handle.get("session_id") or "").strip()
    turn_id = str(handle.get("turn_id") or "").strip()
    task_id = str(handle.get("task_id") or "").strip()
    if not session_id or not turn_id or not task_id:
        return None
    from .task_adapter_registry import resolve_agent_task_adapter

    spec = resolve_agent_task_adapter(action.node_id)
    if spec is None or spec.family != "source_collection":
        # Only the source-collection family exposes a completion authority
        # today; every other family keeps its receipt-wake semantics untouched.
        return None
    team_id = str(row_team_id or "").strip()
    from .agent_turn_completion import _stage_task_work_already_complete

    if not _stage_task_work_already_complete(team_id=team_id, task_id=task_id):
        return None
    try:
        from core.web.services.session.turn_diagnostics import (
            get_session_turn_completion_snapshot,
        )

        snapshot = get_session_turn_completion_snapshot(session_id, turn_id)
    except Exception:  # noqa: BLE001 - unreadable execution keeps the block
        return None
    if not bool((snapshot or {}).get("terminal")):
        # A still-live turn must keep its wait semantics: re-arming a live
        # cursor would downgrade the resume to a fresh continuation path.
        return None
    return action, team_id, session_id, turn_id, task_id


def redrive_authority_complete_completions(
    store: Any, *, limit: int = 4, now_ms: int | None = None
) -> int:
    """Re-arm completion cursors whose domain authority already finished.

    :func:`wake_receipt_completion` can only fire when the original
    model-invocation receipt is delivered.  When the process that produced
    that receipt died before persisting it, the delivery never happens and
    the blocked run waits forever -- even though the node's real business
    work already settled "completed" on its domain authority (the
    source-collection stage completion gate; production run-50d3e53c54de).

    This sweep re-arms the original failed ``adapter_dispatch`` action in
    exactly that situation, so the ordinary dispatch path consumes the
    durable ``completionResume`` cursor (the agent-turn completion resume
    branch: re-read the settled terminal turn, never re-execute or continue
    it) and closes the node through the normal artifact/handoff commit.
    Fail-closed: the family must expose a completion authority, the
    authority must report "completed", and the cursor's turn must already be
    terminal -- anything else stays blocked.  The re-arm is the same
    single-transaction write shape as :func:`wake_receipt_completion`
    (requeue the failed row, unblock the run, emit
    ``node_completion_resumed``), so replays are idempotent: a row that is
    no longer failed, an attempt that is no longer running, or a run that is
    no longer blocked is a no-op.
    """

    effective_now = int(now_ms if now_ms is not None else time.time() * 1000)
    try:
        rows = store.read(lambda repo: _completion_redrive_candidates(repo, limit))
    except Exception:  # noqa: BLE001 - the sweep must never break its host
        return 0
    redriven = 0
    for row in rows or ():
        prepared = _redrive_preconditions_hold(row)
        if prepared is None:
            continue
        action, team_id, session_id, turn_id, task_id = prepared
        action_id, run_id = row[0], row[1]
        node_id = action.node_id
        node_run_id = action.node_run_id

        def mutate(
            uow,
            *,
            expected_action_id=action_id,
            expected_run_id=run_id,
            expected_node_run_id=node_run_id,
            expected_node_id=node_id,
            expected_session_id=session_id,
            expected_turn_id=turn_id,
            expected_task_id=task_id,
            cursor_action_id=action.action_id,
        ):
            run = uow.repository.get_run(expected_run_id)
            if run is None or run.status != "blocked":
                return False
            run_problem = json.loads(run.blocked_problem_json or "{}")
            if run_problem.get("code") != COMPLETION_PENDING:
                return False
            attempt = uow.repository.get_attempt(expected_node_run_id)
            if attempt is None or attempt.status != "running":
                return False
            latest = uow.repository.latest_attempt(expected_run_id, attempt.node_id)
            if latest is None or latest.node_run_id != expected_node_run_id:
                return False
            if run.active_node_id != attempt.node_id:
                return False
            outbox = uow.repository.get_outbox(expected_action_id)
            if outbox is None or outbox.status != "failed":
                return False
            row_problem = json.loads(outbox.last_problem_json or "{}")
            cursor = row_problem.get("completionResume") or {}
            cursor_handle = cursor.get("handle") or {}
            if (
                row_problem.get("code") != COMPLETION_PENDING
                or cursor.get("actionId") != cursor_action_id
                or cursor.get("nodeRunId") != expected_node_run_id
                or cursor_handle.get("session_id") != expected_session_id
                or cursor_handle.get("turn_id") != expected_turn_id
                or cursor_handle.get("task_id") != expected_task_id
            ):
                return False
            uow.repository.execute(
                "UPDATE outbox_actions SET status='pending', available_at_ms=?, "
                "lease_owner=NULL, lease_expires_at_ms=NULL, attempt_count=0, "
                "updated_at_ms=? WHERE action_id=? AND status='failed'",
                (effective_now, effective_now, expected_action_id),
            )
            uow.repository.update_run_status(
                expected_run_id,
                run.team_id,
                "running",
                effective_now,
                blocked_problem_json=None,
            )
            from core.research.workflow.ledger import EventRecord

            from .ids import new_id
            sequence = uow.repository.advance_last_sequence(expected_run_id, 1, effective_now)
            if sequence is not None:
                uow.repository.insert_event(EventRecord(
                    run_id=expected_run_id, sequence=sequence, event_id=new_id("evt"),
                    run_version=run.run_version, event_type="node_completion_resumed",
                    actor_json=json.dumps(
                        {"actorType": "system", "actorId": "completion-authority-redrive"}
                    ),
                    correlation_id=expected_action_id, causation_id=None,
                    payload_json=json.dumps({
                        "nodeRunId": expected_node_run_id,
                        "nodeId": expected_node_id,
                        "sessionId": expected_session_id,
                        "turnId": expected_turn_id,
                        "taskId": expected_task_id,
                        "authorityComplete": True,
                        "redrive": True,
                    }),
                    occurred_at_ms=effective_now,
                ))
            return True

        try:
            changed = bool(store.submit(mutate, force_flush=True).result(timeout=30))
        except Exception:  # noqa: BLE001 - one broken candidate is isolated
            changed = False
        if not changed:
            continue
        redriven += 1
        try:
            from core.web.services.runtime_scene_service import (
                record_runtime_scene_event_quietly,
            )

            record_runtime_scene_event_quietly(
                "team_workflow_orchestration",
                "completion_dependency",
                "completion_dependency.authority_complete_redrive",
                level="info",
                outcome="redriven",
                fields={
                    "runId": run_id,
                    "nodeRunId": node_run_id,
                    "nodeId": node_id,
                    "outboxActionId": action_id,
                    "taskId": task_id,
                    "teamId": team_id,
                },
            )
        except Exception:  # noqa: BLE001, S110 - telemetry cannot break recovery
            pass
    return redriven
