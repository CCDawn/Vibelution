"""Research workflow runtime service: definition, runs, commands, HITL, bindings.

HumanTasks, session bindings, handoffs, and idempotency keys are durable on disk.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.types import Command

from core.research.workflow.bindings import AgentBindingLayers, build_run_binding_snapshots
from core.research.workflow.challenge_cup_graph import compile_challenge_cup_graph
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.projection import build_canvas_projection

from .durable_index import DurableWorkflowIndex
from .handoff_builder import (
    artifact_kind_for_gate,
    build_handoff_record,
    edges_between_completed,
    successor_node,
)
from .store import WorkflowRunStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ResearchWorkflowError(Exception):
    def __init__(self, message: str, *, code: str = "workflow_error"):
        super().__init__(message)
        self.code = code


class ResearchWorkflowRuntimeService:
    def __init__(
        self,
        *,
        run_store: WorkflowRunStore | None = None,
        checkpoint_path: str | None = None,
        durable_index: DurableWorkflowIndex | None = None,
    ):
        self._store = run_store or WorkflowRunStore()
        self._checkpoint_path = checkpoint_path or os.environ.get(
            "VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH",
            str(
                Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
                / "Documents"
                / "Vibelution"
                / "data"
                / "research_workflows"
                / "checkpoints.sqlite"
            ),
        )
        index_root = Path(self._store.root) / "_index"
        self._index = durable_index or DurableWorkflowIndex(index_root)
        self._lock = threading.RLock()
        self._bindings = AgentBindingLayers()
        # Command-level idempotency is also durable via index keys with prefix.
        self._command_memory: dict[str, str] = {}  # key -> run_id snapshot path only for process; reloaded from index

    def get_definition(self, workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID) -> dict[str, Any]:
        if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
            raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
        definition = build_challenge_cup_workflow_definition()
        return {
            "workflowId": definition.workflowId,
            "workflowVersionId": f"wv-{definition.structureHash[:12]}",
            "definition": definition.to_dict(),
        }

    def list_runs(self, workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID) -> dict[str, Any]:
        runs = self._store.list_runs(workflow_id)
        return {"workflowId": workflow_id, "runs": runs}

    def _new_human_task(
        self,
        *,
        run_id: str,
        node_id: str,
        checkpoint_id: str = "",
        node_run_id: str = "",
    ) -> dict[str, Any]:
        return {
            "taskId": f"ht-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": node_run_id or f"nr-{node_id}",
            "checkpointId": checkpoint_id,
            "status": "pending",
            "prompt": f"Resolve gate at {node_id}",
            "createdAt": _utc_now(),
            "resolvedAt": "",
            "resolvedBy": "",
        }

    def _checkpoint_id_from_state(self, state: Any) -> str:
        try:
            cfg = state.config.get("configurable") or {}
            return str(cfg.get("checkpoint_id") or "")
        except Exception:
            return ""

    def _append_auto_handoffs(
        self,
        *,
        run_id: str,
        workflow_id: str,
        workflow_version_id: str,
        completed: list[str],
        artifacts: dict[str, Any],
        existing_edge_ids: set[str],
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for from_id, to_id in edges_between_completed(completed):
            edge_key = f"{from_id}->{to_id}"
            if edge_key in existing_edge_ids:
                continue
            record = build_handoff_record(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_version_id=workflow_version_id,
                from_node_id=from_id,
                to_node_id=to_id,
                status="accepted",
                artifacts=artifacts,
            )
            self._store.append_handoff(run_id, record)
            existing_edge_ids.add(edge_key)
            existing_edge_ids.add(str(record.get("edgeId") or ""))
            created.append(record)
        return created

    def create_run(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str = "",
        project_id: str = "",
        binding_layers: AgentBindingLayers | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key:
                existing_id = self._index.get_run_id(f"create:{idempotency_key}")
                if existing_id:
                    existing = self._store.get_run(existing_id)
                    if existing:
                        return existing

            meta = self.get_definition(workflow_id)
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            thread_id = f"thread-{run_id}"
            layers = binding_layers or self._bindings
            snapshots = build_run_binding_snapshots(
                run_id=run_id,
                workflow_version_id=meta["workflowVersionId"],
                layers=layers,
                captured_at=_utc_now(),
            )
            self._store.create_run(
                {
                    "runId": run_id,
                    "workflowId": workflow_id,
                    "workflowVersionId": meta["workflowVersionId"],
                    "structureHash": meta["definition"]["structureHash"],
                    "teamId": team_id,
                    "projectId": project_id,
                    "threadId": thread_id,
                    "status": "queued",
                    "runtimeCurrentNodeIds": [],
                    "bindingSnapshots": [
                        {
                            "snapshotId": s.snapshotId,
                            "nodeId": s.nodeId,
                            "agentId": s.agentId,
                            "roleKey": s.roleKey,
                            "actorKind": s.actorKind.value,
                            "resolvedFrom": s.resolvedFrom,
                            "capturedAt": s.capturedAt,
                        }
                        for s in snapshots
                    ],
                    "events": [],
                    "humanTasks": [],
                    "handoffs": [],
                    "sessionBindings": {},
                    "createIdempotencyKey": idempotency_key,
                }
            )
            if idempotency_key:
                self._index.put_run_id(f"create:{idempotency_key}", run_id)

            current_node_ids: list[str] = []
            lg_snapshot: dict[str, Any] = {}
            checkpoint_id = ""
            with open_sqlite_checkpointer(self._checkpoint_path) as checkpointer:
                graph = compile_challenge_cup_graph(checkpointer)
                cfg = {"configurable": {"thread_id": thread_id}}
                graph.invoke({}, cfg)
                state = graph.get_state(cfg)
                checkpoint_id = self._checkpoint_id_from_state(state)
                current_node_ids = [str(n) for n in (state.next or [])]
                if not current_node_ids and state.values.get("current_node_id"):
                    current_node_ids = [str(state.values.get("current_node_id"))]
                completed = list(state.values.get("completed_node_ids") or [])
                artifacts = dict(state.values.get("artifacts") or {})
                lg_snapshot = {
                    "engine": "challenge_cup_graph",
                    "completedNodeIds": completed,
                    "knowledgePackageAccepted": bool(state.values.get("knowledge_package_accepted")),
                    "frozenProtocolAccepted": bool(state.values.get("frozen_protocol_accepted")),
                    "smokeAccepted": bool(state.values.get("smoke_accepted")),
                    "artifacts": artifacts,
                    "checkpointId": checkpoint_id,
                }

            # Auto handoffs for completed agent pipeline before first gate.
            self._append_auto_handoffs(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_version_id=meta["workflowVersionId"],
                completed=completed,
                artifacts=artifacts,
                existing_edge_ids=set(),
            )

            status = "waiting_human" if current_node_ids else "running"
            gate_node = current_node_ids[0] if current_node_ids else ""
            human_tasks: list[dict[str, Any]] = []
            if gate_node:
                human_task = self._new_human_task(
                    run_id=run_id,
                    node_id=gate_node,
                    checkpoint_id=checkpoint_id,
                )
                human_tasks = [human_task]

            record = self._store.update_run(
                run_id,
                {
                    "status": status,
                    "runtimeCurrentNodeIds": current_node_ids,
                    "humanTasks": human_tasks,
                    "langGraph": lg_snapshot,
                },
            )
            if gate_node:
                self._store.append_event(
                    run_id,
                    {
                        "workflowId": workflow_id,
                        "workflowVersionId": meta["workflowVersionId"],
                        "runId": run_id,
                        "threadId": thread_id,
                        "nodeId": gate_node,
                        "type": "node.waiting_human",
                        "summary": {"taskId": human_tasks[0]["taskId"]},
                    },
                )
            return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = self._store.get_run(run_id)
        if record is None:
            raise ResearchWorkflowError(f"Unknown runId: {run_id}", code="unknown_run")
        return record

    def get_canvas_projection(self, run_id: str | None = None) -> dict[str, Any]:
        if not run_id:
            return build_canvas_projection()
        record = self.get_run(run_id)
        from core.research.workflow.models import WorkflowRunStatus

        status_raw = str(record.get("status") or "")
        try:
            status = WorkflowRunStatus(status_raw)
        except ValueError:
            status = None
        pending = [
            t
            for t in (record.get("humanTasks") or [])
            if str(t.get("status") or "") == "pending"
        ]
        return build_canvas_projection(
            run_id=run_id,
            run_status=status,
            runtime_current_node_ids=list(record.get("runtimeCurrentNodeIds") or []),
            pending_human_tasks=pending,
        )

    def get_node_detail(self, run_id: str, node_id: str) -> dict[str, Any]:
        record = self.get_run(run_id)
        definition = build_challenge_cup_workflow_definition()
        node = next((n for n in definition.nodes if n.nodeId == node_id), None)
        if node is None:
            raise ResearchWorkflowError(f"Unknown nodeId: {node_id}", code="unknown_node")
        snapshots = {s["nodeId"]: s for s in record.get("bindingSnapshots") or []}
        snap = snapshots.get(node_id) or {}
        session_binding = self._store.get_session_binding(run_id, node_id)
        degraded = False
        chat_href = None
        if node.actorKind is ActorKind.AGENT:
            if not session_binding or not session_binding.get("taskId") or not session_binding.get("turnId"):
                degraded = True
            elif session_binding.get("sessionId"):
                chat_href = (
                    f"/chat?session={session_binding['sessionId']}"
                    f"&focusTask={session_binding['taskId']}"
                    f"&focusTurn={session_binding['turnId']}"
                    f"&returnTo=/teams?researchView=workflow&runId={run_id}&node={node_id}"
                    f"&returnLabel=workflow"
                )
        return {
            "runId": run_id,
            "nodeId": node_id,
            "actorKind": node.actorKind.value,
            "primaryRoleKey": node.primaryRoleKey,
            "bindingSnapshot": snap,
            "sessionBinding": session_binding,
            "chatDeepLink": chat_href,
            "sessionAnchorDegraded": degraded,
            "runtimeCurrent": node_id in (record.get("runtimeCurrentNodeIds") or []),
            "status": record.get("status"),
        }

    def resolve_human_task(
        self,
        run_id: str,
        task_id: str,
        *,
        accept: bool,
        resolved_by: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            record = self.get_run(run_id)
            task = self._store.find_human_task(run_id, task_id)
            if task is None or task.get("runId") != run_id:
                raise ResearchWorkflowError(f"Unknown human task: {task_id}", code="unknown_human_task")
            if task.get("status") != "pending":
                raise ResearchWorkflowError("Human task already resolved", code="human_task_resolved")

            thread_id = str(record.get("threadId") or "")
            gate_node = str(task.get("nodeId") or "")
            workflow_id = str(record.get("workflowId") or CHALLENGE_CUP_WORKFLOW_ID)
            workflow_version_id = str(record.get("workflowVersionId") or "")
            previous_completed = list((record.get("langGraph") or {}).get("completedNodeIds") or [])
            existing_handoffs = list(record.get("handoffs") or [])
            existing_edge_ids = {
                str(h.get("edgeId") or f"{h.get('fromNodeId')}->{h.get('toNodeId')}")
                for h in existing_handoffs
            }

            runtime_nodes: list[str] = []
            lg_snapshot = dict(record.get("langGraph") or {})
            checkpoint_id = ""
            with open_sqlite_checkpointer(self._checkpoint_path) as checkpointer:
                graph = compile_challenge_cup_graph(checkpointer)
                cfg = {"configurable": {"thread_id": thread_id}}
                graph.invoke(Command(resume={"accept": accept}), cfg)
                state = graph.get_state(cfg)
                checkpoint_id = self._checkpoint_id_from_state(state)
                runtime_nodes = [str(n) for n in (state.next or [])]
                completed = list(state.values.get("completed_node_ids") or [])
                artifacts = dict(state.values.get("artifacts") or {})
                lg_snapshot = {
                    **lg_snapshot,
                    "engine": "challenge_cup_graph",
                    "completedNodeIds": completed,
                    "knowledgePackageAccepted": bool(state.values.get("knowledge_package_accepted")),
                    "frozenProtocolAccepted": bool(state.values.get("frozen_protocol_accepted")),
                    "smokeAccepted": bool(state.values.get("smoke_accepted")),
                    "artifacts": artifacts,
                    "checkpointId": checkpoint_id,
                }

            # Resolve current task
            resolved_status = "resolved_accept" if accept else "resolved_reject"
            resolved_task = {
                **task,
                "status": resolved_status,
                "resolvedBy": resolved_by or "operator",
                "resolvedAt": _utc_now(),
                "checkpointId": checkpoint_id or task.get("checkpointId") or "",
            }
            self._store.upsert_human_task(run_id, resolved_task)

            # Handoff for this gate (adjacent definition edge)
            handoff_status = "accepted" if accept else "rejected"
            handoff = build_handoff_record(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_version_id=workflow_version_id,
                from_node_id=gate_node,
                to_node_id=successor_node(gate_node),
                status=handoff_status,
                artifacts=lg_snapshot.get("artifacts") if isinstance(lg_snapshot.get("artifacts"), dict) else {},
                accepted_by=resolved_by or "operator",
                rejection_reason="" if accept else "rejected_by_human",
                human_task_id=task_id,
            )
            self._store.append_handoff(run_id, handoff)
            existing_edge_ids.add(str(handoff.get("edgeId") or ""))

            # Auto handoffs for newly completed agent nodes after this resume
            if accept:
                self._append_auto_handoffs(
                    run_id=run_id,
                    workflow_id=workflow_id,
                    workflow_version_id=workflow_version_id,
                    completed=completed,
                    artifacts=artifacts,
                    existing_edge_ids=existing_edge_ids,
                )

            # Create next pending HumanTask for new interrupt
            if accept and runtime_nodes:
                next_gate = runtime_nodes[0]
                # Avoid duplicate pending for same node
                tasks_now = list((self.get_run(run_id).get("humanTasks") or []))
                has_pending_next = any(
                    str(t.get("nodeId")) == next_gate and str(t.get("status")) == "pending"
                    for t in tasks_now
                )
                if not has_pending_next:
                    next_task = self._new_human_task(
                        run_id=run_id,
                        node_id=next_gate,
                        checkpoint_id=checkpoint_id,
                    )
                    self._store.upsert_human_task(run_id, next_task)
                    self._store.append_event(
                        run_id,
                        {
                            "workflowId": workflow_id,
                            "runId": run_id,
                            "threadId": thread_id,
                            "nodeId": next_gate,
                            "type": "node.waiting_human",
                            "summary": {"taskId": next_task["taskId"]},
                        },
                    )

            if not accept:
                status = "blocked"
            elif not runtime_nodes:
                status = "succeeded"
            else:
                status = "waiting_human"

            self._store.update_run(
                run_id,
                {
                    "status": status,
                    "runtimeCurrentNodeIds": runtime_nodes if accept else [gate_node],
                    "langGraph": lg_snapshot,
                },
            )
            self._store.append_event(
                run_id,
                {
                    "workflowId": workflow_id,
                    "runId": run_id,
                    "threadId": thread_id,
                    "nodeId": gate_node,
                    "type": "human_task.resolved",
                    "summary": {
                        "taskId": task_id,
                        "accept": accept,
                        "handoffId": handoff["handoffId"],
                        "toNodeId": handoff.get("toNodeId"),
                    },
                },
            )
            return self.get_run(run_id)

    def apply_command(
        self,
        run_id: str,
        command: str,
        *,
        idempotency_key: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        durable_key = f"cmd:{run_id}:{command}:{idempotency_key}" if idempotency_key else ""
        if durable_key:
            existing_id = self._index.get_run_id(durable_key)
            if existing_id:
                # Stored value is a marker; return current run after prior command.
                return self.get_run(run_id)

        payload = payload or {}
        if command == "cancel":
            record = self._store.update_run(run_id, {"status": "cancelled", "runtimeCurrentNodeIds": []})
        elif command == "retry_node":
            record = self.get_run(run_id)
            attempts = int(record.get("retryCount") or 0) + 1
            record = self._store.update_run(run_id, {"retryCount": attempts, "status": "queued"})
        elif command == "rebind_node":
            node_id = str(payload.get("nodeId") or "")
            agent_id = str(payload.get("agentId") or "").strip()
            if not node_id or not agent_id:
                raise ResearchWorkflowError("rebind_node requires nodeId and agentId", code="invalid_rebind")
            record = self.get_run(run_id)
            snaps = list(record.get("bindingSnapshots") or [])
            history = list(record.get("bindingHistory") or [])
            attempt = int(record.get("rebindAttempt") or 0) + 1
            for snap in snaps:
                if snap.get("nodeId") == node_id:
                    history.append({**snap, "supersededAt": _utc_now()})
            new_snap = {
                "snapshotId": f"snap:{run_id}:{node_id}:rebind-{uuid.uuid4().hex[:6]}",
                "nodeId": node_id,
                "agentId": agent_id,
                "roleKey": next((s.get("roleKey") for s in snaps if s.get("nodeId") == node_id), ""),
                "actorKind": "agent",
                "resolvedFrom": "rebind",
                "capturedAt": _utc_now(),
                "nodeAttempt": attempt,
            }
            snaps = [s for s in snaps if s.get("nodeId") != node_id] + [new_snap]
            record = self._store.update_run(
                run_id,
                {
                    "bindingSnapshots": snaps,
                    "bindingHistory": history,
                    "rebindAttempt": attempt,
                },
            )
            self._store.append_event(
                run_id,
                {
                    "runId": run_id,
                    "nodeId": node_id,
                    "type": "binding.rebind_node",
                    "summary": {"agentId": agent_id, "nodeAttempt": attempt},
                },
            )
            record = self.get_run(run_id)
        else:
            raise ResearchWorkflowError(f"Unknown command: {command}", code="unknown_command")
        if durable_key:
            self._index.put_run_id(durable_key, run_id)
        return record

    def put_session_binding(self, run_id: str, node_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        self.get_run(run_id)
        required = ("sessionId", "taskId", "turnId", "agentId")
        missing = [k for k in required if not str(binding.get(k) or "").strip()]
        record = {
            "bindingId": str(binding.get("bindingId") or f"nsb-{uuid.uuid4().hex[:10]}"),
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": str(binding.get("nodeRunId") or f"nr-{node_id}"),
            "nodeAttempt": int(binding.get("nodeAttempt") or 1),
            "agentId": str(binding.get("agentId") or ""),
            "roleKey": str(binding.get("roleKey") or ""),
            "sessionId": str(binding.get("sessionId") or ""),
            "sessionAttempt": int(binding.get("sessionAttempt") or 1),
            "taskId": str(binding.get("taskId") or ""),
            "turnId": str(binding.get("turnId") or ""),
            "checkpointId": str(binding.get("checkpointId") or ""),
            "status": "degraded" if missing else "bound",
            "boundAt": _utc_now(),
            "supersedesBindingId": str(binding.get("supersedesBindingId") or ""),
            "missingFields": missing,
        }
        self._store.put_session_binding(run_id, node_id, record)
        return record

    def list_events(self, run_id: str, *, after_sequence: int = 0) -> dict[str, Any]:
        record = self.get_run(run_id)
        events = [e for e in (record.get("events") or []) if int(e.get("sequence") or 0) > after_sequence]
        return {
            "runId": run_id,
            "events": events,
            "snapshot": {
                "status": record.get("status"),
                "runtimeCurrentNodeIds": record.get("runtimeCurrentNodeIds") or [],
                "bindingSnapshots": record.get("bindingSnapshots") or [],
                "handoffs": record.get("handoffs") or [],
                "humanTasks": record.get("humanTasks") or [],
                "langGraph": record.get("langGraph") or {},
            },
        }

    def set_binding_layers(self, layers: AgentBindingLayers) -> None:
        self._bindings = layers


_SERVICE: ResearchWorkflowRuntimeService | None = None
_SERVICE_LOCK = threading.Lock()


def get_research_workflow_runtime_service() -> ResearchWorkflowRuntimeService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = ResearchWorkflowRuntimeService()
        return _SERVICE


def reset_research_workflow_runtime_service_for_tests(
    *,
    run_store: WorkflowRunStore | None = None,
    checkpoint_path: str | None = None,
    durable_index: DurableWorkflowIndex | None = None,
) -> ResearchWorkflowRuntimeService:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = ResearchWorkflowRuntimeService(
            run_store=run_store,
            checkpoint_path=checkpoint_path,
            durable_index=durable_index,
        )
        return _SERVICE
