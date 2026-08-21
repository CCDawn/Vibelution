"""resolve_human_task CommandOffers — one executable Offer per decision."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition


_DECISIONS = (
    ("accept", "接受交接", True),
    ("reject", "拒绝交接", True),
    ("revise", "要求修订", False),
)


def build_resolve_human_offers(
    *,
    run: RunRecord,
    definition: WorkflowDefinition,
    pending_human_tasks: Sequence[Any] = (),
    revise_checkpoint_id: str | None = None,
) -> list[CommandOffer]:
    offers: list[CommandOffer] = []
    pending_by_node: dict[str, list[Any]] = {}
    for task in pending_human_tasks:
        node_id = _task_node_id(task)
        if node_id:
            pending_by_node.setdefault(node_id, []).append(task)

    human_nodes = [node for node in definition.nodes if node.actorKind == ActorKind.HUMAN]
    for node in human_nodes:
        tasks = pending_by_node.get(node.nodeId) or []
        if not tasks:
            offers.append(
                CommandOffer(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=node.nodeId,
                    available=False,
                    label=f"处理 {node.label}",
                    reason_code="no_pending_human_task",
                    blocker_ids=("no_pending_human_task",),
                    idempotency_key=(
                        f"offer:{run.run_id}:{node.nodeId}:resolve_human_task:v{run.run_version}"
                    ),
                    expected_run_version=run.run_version,
                    payload={},
                )
            )
            continue

        task = tasks[0]
        task_id = _task_field(task, "task_id", "taskId")
        # Root runs never carry forked_from_checkpoint_id; the caller resolves
        # the thread's latest durable checkpoint so revise stays available.
        checkpoint_id = str(
            run.forked_from_checkpoint_id or revise_checkpoint_id or ""
        ).strip()
        for decision, label, always_available in _DECISIONS:
            if decision == "revise":
                available = bool(checkpoint_id)
                blocker_ids = () if available else ("revise_checkpoint_unavailable",)
                reason_code = "ready" if available else "revise_checkpoint_unavailable"
                payload: dict[str, Any] = {
                    "taskId": task_id,
                    "decision": "revise",
                    "reason": "operator requested revision",
                    "fromNodeId": node.nodeId,
                    "checkpointId": checkpoint_id,
                }
            else:
                available = always_available
                blocker_ids = ()
                reason_code = "human_task_pending"
                payload = {
                    "taskId": task_id,
                    "decision": decision,
                    "reason": "",
                }
            offers.append(
                CommandOffer(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=node.nodeId,
                    available=available,
                    label=label,
                    reason_code=reason_code,
                    blocker_ids=blocker_ids,
                    idempotency_key=(
                        f"offer:{run.run_id}:{node.nodeId}:resolve_human_task:"
                        f"{task_id}:{decision}:v{run.run_version}"
                    ),
                    expected_run_version=run.run_version,
                    payload=payload,
                )
            )
    return offers


def _task_field(task: Any, *names: str) -> str:
    if isinstance(task, dict):
        for name in names:
            value = task.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
    for name in names:
        value = getattr(task, name, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _task_node_id(task: Any) -> str:
    if isinstance(task, dict) and task.get("nodeId"):
        return str(task["nodeId"])
    return str(getattr(task, "node_id", "") or "")
