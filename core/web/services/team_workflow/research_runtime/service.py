"""Research workflow runtime service: definition, runs, commands, HITL, bindings."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.workflow.bindings import AgentBindingLayers, build_run_binding_snapshots
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.projection import build_canvas_projection
from core.research.workflow.runtime import VerticalSliceRuntime

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
        self._lock = threading.RLock()
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._bindings = AgentBindingLayers()
        self._session_bindings: dict[str, dict[str, Any]] = {}  # key runId:nodeId
        self._human_tasks: dict[str, dict[str, Any]] = {}

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
            if idempotency_key and idempotency_key in self._idempotency:
                return self._idempotency[idempotency_key]

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
            record = self._store.create_run(
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
                }
            )
            # Kick vertical-slice engine (HITL gate) for runtime truth.
            with VerticalSliceRuntime(checkpoint_path=self._checkpoint_path) as rt:
                lg_result = rt.start(thread_id, idempotency_key=run_id)
            status = "waiting_human" if lg_result.get("step") == "start" else "running"
            task_id = f"ht-{uuid.uuid4().hex[:10]}"
            human_task = {
                "taskId": task_id,
                "runId": run_id,
                "nodeId": "knowledge_handoff",
                "status": "pending",
                "prompt": "Accept upstream handoff?",
                "checkpointId": "",
                "createdAt": _utc_now(),
            }
            self._human_tasks[task_id] = human_task
            record = self._store.update_run(
                run_id,
                {
                    "status": status,
                    "runtimeCurrentNodeIds": ["knowledge_handoff"],
                    "humanTasks": [human_task],
                    "langGraph": {
                        "lastStep": lg_result.get("step"),
                        "artifact": lg_result.get("upstream_artifact"),
                        "inputSnapshotHash": lg_result.get("input_snapshot_hash"),
                    },
                },
            )
            self._store.append_event(
                run_id,
                {
                    "workflowId": workflow_id,
                    "workflowVersionId": meta["workflowVersionId"],
                    "runId": run_id,
                    "threadId": thread_id,
                    "nodeId": "knowledge_handoff",
                    "type": "node.waiting_human",
                    "summary": {"taskId": task_id},
                },
            )
            record = self._store.get_run(run_id) or record
            if idempotency_key:
                self._idempotency[idempotency_key] = record
            return record

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
        return build_canvas_projection(
            run_id=run_id,
            run_status=status,
            runtime_current_node_ids=list(record.get("runtimeCurrentNodeIds") or []),
            pending_human_tasks=list(record.get("humanTasks") or []),
        )

    def get_node_detail(self, run_id: str, node_id: str) -> dict[str, Any]:
        record = self.get_run(run_id)
        definition = build_challenge_cup_workflow_definition()
        node = next((n for n in definition.nodes if n.nodeId == node_id), None)
        if node is None:
            raise ResearchWorkflowError(f"Unknown nodeId: {node_id}", code="unknown_node")
        snapshots = {s["nodeId"]: s for s in record.get("bindingSnapshots") or []}
        snap = snapshots.get(node_id) or {}
        session_key = f"{run_id}:{node_id}"
        session_binding = self._session_bindings.get(session_key)
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

    def resolve_human_task(self, run_id: str, task_id: str, *, accept: bool, resolved_by: str = "") -> dict[str, Any]:
        with self._lock:
            record = self.get_run(run_id)
            task = self._human_tasks.get(task_id)
            if task is None or task.get("runId") != run_id:
                raise ResearchWorkflowError(f"Unknown human task: {task_id}", code="unknown_human_task")
            if task.get("status") != "pending":
                raise ResearchWorkflowError("Human task already resolved", code="human_task_resolved")
            thread_id = str(record.get("threadId") or "")
            with VerticalSliceRuntime(checkpoint_path=self._checkpoint_path) as rt:
                lg_result = rt.resume(thread_id, {"accept": accept})
            task = {
                **task,
                "status": "resolved_accept" if accept else "resolved_reject",
                "resolvedBy": resolved_by or "operator",
                "resolvedAt": _utc_now(),
            }
            self._human_tasks[task_id] = task
            handoff = {
                "handoffId": f"ho-{uuid.uuid4().hex[:10]}",
                "fromNodeId": "knowledge_handoff",
                "toNodeId": "hypothesis_design",
                "status": "accepted" if accept else "rejected",
                "inputSnapshotHash": (record.get("langGraph") or {}).get("inputSnapshotHash") or "",
                "outputArtifactRefs": [
                    {
                        "artifactId": (record.get("langGraph") or {}).get("artifact") or "",
                        "kind": "knowledge_package",
                        "version": "1",
                        "contentHash": (record.get("langGraph") or {}).get("inputSnapshotHash") or "",
                    }
                ]
                if accept
                else [],
            }
            status = "succeeded" if accept and lg_result.get("step") == "done" else ("failed" if not accept else "running")
            runtime_nodes = [] if accept else ["knowledge_handoff"]
            if accept:
                runtime_nodes = []
            record = self._store.update_run(
                run_id,
                {
                    "status": status,
                    "runtimeCurrentNodeIds": runtime_nodes,
                    "humanTasks": [task],
                    "handoffs": [handoff],
                    "langGraph": {
                        **(record.get("langGraph") or {}),
                        "lastStep": lg_result.get("step"),
                        "handoffStatus": lg_result.get("handoff_status"),
                    },
                },
            )
            self._store.append_event(
                run_id,
                {
                    "workflowId": record.get("workflowId"),
                    "runId": run_id,
                    "threadId": thread_id,
                    "nodeId": "knowledge_handoff",
                    "type": "human_task.resolved",
                    "summary": {"taskId": task_id, "accept": accept},
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
        key = f"{run_id}:{command}:{idempotency_key}"
        if idempotency_key and key in self._idempotency:
            return self._idempotency[key]
        payload = payload or {}
        if command == "cancel":
            record = self._store.update_run(run_id, {"status": "cancelled", "runtimeCurrentNodeIds": []})
        elif command == "retry_node":
            # New attempt lineage marker only at service layer for now.
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
            replaced = False
            for idx, snap in enumerate(snaps):
                if snap.get("nodeId") == node_id:
                    snaps[idx] = {
                        **snap,
                        "agentId": agent_id,
                        "resolvedFrom": "rebind",
                        "capturedAt": _utc_now(),
                        "snapshotId": f"snap:{run_id}:{node_id}:rebind-{uuid.uuid4().hex[:6]}",
                    }
                    replaced = True
            if not replaced:
                snaps.append(
                    {
                        "snapshotId": f"snap:{run_id}:{node_id}:rebind",
                        "nodeId": node_id,
                        "agentId": agent_id,
                        "roleKey": "",
                        "actorKind": "agent",
                        "resolvedFrom": "rebind",
                        "capturedAt": _utc_now(),
                    }
                )
            record = self._store.update_run(run_id, {"bindingSnapshots": snaps})
            self._store.append_event(
                run_id,
                {
                    "runId": run_id,
                    "nodeId": node_id,
                    "type": "binding.rebind_node",
                    "summary": {"agentId": agent_id},
                },
            )
            record = self.get_run(run_id)
        else:
            raise ResearchWorkflowError(f"Unknown command: {command}", code="unknown_command")
        if idempotency_key:
            self._idempotency[key] = record
        return record

    def put_session_binding(self, run_id: str, node_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        """Persist NodeAgentSessionBinding fields (Task 7 fills chat integration)."""
        self.get_run(run_id)
        required = ("sessionId", "taskId", "turnId", "agentId")
        missing = [k for k in required if not str(binding.get(k) or "").strip()]
        record = {
            "bindingId": str(binding.get("bindingId") or f"nsb-{uuid.uuid4().hex[:10]}"),
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": str(binding.get("nodeRunId") or ""),
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
        self._session_bindings[f"{run_id}:{node_id}"] = record
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
) -> ResearchWorkflowRuntimeService:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = ResearchWorkflowRuntimeService(run_store=run_store, checkpoint_path=checkpoint_path)
        return _SERVICE
