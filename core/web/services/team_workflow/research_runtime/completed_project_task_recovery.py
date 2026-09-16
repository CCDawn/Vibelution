"""Recover a Formal Ledger dispatch after its project task finished.

The Agent Session owns model execution and the research-project task owns
business completion.  This module only rebuilds the adapter's durable
completion cursor when an older adapter failure occurred in the small window
between those two facts.  It never starts a task, Turn, or model invocation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from core.research.workflow.contracts import PendingAction

from .completion_dependency import COMPLETION_PENDING
from .domain_ports import AgentTaskHandle
from .external_agent_task_failure import is_project_agent_task_reconciliation_lag
from .task_adapter_registry import resolve_agent_task_adapter


@dataclass(frozen=True)
class CompletedProjectTaskRecovery:
    """One externally completed task that can safely resume its old outbox."""

    run_id: str
    team_id: str
    node_run_id: str
    node_id: str
    outbox_action_id: str
    task_id: str
    session_id: str
    session_attempt: int
    turn_id: str
    action: PendingAction
    restore_voided_usage: bool

    def resume_problem_json(self) -> str:
        handle = AgentTaskHandle(
            session_id=self.session_id,
            session_attempt=self.session_attempt,
            task_id=self.task_id,
            turn_id=self.turn_id,
        )
        payload = {
            "code": COMPLETION_PENDING,
            "detail": (
                "completed research-project task is resuming its original "
                "Formal Ledger adapter dispatch"
            ),
            "dependency": "research_project_task",
            "dependencyStatus": "completed",
            "executionStatus": "completed",
            "recovery": "completed_project_task_reconciliation",
            "completionResume": {
                "actionId": self.action.action_id,
                "nodeRunId": self.node_run_id,
                "inputSnapshotHash": self.action.input_snapshot_hash,
                "handle": asdict(handle),
                "reservation": {
                    "reservationId": f"reservation-{self.node_run_id}",
                    "runId": self.run_id,
                    "nodeRunId": self.node_run_id,
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)


def find_completed_project_task_recovery(
    store: Any,
    *,
    run: Any,
) -> CompletedProjectTaskRecovery | None:
    """Read a single exact recovery candidate outside the Ledger transaction.

    The project-task API is deliberately read-only here.  The transaction
    later repeats all Ledger-local predicates before changing any state, so a
    stale candidate is a no-op instead of a widened recovery.
    """

    if not str(getattr(run, "project_id", "") or "").strip():
        return None
    rows = store.read(
        lambda repo: repo.execute(
            """
            SELECT na.node_run_id, na.node_id, na.status, na.problem_json,
                   oa.action_id, oa.payload_json, oa.last_problem_json,
                   ea.session_id, ea.session_attempt, ea.task_id, ea.turn_id,
                   br.status, br.settled_json
            FROM node_attempts na
            JOIN outbox_actions oa
              ON oa.node_run_id = na.node_run_id
             AND oa.action_kind = 'adapter_dispatch'
             AND oa.status = 'failed'
            JOIN execution_anchors ea ON ea.node_run_id = na.node_run_id
            LEFT JOIN budget_receipts br
              ON br.reservation_id = 'reservation-' || na.node_run_id
            WHERE na.run_id = ?
              AND na.status IN ('failed', 'blocked')
            ORDER BY na.updated_at_ms DESC, oa.updated_at_ms DESC
            """,
            (run.run_id,),
        ).fetchall()
    )
    candidates = [
        candidate
        for row in rows or ()
        if (
            candidate := _candidate_from_row(
                row,
                run_id=str(run.run_id),
                team_id=str(run.team_id),
            )
        )
        is not None
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    try:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            get_research_project_agent_task_status,
        )

        tasks = get_research_project_agent_task_status(
            candidate.team_id,
            str(run.project_id),
        ).get("tasks")
    except Exception:  # noqa: BLE001 - the operator can reconcile again later
        return None
    if not isinstance(tasks, list):
        return None
    matched = [
        task
        for task in tasks
        if isinstance(task, dict) and _task_matches_candidate(task, candidate)
    ]
    return candidate if len(matched) == 1 else None


def reopen_completed_project_task_recovery(
    uow: Any,
    *,
    candidate: CompletedProjectTaskRecovery | None,
    now_ms: int,
) -> CompletedProjectTaskRecovery | None:
    """Re-arm one validated formal adapter row in the caller's transaction."""

    if candidate is None:
        return None
    row = uow.repository.execute(
        """
        SELECT na.status, oa.status, ea.session_id, ea.session_attempt,
               ea.task_id, ea.turn_id
        FROM node_attempts na
        JOIN outbox_actions oa ON oa.action_id = ?
        JOIN execution_anchors ea ON ea.node_run_id = na.node_run_id
        WHERE na.node_run_id = ?
          AND na.run_id = ?
          AND oa.node_run_id = na.node_run_id
          AND oa.action_kind = 'adapter_dispatch'
        """,
        (candidate.outbox_action_id, candidate.node_run_id, candidate.run_id),
    ).fetchone()
    if row is None:
        return None
    attempt_status, outbox_status, session_id, session_attempt, task_id, turn_id = row
    if (
        str(attempt_status) not in {"failed", "blocked"}
        or str(outbox_status) != "failed"
        or str(session_id or "") != candidate.session_id
        or _positive_int(session_attempt) != candidate.session_attempt
        or str(task_id or "") != candidate.task_id
        or str(turn_id or "") != candidate.turn_id
    ):
        return None
    if candidate.restore_voided_usage:
        uow.repository.execute(
            """
            UPDATE budget_receipts
            SET status = 'settled', updated_at_ms = ?
            WHERE reservation_id = ? AND status = 'voided'
            """,
            (now_ms, f"reservation-{candidate.node_run_id}"),
        )
        if uow.repository.affected() != 1:
            return None
    uow.repository.execute(
        """
        UPDATE node_attempts
        SET status = 'dispatching', problem_json = ?, finished_at_ms = NULL,
            updated_at_ms = ?
        WHERE node_run_id = ?
        """,
        (candidate.resume_problem_json(), now_ms, candidate.node_run_id),
    )
    uow.repository.execute(
        """
        UPDATE outbox_actions
        SET status = 'pending', lease_owner = NULL, lease_expires_at_ms = NULL,
            available_at_ms = ?, attempt_count = 0, lease_recovery_count = 0,
            last_problem_json = ?, updated_at_ms = ?
        WHERE action_id = ?
        """,
        (
            now_ms,
            candidate.resume_problem_json(),
            now_ms,
            candidate.outbox_action_id,
        ),
    )
    uow.repository.execute(
        "UPDATE execution_anchors SET status = 'recovery_pending' WHERE node_run_id = ?",
        (candidate.node_run_id,),
    )
    return candidate


