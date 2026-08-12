"""Production DomainPorts implementation (P1-3/P1-4).

Resolves the frozen RunAgentBindingSnapshot from the Workflow Ledger input
snapshot, creates real Agent session/task/turn through the canonical Chat and
research-project task authorities, and reserves/settles budget against the
Workflow Ledger ``budget_receipts`` table (the T5 budget authority).

The adapter worker drives the exact ordering: read-back -> resolve binding ->
reserve -> create task -> turn -> verify -> one ledger commit -> settle.
"""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import WorkflowLedgerStore

from .domain_ports import (
    AgentTaskHandle,
    ArtifactReadBack,
    BindingResolution,
    HumanTaskHandle,
    ReadBackVerdict,
)

DEFAULT_AGENT_ESTIMATE_TOKENS = 25_000


class RealDomainPorts:
    """Real wiring: ledger-backed binding/budget + real Agent session/task."""

    def __init__(
        self,
        store: WorkflowLedgerStore,
        *,
        agent_task_factory: Any | None = None,
        budget_policy_hash: str = "",
    ) -> None:
        self._store = store
        self._agent_task_factory = agent_task_factory
        self._budget_policy_hash = budget_policy_hash

    # ------------------------------------------------------- run snapshot

    def _run_input_snapshot(self, run_id: str) -> dict[str, Any]:
        run = self._store.get_run(run_id)
        if run is None or not run.input_snapshot_json:
            return {}
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return {}
        return snapshot if isinstance(snapshot, dict) else {}

    def read_back_input(self, action: PendingAction) -> ReadBackVerdict:
        snapshot = self._run_input_snapshot(action.run_id)
        snapshot_hash = str(snapshot.get("snapshotHash") or "")
        if action.input_snapshot_hash and snapshot_hash and (
            snapshot_hash != action.input_snapshot_hash
        ):
            return ReadBackVerdict(
                ok=False,
                detail="input snapshot hash drifted",
                revision_vector={},
            )
        return ReadBackVerdict(ok=True, revision_vector={})

    def resolve_binding(self, action: PendingAction) -> BindingResolution:
        snapshot = self._run_input_snapshot(action.run_id)
        for binding in snapshot.get("agentBindingSnapshot") or []:
            if not isinstance(binding, dict):
                continue
            if str(binding.get("nodeId") or "") != action.node_id:
                continue
            return BindingResolution(
                agent_id=str(binding.get("agentId") or ""),
                role_key=str(binding.get("roleKey") or ""),
                binding_snapshot_id=str(binding.get("snapshotId") or "") or None,
            )
        return BindingResolution(agent_id="", role_key="")

    # ------------------------------------------------------------- budget

    def reserve_budget(
        self, *, action: PendingAction, estimate_tokens: int
    ) -> dict[str, Any]:
        reservation_id = f"reservation-{action.node_run_id}"
        return {
            "reservationId": reservation_id,
            "actionId": action.action_id,
            "nodeRunId": action.node_run_id,
            "stageId": _stage_for(action.node_id),
            "policyHash": action.budget_policy_hash or self._budget_policy_hash,
            "reserved": {"estimatedTokens": estimate_tokens},
            "status": "reserved",
        }

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> None:
        reservation_id = str(reservation.get("reservationId") or "")
        if not reservation_id:
            return
        now_ms = int(__import__("time").time() * 1000)
        settled_json = json.dumps(
            {"usage": usage, "source": "adapter-worker"}, ensure_ascii=False
        )

        def mutate(uow):
            # budget_receipts.reservation_id 是唯一键；reserve 时已插入，settle 更新状态。
            row = uow.repository.execute(
                "SELECT receipt_id FROM budget_receipts WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                return
            uow.repository.update_budget_receipt(
                str(row[0]),
                status="settled",
                now_ms=now_ms,
                settled_json=settled_json,
            )

        self._store.submit(mutate, force_flush=True).result(timeout=30)

    # ------------------------------------------------------------ agent

    def create_agent_task(self, *, action: PendingAction) -> AgentTaskHandle:
        from .task_adapter_registry import resolve_agent_task_adapter

        adapter_spec = resolve_agent_task_adapter(action.node_id)
        if adapter_spec is None:
            raise RuntimeError(f"agent node {action.node_id} has no task adapter")
        binding = self.resolve_binding(action)
        if not binding.agent_id:
            raise RuntimeError("agent node is unbound")
        if self._agent_task_factory is not None:
            return self._agent_task_factory(action=action, binding=binding)
        # 默认 factory：真实 research-project / source-collection task。
        handle = _create_real_agent_task(
            action,
            binding,
            self._run_input_snapshot(action.run_id),
            adapter_spec=adapter_spec,
        )
        _require_canonical_session(
            session_id=handle.session_id,
            agent_id=binding.agent_id,
        )
        return handle

    def execute_agent_turn(
        self, *, action: PendingAction, handle: AgentTaskHandle
    ) -> list[dict[str, str]]:
        # turn 已在 create_agent_task 提交；此处仅返回空（read-back 走 artifact store）。
        return []

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None:
        return _read_back_real_artifact(canonical_ref)

    # ------------------------------------------------------------ human

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle:
        return HumanTaskHandle(task_id=f"ht-{action.action_id}")

    # ------------------------------------------------------------ system

    def execute_system_action(
        self, *, action: PendingAction
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        return _execute_real_system_action(action)


def _stage_for(node_id: str) -> str:
    _STAGE_BY_NODE = {
        "source_finding": "knowledge_collection",
        "source_extraction": "knowledge_collection",
        "evidence_relations": "knowledge_collection",
        "knowledge_ingestion": "knowledge_collection",
        "knowledge_handoff": "knowledge_collection",
        "hypothesis_design": "experiment_design",
        "protocol_design": "experiment_design",
        "protocol_review": "experiment_design",
        "protocol_freeze": "experiment_design",
        "smoke_gate": "experiment_design",
        "controlled_run": "execution_iteration",
        "result_evaluation": "execution_iteration",
        "iteration_decision": "execution_iteration",
        "version_governance": "execution_iteration",
        "candidate_promotion": "execution_iteration",
        "result_package": "execution_iteration",
    }
    return _STAGE_BY_NODE.get(node_id, "execution_iteration")


def _create_real_agent_task(
    action: PendingAction,
    binding: BindingResolution,
    input_snapshot: dict[str, Any],
    *,
    adapter_spec: Any | None = None,
) -> AgentTaskHandle:
    from .task_adapter_registry import AgentTaskAdapterSpec, resolve_agent_task_adapter

    spec = adapter_spec or resolve_agent_task_adapter(action.node_id)
    if not isinstance(spec, AgentTaskAdapterSpec):
        raise RuntimeError(f"agent node {action.node_id} has no task adapter")
    team_id = str(input_snapshot.get("teamId") or "").strip()
    project_id = str(input_snapshot.get("projectId") or "").strip()
    if not team_id:
        raise RuntimeError("input snapshot has no teamId")
    idempotency_key = f"agent-task:{action.node_run_id}"
    if spec.family == "source_collection":
        started = _start_source_collection_agent_task(
            team_id=team_id,
            project_id=project_id,
            input_snapshot=input_snapshot,
            action=action,
            binding=binding,
            stage_id=spec.task_key,
            role_key=spec.role_key or binding.role_key,
            idempotency_key=idempotency_key,
        )
    else:
        from core.web.services.team_workflow.research_project_agent_tasks import (
            start_research_project_agent_task,
        )

        if not project_id:
            raise RuntimeError("input snapshot has no projectId")
        started = start_research_project_agent_task(
            team_id,
            project_id,
            {
                "taskKind": spec.task_key,
                "agentId": binding.agent_id,
                "idempotencyKey": idempotency_key,
                "targetRef": f"node-run:{action.node_id}",
            },
        )
    return _agent_handle_from_started(started)


def _task_kind_for(node_id: str) -> str | None:
    """Compatibility helper: returns stageId/taskKind key for Agent nodes."""
    from .task_adapter_registry import resolve_agent_task_adapter

    spec = resolve_agent_task_adapter(node_id)
    return None if spec is None else spec.task_key


def _start_source_collection_agent_task(
    *,
    team_id: str,
    project_id: str,
    input_snapshot: dict[str, Any],
    action: PendingAction,
    binding: BindingResolution,
    stage_id: str,
    role_key: str,
    idempotency_key: str,
) -> dict[str, Any]:
    from core.web.services.team_workflow.source_collection.runs import (
        start_source_collection_run,
    )
    from core.web.services.team_workflow.source_collection.stage_session import (
        start_source_collection_stage_session_task,
    )

    source_run_id = str(input_snapshot.get("sourceCollectionRunId") or "").strip()
    if not source_run_id:
        objective = input_snapshot.get("researchObjectiveContract") or {}
        started_run = start_source_collection_run(
            team_id,
            {
                "researchProjectId": project_id,
                "title": "Challenge Cup workflow source collection",
                "goal": str(objective.get("question") or ""),
                "topic": str(objective.get("question") or ""),
                "inputRefs": list(input_snapshot.get("datasetRefs") or []),
                "agentRoles": [role_key] if role_key else [],
                "agentIds": {role_key: binding.agent_id} if role_key else {},
                "scope": {
                    "workflowRunId": action.run_id,
                    "researchProjectId": project_id,
                },
            },
        )
        source_run_id = str((started_run.get("run") or {}).get("runId") or "").strip()
    if not source_run_id:
        raise RuntimeError("source collection adapter did not return a runId")
    return start_source_collection_stage_session_task(
        team_id,
        source_run_id,
        {
            "stageId": stage_id,
            "agentId": binding.agent_id,
            "agentRole": role_key,
            "idempotencyKey": idempotency_key,
            "returnLabel": "科研工作流",
        },
    )


def _agent_handle_from_started(started: dict[str, Any]) -> AgentTaskHandle:
    task = started.get("task") if isinstance(started.get("task"), dict) else {}
    task_turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    session_id = str(started.get("sessionId") or task.get("sessionId") or "")
    turn_id = str(
        task_turn.get("turnId") or task.get("startedTurnId") or started.get("startedTurnId") or ""
    )
    task_id = str(started.get("taskId") or task.get("taskId") or "")
    session_attempt = int(
        started.get("sessionAttempt") or task.get("sessionAttempt") or 1
    )
    if not session_id or not task_id or not turn_id:
        raise RuntimeError("agent task anchor is incomplete")
    return AgentTaskHandle(
        session_id=session_id,
        session_attempt=session_attempt,
        task_id=task_id,
        turn_id=turn_id,
    )


def _require_canonical_session(*, session_id: str, agent_id: str) -> None:
    from core.web.services import session_service

    try:
        detail = session_service.get_session_detail(
            str(session_id or ""),
            message_limit=0,
            transcript_scope="none",
        )
    except Exception as exc:
        raise RuntimeError("Agent task session authority could not be verified") from exc
    if not isinstance(detail, dict) or str(detail.get("id") or "").strip() != str(session_id or ""):
        raise RuntimeError("Agent task session is missing from the canonical session index")
    canonical_agent_id = str(detail.get("agentId") or "").strip()
    if canonical_agent_id and canonical_agent_id != agent_id:
        raise RuntimeError(
            "Agent task session Agent does not match the frozen NodeRun binding"
        )


def _read_back_real_artifact(canonical_ref: str) -> ArtifactReadBack | None:
    from .artifact_readback_registry import read_domain_artifact

    if not canonical_ref:
        return None
    return read_domain_artifact(canonical_ref)


def _execute_real_system_action(
    action: PendingAction,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """System nodes must materialize real artifacts with a non-empty runnerId.

    Full controlled_run / result_package executors remain owned by their domain
    adapters; the production port refuses silent empty success.
    """
    node_id = str(action.node_id or "").strip()
    raise RuntimeError(
        f"system node {node_id} has no system executor wired for Ledger production path"
    )
