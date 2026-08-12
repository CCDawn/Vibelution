"""Build CommandOffer tuples from NodeReadiness (single executability authority).

Offers are signed for a specific runVersion. Frontend must echo idempotencyKey
and payload unchanged; availability is never re-derived client-side.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.models import ActorKind, WorkflowDefinition

from .readiness import NodeReadinessService
from .readiness.common import DomainReadinessContext


def build_command_offers(
    *,
    readiness_service: NodeReadinessService,
    context: DomainReadinessContext,
    team_id: str,
    run_id: str,
    run_version: int,
    definition: WorkflowDefinition,
    pending_human_tasks: Sequence[Any] = (),
    evaluated_at_ms: int | None = None,
) -> list[CommandOffer]:
    offers: list[CommandOffer] = []
    pending_by_node: dict[str, list[Any]] = {}
    for task in pending_human_tasks:
        node_id = _task_node_id(task)
        if node_id:
            pending_by_node.setdefault(node_id, []).append(task)

    for node in definition.nodes:
        node_id = node.nodeId
        readiness = readiness_service.evaluate(
            team_id=team_id,
            run_id=run_id,
            node_id=node_id,
            context=context,
            use_cache=True,
            evaluated_at_ms=evaluated_at_ms,
        )
        blocker_ids = tuple(blocker.code for blocker in readiness.blockers)
        reason_code = blocker_ids[0] if blocker_ids else (
            "ready" if readiness.ready else "not_ready"
        )

        if node.actorKind == ActorKind.HUMAN:
            tasks = pending_by_node.get(node_id) or []
            if tasks:
                task = tasks[0]
                task_id = _task_field(task, "task_id", "taskId")
                available = True
                offers.append(
                    CommandOffer(
                        command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                        node_id=node_id,
                        available=available,
                        label=f"处理 {node.label}",
                        reason_code="human_task_pending",
                        blocker_ids=(),
                        idempotency_key=(
                            f"offer:{run_id}:{node_id}:resolve_human_task:"
                            f"{task_id}:v{run_version}"
                        ),
                        expected_run_version=run_version,
                        payload={"taskId": task_id},
                    )
                )
            else:
                offers.append(
                    CommandOffer(
                        command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                        node_id=node_id,
                        available=False,
                        label=f"处理 {node.label}",
                        reason_code="no_pending_human_task",
                        blocker_ids=("no_pending_human_task",),
                        idempotency_key=(
                            f"offer:{run_id}:{node_id}:resolve_human_task:v{run_version}"
                        ),
                        expected_run_version=run_version,
                        payload={},
                    )
                )
            continue

        offers.append(
            CommandOffer(
                command=WorkflowCommandKind.START_NODE,
                node_id=node_id,
                available=bool(readiness.ready),
                label=f"启动 {node.label}",
                reason_code=reason_code,
                blocker_ids=blocker_ids,
                idempotency_key=(
                    f"offer:{run_id}:{node_id}:start_node:v{run_version}"
                ),
                expected_run_version=run_version,
                payload={},
            )
        )

    offers.append(
        CommandOffer(
            command=WorkflowCommandKind.CANCEL_RUN,
            node_id=None,
            available=True,
            label="取消运行",
            reason_code="cancel_available",
            blocker_ids=(),
            idempotency_key=f"offer:{run_id}:cancel_run:v{run_version}",
            expected_run_version=run_version,
            payload={},
            destructive=True,
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
    # Human tasks store node via node_run_id; callers may pass enriched dicts.
    if isinstance(task, dict) and task.get("nodeId"):
        return str(task["nodeId"])
    return str(getattr(task, "node_id", "") or "")