def _candidate_from_row(
    row: Any,
    *,
    run_id: str,
    team_id: str,
) -> CompletedProjectTaskRecovery | None:
    (
        node_run_id,
        node_id,
        _attempt_status,
        attempt_problem,
        outbox_action_id,
        raw_action,
        outbox_problem,
        session_id,
        session_attempt,
        task_id,
        turn_id,
        budget_status,
        budget_settled_json,
    ) = row
    normalized_node_run_id = str(node_run_id or "").strip()
    normalized_task_id = str(task_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_session_attempt = _positive_int(session_attempt)
    if not all(
        (
            normalized_node_run_id,
            normalized_task_id,
            normalized_session_id,
            normalized_turn_id,
            normalized_session_attempt > 0,
        )
    ):
        return None
    error_task_id = _lagging_project_task_id(attempt_problem) or _lagging_project_task_id(
        outbox_problem
    )
    if error_task_id != normalized_task_id:
        return None
    try:
        action = PendingAction.from_dict(json.loads(str(raw_action or "{}")))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    spec = resolve_agent_task_adapter(action.node_id)
    if (
        action.run_id != run_id
        or action.node_run_id != normalized_node_run_id
        or action.node_id != str(node_id or "")
        or spec is None
        or spec.family != "research_project"
    ):
        return None
    restore_voided_usage = False
    if str(budget_status or "") == "voided":
        restore_voided_usage = _has_observed_usage(budget_settled_json)
        if not restore_voided_usage:
            return None
    elif str(budget_status or "") not in {"reserved", "settled"}:
        return None
    return CompletedProjectTaskRecovery(
        run_id=run_id,
        team_id=team_id,
        node_run_id=normalized_node_run_id,
        node_id=str(node_id),
        outbox_action_id=str(outbox_action_id),
        task_id=normalized_task_id,
        session_id=normalized_session_id,
        session_attempt=normalized_session_attempt,
        turn_id=normalized_turn_id,
        action=action,
        restore_voided_usage=restore_voided_usage,
    )


def _lagging_project_task_id(raw_problem: Any) -> str:
    """Extract only the current code or its historical generic wrapper."""

    try:
        problem = raw_problem if isinstance(raw_problem, dict) else json.loads(
            str(raw_problem or "{}")
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(problem, dict):
        return ""
    if is_project_agent_task_reconciliation_lag(problem):
        return str(problem.get("taskId") or "").strip()
    if str(problem.get("code") or "").strip() != "adapter_execution_exception":
        return ""
    detail = problem.get("detail")
    if not is_project_agent_task_reconciliation_lag(detail):
        return ""
    try:
        nested = detail if isinstance(detail, dict) else json.loads(str(detail))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return str(nested.get("taskId") or "").strip() if isinstance(nested, dict) else ""


def _has_observed_usage(raw: Any) -> bool:
    try:
        payload = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    usage = payload.get("usage")
    invocations = payload.get("invocations")
    return bool(usage) or bool(invocations)


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _task_matches_candidate(
    task: dict[str, Any], candidate: CompletedProjectTaskRecovery
) -> bool:
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    return (
        str(task.get("taskId") or "") == candidate.task_id
        and str(task.get("status") or "").lower() == "completed"
        and str(task.get("workflowRunId") or "") == candidate.run_id
        and str(task.get("nodeRunId") or "") == candidate.node_run_id
        and str(task.get("sessionId") or "") == candidate.session_id
        and _positive_int(task.get("sessionAttempt")) == candidate.session_attempt
        and str(turn.get("turnId") or "") == candidate.turn_id
    )
