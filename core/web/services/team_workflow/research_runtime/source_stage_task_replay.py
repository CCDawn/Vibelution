"""Exact Source Collection task reuse for adapter timeout and retry lineage."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import WorkflowLedgerStore

_REUSABLE_ANCESTOR_STATUSES = frozenset({"queued", "running", "completed"})


def find_reusable_source_stage_task(
    *,
    store: WorkflowLedgerStore | None,
    action: PendingAction,
    team_id: str,
    source_run_id: str,
    stage_id: str,
    agent_id: str,
    agent_role: str,
) -> dict[str, Any] | None:
    """Return the exact live/completed task for this NodeRun or retry lineage.

    The lookup runs before Source Collection context construction.  It never
    searches by "latest" task: the current ``node_run_id`` and its direct
    Ledger ``retry_of_node_run_id`` parent are the only accepted identities.
    """

    from core.web.services.team_workflow.source_collection.stage_reconcile import (
        _find_source_collection_stage_session_task,
        _reconcile_source_collection_stage_session_task,
        _source_collection_stage_task_idempotency_key,
    )
    from core.web.services.team_workflow.source_collection.stage_session import (
        _AUTO_FORMAL_RETRY_STATUSES,
    )

    dead_stage_task_statuses = _AUTO_FORMAL_RETRY_STATUSES | {
        "cancelled",
        "interrupted",
    }

    node_run_ids, ancestor_attempt_statuses = _node_run_lineage(store, action)
    for index, node_run_id in enumerate(node_run_ids):
        is_current_node_run = index == 0
        if (
            not is_current_node_run
            and ancestor_attempt_statuses.get(node_run_id) == "succeeded"
        ):
            # An explicit rerun of a succeeded node (the only path that creates
            # an attempt after a succeeded parent) asks for regeneration: the
            # parent's completed task would replay its accepted turn and report
            # instant success without re-executing the stage. Crash recovery
            # keeps the reuse: only a succeeded parent is skipped.
            continue
        idempotency_key = _source_collection_stage_task_idempotency_key(
            team_id=team_id,
            run_id=source_run_id,
            stage_id=stage_id,
            agent_id=agent_id,
            agent_role=agent_role,
            task_id="",
            requested_key=f"agent-task:{node_run_id}",
        )
        task = _find_source_collection_stage_session_task(
            team_id,
            source_run_id,
            idempotency_key=idempotency_key,
        )
        if not isinstance(task, dict):
            continue
        _assert_task_identity(
            task,
            team_id=team_id,
            source_run_id=source_run_id,
            stage_id=stage_id,
            agent_id=agent_id,
            agent_role=agent_role,
        )
        if not _has_turn_anchor(task):
            continue
        was_active = str(task.get("status") or "").strip().lower() in {"queued", "running"}
        if was_active:
            # Parity with the start path: a queued/running task may be a
            # zombie whose turn already ended (for example a provider outage
            # after the last reconcile). Reconcile before reusing so a retry
            # never replays a dead turn.
            task = _reconcile_source_collection_stage_session_task(
                team_id,
                source_run_id,
                task,
            )
        status = str(task.get("status") or "").strip().lower()
        task_is_dead = was_active and status in dead_stage_task_statuses
        if (
            task_is_dead
            or (
                not is_current_node_run
                and status not in _REUSABLE_ANCESTOR_STATUSES
            )
        ):
            continue
        return {
            "teamId": team_id,
            "runId": source_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": str(task.get("sessionId") or "").strip(),
            "taskId": str(task.get("taskId") or "").strip(),
            "idempotencyKey": idempotency_key,
            "created": False,
            "alreadyPresent": True,
            "task": task,
            "turn": task.get("turn") if isinstance(task.get("turn"), dict) else {},
        }
    return None


def _node_run_lineage(
    store: WorkflowLedgerStore | None,
    action: PendingAction,
) -> tuple[tuple[str, ...], dict[str, str]]:
    lineage = [action.node_run_id]
    attempt_statuses: dict[str, str] = {}
    if store is None:
        return tuple(lineage), attempt_statuses

    def load(repository):
        current = repository.get_attempt(action.node_run_id)
        if current is None or not current.retry_of_node_run_id:
            return []
        parent_id = str(current.retry_of_node_run_id).strip()
        if not parent_id or parent_id == action.node_run_id:
            return []
        parent = repository.get_attempt(parent_id)
        if parent is None:
            return []
        attempt_statuses[parent_id] = str(getattr(parent, "status", "") or "").strip().lower()
        if parent.run_id != action.run_id or parent.node_id != action.node_id:
            raise RuntimeError("retry lineage identity mismatch")
        return [parent_id]

    lineage.extend(store.read(load))
    return tuple(lineage), attempt_statuses


def _assert_task_identity(
    task: dict[str, Any],
    *,
    team_id: str,
    source_run_id: str,
    stage_id: str,
    agent_id: str,
    agent_role: str,
) -> None:
    expected = {
        "teamId": team_id,
        "runId": source_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
    }
    mismatches = [
        key
        for key, value in expected.items()
        if str(task.get(key) or "").strip() != str(value or "").strip()
    ]
    if mismatches:
        raise RuntimeError(
            "stage task identity mismatch: " + ", ".join(sorted(mismatches))
        )


def _has_turn_anchor(task: dict[str, Any]) -> bool:
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    session_id = str(task.get("sessionId") or turn.get("sessionId") or "").strip()
    turn_id = str(turn.get("turnId") or task.get("startedTurnId") or "").strip()
    return bool(session_id and turn_id)
