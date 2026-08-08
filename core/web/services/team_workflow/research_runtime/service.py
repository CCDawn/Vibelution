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

from core.research.workflow.bindings import (
    AgentBindingLayers,
    build_run_binding_snapshots,
    resolve_effective_agent_id,
)
from core.research.workflow.challenge_cup_graph import compile_challenge_cup_graph
from core.research.workflow.checkpoint_store import open_sqlite_checkpointer
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.iteration_decisions import (
    DEFAULT_ITERATION_BUDGET,
    IterationDecisionError,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.projection import build_canvas_projection

from .binding_config import BindingConfigValidationError, WorkflowBindingConfigStore
from .durable_index import DurableWorkflowIndex
from .handoff_builder import (
    artifact_kind_for_gate,
    build_handoff_record,
    successor_node,
)
from .handoff_lineage import (
    build_auto_handoffs_for_completed,
    existing_active_edge_ids,
    handoff_edge_id,
)
from .iteration_transition import (
    apply_iteration_decision_side_effects,
    find_decision_by_idempotency,
)
from .node_command_adapter import (
    NodeCommandError,
    NodeCommandUnavailable,
    apply_node_command,
    node_command_capabilities,
)
from .session_binding_bridge import (
    SessionBindingBridge,
    SessionBindingError,
)
from .store import WorkflowRunStore
from .team_role_source import effective_binding_layers


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _node_attempt(record: dict[str, Any], node_id: str) -> int:
    attempts = record.get("nodeAttempts") or {}
    if isinstance(attempts, dict):
        return int(attempts.get(node_id) or 0)
    return 0


def _agent_display_name(agent_id: str) -> str:
    try:
        from core.web.services.agent_directory_service import get_agent_config

        agent = get_agent_config(agent_id)
        if isinstance(agent, dict):
            return str(agent.get("displayName") or agent.get("agentName") or agent_id)
    except Exception:
        pass
    return agent_id


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
        binding_config_store: WorkflowBindingConfigStore | None = None,
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
        # Per-(workflowId, teamId) controlled config; team roles are the
        # fallback default source resolved at run creation (never random).
        self._binding_config = binding_config_store or WorkflowBindingConfigStore(self._store.root)
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

    def list_runs(self, workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID, *, team_id: str = "") -> dict[str, Any]:
        runs = self._store.list_runs(workflow_id)
        if str(team_id or "").strip():
            runs = [r for r in runs if str(r.get("teamId") or "") == str(team_id).strip()]
        return {"workflowId": workflow_id, "runs": runs}

    def _effective_binding_layers(self, workflow_id: str, team_id: str) -> AgentBindingLayers:
        """Controlled config (per workflow+team) merged over team-role defaults."""
        config = self._binding_config.load(workflow_id, team_id)
        return effective_binding_layers(team_id, config)

    def get_effective_agent_bindings(
        self,
        workflow_id: str = CHALLENGE_CUP_WORKFLOW_ID,
        *,
        team_id: str = "",
    ) -> dict[str, Any]:
        """Current-configuration view per agent node (never touches run history)."""
        meta = self.get_definition(workflow_id)
        definition = build_challenge_cup_workflow_definition()
        layers = self._effective_binding_layers(workflow_id, team_id)
        bindings = []
        for node in definition.nodes:
            if node.actorKind is not ActorKind.AGENT:
                continue
            agent_id, resolved_from = resolve_effective_agent_id(node, layers)
            bindings.append(
                {
                    "nodeId": node.nodeId,
                    "roleKey": node.primaryRoleKey,
                    "agentId": agent_id,
                    "resolvedFrom": resolved_from,
                }
            )
        return {
            "workflowId": workflow_id,
            "workflowVersionId": meta["workflowVersionId"],
            "teamId": str(team_id or "").strip(),
            "bindings": bindings,
        }

    def put_agent_binding_config(
        self,
        workflow_id: str,
        payload: dict[str, Any],
        *,
        team_id: str = "",
    ) -> dict[str, Any]:
        """Controlled write of binding config layers (per workflow+team scope).

        Only the keys present in the payload are replaced; missing layers keep
        their persisted values. Validated against the workflow definition
        before persisting (unknown role/stage/node rejected).
        """
        if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
            raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
        current = self._binding_config.load(workflow_id, team_id)
        # Replace-whole-layer semantics: a layer present in the payload fully
        # replaces its persisted value (an empty dict clears it); absent
        # layers keep their persisted values.
        update = {
            "workflowDefaults": (
                {str(k): str(v) for k, v in (payload.get("workflowDefaults") or {}).items()}
                if "workflowDefaults" in payload
                else current.workflowDefaults
            ),
            "stageOverrides": (
                {
                    str(k): {str(rk): str(av) for rk, av in v.items()}
                    for k, v in (payload.get("stageOverrides") or {}).items()
                }
                if "stageOverrides" in payload
                else current.stageOverrides
            ),
            "nodeOverrides": (
                {str(k): str(v) for k, v in (payload.get("nodeOverrides") or {}).items()}
                if "nodeOverrides" in payload
                else current.nodeOverrides
            ),
        }
        try:
            self._binding_config.validate_payload(update)
        except BindingConfigValidationError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc
        saved = self._binding_config.save(
            workflow_id,
            team_id,
            AgentBindingLayers(
                workflowDefaults=update["workflowDefaults"],
                stageOverrides=update["stageOverrides"],
                nodeOverrides=update["nodeOverrides"],
            ),
        )
        return {
            "workflowId": workflow_id,
            "teamId": saved["teamId"],
            "workflowDefaults": saved["workflowDefaults"],
            "stageOverrides": saved["stageOverrides"],
            "nodeOverrides": saved["nodeOverrides"],
            "updatedAt": saved["updatedAt"],
        }

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
        """Append auto handoffs using definition edgeId identity (no human dupes)."""
        created = build_auto_handoffs_for_completed(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            completed=completed,
            artifacts=artifacts,
            existing_edge_ids=existing_edge_ids,
        )
        for record in created:
            self._store.append_handoff(run_id, record)
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
            # Binding resolution: explicit layers > non-empty service-level
            # config > team-role default mapping (per teamId, never random).
            service_config = self._bindings
            has_service_config = bool(
                service_config.workflowDefaults
                or service_config.stageOverrides
                or service_config.nodeOverrides
            )
            layers = (
                binding_layers
                or (service_config if has_service_config else None)
                or self._effective_binding_layers(workflow_id, team_id)
            )
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
                    "iterationDecisions": [],
                    "nodeAttempts": {},
                    "iterationBudgetMax": DEFAULT_ITERATION_BUDGET,
                    "officialCandidateRef": "",
                    "baselineCandidateRef": "",
                    "childRunIds": [],
                    "completionKind": "",
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
        node_attempts = dict(record.get("nodeAttempts") or {})
        node_runs: dict[str, dict[str, Any]] = {}
        for node_id, attempt in node_attempts.items():
            node_runs[str(node_id)] = {
                "nodeId": str(node_id),
                "status": "succeeded" if int(attempt or 0) > 0 else "pending",
                "attempt": int(attempt or 0),
                "nodeRunId": f"nr-{node_id}-a{int(attempt or 0)}",
            }
        return build_canvas_projection(
            run_id=run_id,
            run_status=status,
            runtime_current_node_ids=list(record.get("runtimeCurrentNodeIds") or []),
            node_runs=node_runs,
            pending_human_tasks=pending,
            parent_run_id=str(record.get("parentRunId") or "") or None,
            child_run_ids=list(record.get("childRunIds") or []),
            completion_kind=str(record.get("completionKind") or "") or None,
            official_candidate_ref=str(record.get("officialCandidateRef") or "") or None,
            blocked_reason=str(record.get("blockedReason") or (record.get("langGraph") or {}).get("blockedReason") or "")
            or None,
            iteration_budget_max=int(record.get("iterationBudgetMax") or DEFAULT_ITERATION_BUDGET),
        )

    def get_node_detail(self, run_id: str, node_id: str) -> dict[str, Any]:
        record = self.get_run(run_id)
        definition = build_challenge_cup_workflow_definition()
        node = next((n for n in definition.nodes if n.nodeId == node_id), None)
        if node is None:
            raise ResearchWorkflowError(f"Unknown nodeId: {node_id}", code="unknown_node")
        snapshots = {s["nodeId"]: s for s in record.get("bindingSnapshots") or []}
        snap = snapshots.get(node_id) or {}
        bridge = SessionBindingBridge(self._store)
        chat_href, degraded = bridge.deep_link_for(record, node_id)
        if node.actorKind is not ActorKind.AGENT:
            degraded = False
            chat_href = None
        display_name = ""
        if snap.get("agentId"):
            display_name = _agent_display_name(str(snap["agentId"]))
        return {
            "runId": run_id,
            "nodeId": node_id,
            "actorKind": node.actorKind.value,
            "primaryRoleKey": node.primaryRoleKey,
            "label": node.label,
            "bindingSnapshot": {**snap, "displayName": display_name},
            "sessionBinding": self._store.get_session_binding(run_id, node_id),
            "chatDeepLink": chat_href,
            "sessionAnchorDegraded": degraded,
            "runtimeCurrent": node_id in (record.get("runtimeCurrentNodeIds") or []),
            "status": record.get("status"),
            "nodeAttempt": _node_attempt(record, node_id),
            "blockedReason": str(record.get("blockedReason") or (record.get("langGraph") or {}).get("blockedReason") or ""),
            "artifacts": (record.get("langGraph") or {}).get("artifacts") or {},
            "commands": node_command_capabilities(record, node_id),
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
            # Uniqueness is definition edgeId only (never mix with from->to keys).
            existing_edge_ids = existing_active_edge_ids(existing_handoffs)

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

            # Handoff for this gate (adjacent definition edge) — human lineage first.
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
            handoff.setdefault("nodeAttempt", 1)
            self._store.append_handoff(run_id, handoff)
            human_edge_id = handoff_edge_id(handoff)
            if human_edge_id:
                existing_edge_ids.add(human_edge_id)

            # Auto handoffs for newly completed agent nodes after this resume.
            # Must not re-append the human gate edge (same definition edgeId).
            if accept:
                self._append_auto_handoffs(
                    run_id=run_id,
                    workflow_id=workflow_id,
                    workflow_version_id=workflow_version_id,
                    completed=completed,
                    artifacts=artifacts,
                    existing_edge_ids=existing_edge_ids,
                )

            # Create next pending HumanTask only for human-gated nodes
            if accept and runtime_nodes:
                next_gate = runtime_nodes[0]
                next_spec = next(
                    (n for n in build_challenge_cup_workflow_definition().nodes if n.nodeId == next_gate),
                    None,
                )
                is_human_gate = next_spec is not None and next_spec.actorKind is ActorKind.HUMAN
                # Avoid duplicate pending for same node
                tasks_now = list((self.get_run(run_id).get("humanTasks") or []))
                has_pending_next = any(
                    str(t.get("nodeId")) == next_gate and str(t.get("status")) == "pending"
                    for t in tasks_now
                )
                if is_human_gate and not has_pending_next:
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

            run_patch: dict[str, Any] = {
                "status": status,
                "runtimeCurrentNodeIds": runtime_nodes if accept else [gate_node],
                "langGraph": lg_snapshot,
            }
            # Promotion / rollback HumanTask: only on accept update official candidate ref.
            if gate_node == "candidate_promotion":
                proposals = list(record.get("promotionProposals") or [])
                op = str(task.get("promotionOperation") or record.get("promotionOperation") or "promote")
                proposal_id = str(task.get("proposalId") or "")
                if accept:
                    for prop in proposals:
                        if proposal_id and prop.get("proposalId") == proposal_id:
                            prop["status"] = "accepted"
                            target = str(prop.get("targetCandidateRef") or prop.get("selectedCandidateRef") or "")
                            if op == "promote":
                                run_patch["officialCandidateRef"] = target or prop.get("selectedCandidateRef") or f"candidate:{proposal_id}"
                            elif op == "rollback":
                                run_patch["officialCandidateRef"] = target
                            break
                    else:
                        # No proposal id match — still mark latest
                        if proposals:
                            proposals[-1]["status"] = "accepted"
                            run_patch["officialCandidateRef"] = str(
                                proposals[-1].get("targetCandidateRef")
                                or proposals[-1].get("selectedCandidateRef")
                                or record.get("officialCandidateRef")
                                or ""
                            )
                    run_patch["promotionProposals"] = proposals
                    if not runtime_nodes:
                        run_patch["completionKind"] = "promoted" if op == "promote" else "rolled_back"
                        run_patch["status"] = "succeeded"
                else:
                    for prop in proposals:
                        if proposal_id and prop.get("proposalId") == proposal_id:
                            prop["status"] = "rejected"
                    run_patch["promotionProposals"] = proposals
                    run_patch["status"] = "blocked"
                    run_patch["blockedReason"] = "promotion_rejected"
                    # Downstream result_package must remain locked
                    run_patch["runtimeCurrentNodeIds"] = [gate_node]

            self._store.update_run(run_id, run_patch)
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

    def apply_iteration_decision(
        self,
        run_id: str,
        decision: dict[str, Any],
        *,
        idempotency_key: str = "",
        decided_by: str = "",
    ) -> dict[str, Any]:
        """Apply one of the five structured iteration decisions (durable + graph resume)."""
        with self._lock:
            record = self.get_run(run_id)
            key = idempotency_key or str(decision.get("idempotencyKey") or "")
            if key:
                prior = find_decision_by_idempotency(record, key)
                if prior:
                    return self.get_run(run_id)
                durable_key = f"iterdec:{run_id}:{key}"
                if self._index.get_run_id(durable_key):
                    return self.get_run(run_id)

            payload = dict(decision)
            if key:
                payload["idempotencyKey"] = key
            if decided_by:
                payload["decidedBy"] = decided_by
            payload.setdefault("budgetMax", int(record.get("iterationBudgetMax") or DEFAULT_ITERATION_BUDGET))

            thread_id = str(record.get("threadId") or "")
            workflow_id = str(record.get("workflowId") or CHALLENGE_CUP_WORKFLOW_ID)
            workflow_version_id = str(record.get("workflowVersionId") or "")
            checkpoint_id = ""
            lg_snapshot = dict(record.get("langGraph") or {})
            runtime_nodes: list[str] = []

            try:
                with open_sqlite_checkpointer(self._checkpoint_path) as checkpointer:
                    graph = compile_challenge_cup_graph(checkpointer)
                    cfg = {"configurable": {"thread_id": thread_id}}
                    # Resume iteration_decision interrupt with structured decision
                    graph.invoke(Command(resume=payload), cfg)
                    state = graph.get_state(cfg)
                    checkpoint_id = self._checkpoint_id_from_state(state)
                    runtime_nodes = [str(n) for n in (state.next or [])]
                    values = dict(state.values or {})
                    lg_snapshot = {
                        **lg_snapshot,
                        "engine": "challenge_cup_graph",
                        "completedNodeIds": list(values.get("completed_node_ids") or []),
                        "knowledgePackageAccepted": bool(values.get("knowledge_package_accepted")),
                        "frozenProtocolAccepted": bool(values.get("frozen_protocol_accepted")),
                        "smokeAccepted": bool(values.get("smoke_accepted")),
                        "promotionAccepted": values.get("promotion_accepted"),
                        "artifacts": dict(values.get("artifacts") or {}),
                        "checkpointId": checkpoint_id,
                        "controlledRunAttempt": int(values.get("controlled_run_attempt") or 0),
                        "iterationDecision": values.get("iteration_decision") or payload,
                        "nodeAttempts": dict(values.get("node_attempts") or {}),
                        "officialCandidateRef": values.get("official_candidate_ref")
                        or record.get("officialCandidateRef")
                        or "",
                        "terminalReason": values.get("terminal_reason") or "",
                        "completionKind": values.get("completion_kind") or "",
                        "blockedReason": values.get("blocked_reason") or "",
                        "promotionOperation": values.get("promotion_operation") or "",
                    }
            except IterationDecisionError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            except Exception as exc:
                # Graph may raise on unknown kind during routing
                msg = str(exc)
                if "Unknown iteration" in msg or "unknown_decision" in msg.lower():
                    raise ResearchWorkflowError(msg, code="unknown_decision_kind") from exc
                raise

            def _create_child(skeleton: dict[str, Any]) -> dict[str, Any]:
                # Persist child run shell; start child graph from protocol_design via empty invoke
                # with pre-seeded state is complex — store shell and mark start node.
                child_id = str(skeleton["runId"])
                if key:
                    existing_child = self._index.get_run_id(f"fork:{run_id}:{key}")
                    if existing_child:
                        existing = self._store.get_run(existing_child)
                        if existing:
                            return existing
                self._store.create_run(skeleton)
                # Seed child checkpoint by compiling and updating state is optional for shell;
                # mark runtime at protocol_design for canvas.
                self._store.update_run(
                    child_id,
                    {
                        "status": "running",
                        "runtimeCurrentNodeIds": ["protocol_design"],
                        "langGraph": {
                            **(skeleton.get("langGraph") or {}),
                            "startNodeId": "protocol_design",
                            "engine": "challenge_cup_graph",
                        },
                    },
                )
                if key:
                    self._index.put_run_id(f"fork:{run_id}:{key}", child_id)
                return self.get_run(child_id)

            try:
                effects = apply_iteration_decision_side_effects(
                    record=record,
                    decision_raw=payload,
                    graph_state={
                        "artifacts": lg_snapshot.get("artifacts") or {},
                        "controlled_run_attempt": lg_snapshot.get("controlledRunAttempt") or 0,
                        "iteration_budget_max": record.get("iterationBudgetMax") or DEFAULT_ITERATION_BUDGET,
                        "blocked_reason": lg_snapshot.get("blockedReason") or "",
                    },
                    checkpoint_id=checkpoint_id,
                    workflow_id=workflow_id,
                    workflow_version_id=workflow_version_id,
                    utc_now=_utc_now,
                    create_child_run=_create_child,
                )
            except IterationDecisionError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc

            decision_rec = effects["decision"]
            decisions = list(record.get("iterationDecisions") or [])
            decisions.append(decision_rec)

            patch = dict(effects.get("patch") or {})
            # Merge graph snapshot
            if "langGraph" in patch:
                lg_snapshot = {**lg_snapshot, **patch.pop("langGraph")}
            if effects.get("replace_handoffs") is not None:
                patch["handoffs"] = effects["replace_handoffs"]
            if effects.get("error"):
                patch.setdefault("status", "blocked")
                patch.setdefault("blockedReason", effects["error"].get("code") or "iteration_error")

            # Prefer graph runtime nodes when not forking/stopping
            if patch.get("status") not in {"succeeded", "blocked"} and runtime_nodes:
                patch.setdefault("runtimeCurrentNodeIds", runtime_nodes)
            if effects.get("controlled_run_attempt"):
                lg_snapshot["controlledRunAttempt"] = effects["controlled_run_attempt"]
                na = dict(patch.get("nodeAttempts") or record.get("nodeAttempts") or {})
                na["controlled_run"] = effects["controlled_run_attempt"]
                patch["nodeAttempts"] = na

            # Budget block from graph
            if lg_snapshot.get("blockedReason") == "iteration_budget_exhausted" or (
                effects.get("error") or {}
            ).get("code") == "iteration_budget_exhausted":
                patch["status"] = "blocked"
                patch["blockedReason"] = "iteration_budget_exhausted"
                patch["runtimeCurrentNodeIds"] = ["iteration_decision"]

            # Preserve frozen protocol on parent after revise
            if effects.get("child_run"):
                # parent patch already from link_parent_after_fork
                pass

            if effects.get("human_task"):
                tasks = list(record.get("humanTasks") or [])
                tasks.append(effects["human_task"])
                patch["humanTasks"] = tasks

            patch["iterationDecisions"] = decisions
            patch["langGraph"] = lg_snapshot

            # Official candidate fields
            if "officialCandidateRef" not in patch and lg_snapshot.get("officialCandidateRef"):
                patch["officialCandidateRef"] = lg_snapshot["officialCandidateRef"]
            if lg_snapshot.get("completionKind") and not patch.get("completionKind"):
                patch["completionKind"] = lg_snapshot["completionKind"]
            if lg_snapshot.get("terminalReason") and not patch.get("terminalReason"):
                patch["terminalReason"] = lg_snapshot["terminalReason"]

            self._store.update_run(run_id, patch)
            self._store.append_event(
                run_id,
                {
                    "workflowId": workflow_id,
                    "runId": run_id,
                    "nodeId": "iteration_decision",
                    "type": "iteration.decision_applied",
                    "summary": {
                        "decisionId": decision_rec.get("decisionId"),
                        "decisionKind": decision_rec.get("decisionKind"),
                        "childRunId": (effects.get("child_run") or {}).get("runId"),
                        "error": effects.get("error"),
                    },
                },
            )
            if key:
                self._index.put_run_id(f"iterdec:{run_id}:{key}", run_id)
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
        if command == "iteration_decision":
            return self.apply_iteration_decision(
                run_id,
                payload,
                idempotency_key=idempotency_key or str(payload.get("idempotencyKey") or ""),
                decided_by=str(payload.get("decidedBy") or ""),
            )
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
        record = self.get_run(run_id)
        try:
            bridge = SessionBindingBridge(self._store)
            record_binding = bridge.put(record, node_id, binding)
        except SessionBindingError as exc:
            raise ResearchWorkflowError(str(exc), code=exc.code) from exc
        self._store.append_event(
            run_id,
            {
                "runId": run_id,
                "nodeId": node_id,
                "type": "session_binding.bound",
                "summary": {
                    "bindingId": record_binding["bindingId"],
                    "agentId": record_binding["agentId"],
                    "sessionId": record_binding["sessionId"],
                    "taskId": record_binding["taskId"],
                    "turnId": record_binding["turnId"],
                    "status": record_binding["status"],
                    "supersedesBindingId": record_binding.get("supersedesBindingId") or "",
                },
            },
        )
        return record_binding

    def apply_node_command(
        self,
        run_id: str,
        node_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Node-level command execution through the real backend adapter."""
        with self._lock:
            record = self.get_run(run_id)
            if command == "rebind_node":
                # Controlled rebind keeps snapshot lineage (apply_command).
                return self.apply_command(
                    run_id,
                    "rebind_node",
                    payload={**(payload or {}), "nodeId": node_id},
                )
            try:
                result = apply_node_command(
                    store=self._store,
                    record=record,
                    node_id=node_id,
                    command=command,
                    payload=payload,
                )
            except NodeCommandUnavailable as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            except NodeCommandError as exc:
                raise ResearchWorkflowError(str(exc), code=exc.code) from exc
            self._store.append_event(
                run_id,
                {
                    "runId": run_id,
                    "nodeId": node_id,
                    "type": "node.command.applied",
                    "summary": {
                        "command": command,
                        "result": {k: v for k, v in result.items() if k != "artifacts"},
                    },
                },
            )
            return result

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
