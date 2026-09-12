"""Durable parent wait cursor for the operator knowledge child."""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.contracts import PendingAction

PENDING_CODE = "operator_knowledge_child_pending"
_PARENT_WORKFLOW = "operator-optimization"
_PARENT_NODE = "optimization_knowledge"


class KnowledgeChildPending(RuntimeError):
    def __init__(self, invocation_id: str, child_run_id: str) -> None:
        self.invocation_id = str(invocation_id or "")
        self.child_run_id = str(child_run_id or "")
        super().__init__(
            f"knowledge child {self.child_run_id} is pending for invocation {self.invocation_id}"
        )


def _terminal_ready(invocation: Any) -> bool:
    status = str(getattr(invocation, "status", "") or "")
    return status in {"failed", "cancelled"} or (
        status == "completed"
        and str(getattr(invocation, "handoff_state", "") or "") == "accepted"
    )


def _delivered_or_failed(uow, invocation):
    if not _terminal_ready(invocation):
        return False
    if invocation.status in {"failed", "cancelled"}:
        return True
    from ..research_runtime.knowledge_sideflow_service import knowledge_result_event_id

    event = uow.repository.get_event_by_id(
        knowledge_result_event_id(
            invocation.invocation_id, invocation.package_content_hash
        )
    )
    return event is not None and event.run_id == invocation.parent_run_id


def _valid_identity(
    uow: Any, action: PendingAction, invocation_id: str, child_run_id: str
) -> Any | None:
    if action.node_id != _PARENT_NODE:
        return None
    parent = uow.repository.get_run(action.run_id)
    invocation = uow.repository.get_knowledge_invocation(invocation_id)
    if parent is None or invocation is None:
        return None
    child = uow.repository.get_run(child_run_id)
    latest = uow.repository.latest_attempt(action.run_id, action.node_id)
    if (
        str(parent.workflow_id) != _PARENT_WORKFLOW
        or str(invocation.parent_run_id) != action.run_id
        or str(invocation.parent_node_id) != _PARENT_NODE
        or str(invocation.parent_node_run_id) != action.node_run_id
        or int(invocation.parent_attempt or 0) != int(action.attempt or 0)
        or str(invocation.knowledge_child_run_id or "") != child_run_id
        or child is None
        or child.workflow_id != "challenge-cup-knowledge-sideflow"
        or str(child.parent_run_id or "") != action.run_id
        or parent.status not in {"running", "blocked"}
        or latest is None
        or latest.node_run_id != action.node_run_id
        or str(child.run_id) != child_run_id
    ):
        return None
    return invocation


def defer_knowledge_child(
    store: Any,
    *,
    outbox: Any,
    action: PendingAction,
    error: KnowledgeChildPending,
    owner: str,
    now_ms: int,
) -> None:
    """Park the leased action and parent attempt in one fenced transaction."""
    from ..research_runtime.block_projection import apply_node_run_block

    def mutate(uow: Any) -> None:
        invocation = _valid_identity(
            uow, action, error.invocation_id, error.child_run_id
        )
        if invocation is None:
            return
        row = uow.repository.get_outbox(outbox.action_id)
        if row is None or row.status != "leased" or row.lease_owner != owner:
            return
        problem = {
            "code": PENDING_CODE,
            "detail": str(error),
            "action": {
                "actionId": action.action_id,
                "nodeRunId": action.node_run_id,
                "inputSnapshotHash": action.input_snapshot_hash,
            },
            "invocation": {"invocationId": error.invocation_id},
            "child": {"childRunId": error.child_run_id},
        }
        encoded = json.dumps(problem, ensure_ascii=False, sort_keys=True)
        attempt = uow.repository.get_attempt(action.node_run_id)
        if attempt is None or attempt.status not in {
            "starting",
            "dispatching",
            "running",
        }:
            return
        if not uow.repository.fail_outbox(outbox.action_id, owner, now_ms, encoded):
            return
        if attempt.status != "running":
            uow.repository.update_attempt_status(
                action.node_run_id, "running", now_ms, problem_json=None
            )
        apply_node_run_block(
            uow,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            node_id=action.node_id,
            problem=problem,
            now_ms=now_ms,
            actor_id=owner,
            correlation_id=action.action_id,
            update_attempt=False,
        )
        # The child may have settled between execute() raising and this write.
        if _delivered_or_failed(uow, invocation):
            _wake_in_uow(uow, error.invocation_id, now_ms)

    store.submit(mutate, force_flush=True).result(timeout=30)


def _wake_in_uow(uow: Any, invocation_id: str, now_ms: int) -> bool:
    invocation = uow.repository.get_knowledge_invocation(invocation_id)
    if invocation is None or not _delivered_or_failed(uow, invocation):
        return False
    run = uow.repository.get_run(invocation.parent_run_id)
    attempt = uow.repository.get_attempt(invocation.parent_node_run_id)
    if run is None or attempt is None:
        return False
    latest = uow.repository.latest_attempt(run.run_id, _PARENT_NODE)
    child = uow.repository.get_run(invocation.knowledge_child_run_id)
    if (
        str(run.workflow_id) != _PARENT_WORKFLOW
        or child is None
        or child.workflow_id != "challenge-cup-knowledge-sideflow"
        or child.parent_run_id != run.run_id
        or invocation.parent_node_id != _PARENT_NODE
        or attempt.attempt != invocation.parent_attempt
        or run.status != "blocked"
        or run.active_node_id != _PARENT_NODE
        or latest is None
        or latest.node_run_id != attempt.node_run_id
        or attempt.status != "running"
    ):
        return False
    run_problem = json.loads(run.blocked_problem_json or "{}")
    if run_problem.get("code") != PENDING_CODE:
        return False
    rows = uow.repository.execute(
        "SELECT action_id, last_problem_json FROM outbox_actions "
        "WHERE run_id = ? AND node_run_id = ? AND action_kind = 'adapter_dispatch' "
        "AND status = 'failed'",
        (run.run_id, attempt.node_run_id),
    ).fetchall()
    woke = False
    for action_id, raw in rows:
        problem = json.loads(raw or "{}")
        if problem.get("code") != PENDING_CODE:
            continue
        cursor = problem.get("invocation") or {}
        action_payload = problem.get("action") or {}
        child_cursor = problem.get("child") or {}
        if (
            cursor.get("invocationId") != invocation_id
            or action_payload.get("actionId") != action_id
            or action_payload.get("nodeRunId") != attempt.node_run_id
            or child_cursor.get("childRunId") != invocation.knowledge_child_run_id
        ):
            continue
        try:
            original = PendingAction.from_dict(
                json.loads(uow.repository.get_outbox(action_id).payload_json)
            )
        except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
            continue
        if (
            original.action_id != action_payload.get("actionId")
            or original.node_run_id != action_payload.get("nodeRunId")
            or original.input_snapshot_hash != action_payload.get("inputSnapshotHash")
        ):
            continue
        uow.repository.execute(
            "UPDATE outbox_actions SET status='pending', available_at_ms=?, "
            "lease_owner=NULL, lease_expires_at_ms=NULL, attempt_count=0, "
            "updated_at_ms=? WHERE action_id=? AND status='failed'",
            (now_ms, now_ms, action_id),
        )
        woke = True
    if woke:
        uow.repository.update_run_status(
            run.run_id, run.team_id, "running", now_ms, blocked_problem_json=None
        )
    return woke


def wake_knowledge_child(uow: Any, invocation_id: str, now_ms: int) -> bool:
    """Wake only the still-current parent cursor; safe under replay."""
    return _wake_in_uow(uow, invocation_id, now_ms)
