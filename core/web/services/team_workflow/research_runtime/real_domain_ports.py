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
        from .budget_authority_adapter import (
            BudgetAuthorityError,
            reserve_budget_authority,
        )

        try:
            return reserve_budget_authority(
                self._store,
                action=action,
                estimate_tokens=estimate_tokens,
                input_snapshot=self._run_input_snapshot(action.run_id),
            )
        except BudgetAuthorityError as exc:
            raise RuntimeError(str(exc)) from exc

    def settle_budget(self, *, reservation: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
        """Settle reserved budget. Raises RuntimeError on failure (callers must
        treat any raised exception as a hard settle failure)."""
        from .budget_authority_adapter import (
            BudgetAuthorityError,
            settle_budget_authority,
        )

        try:
            return settle_budget_authority(
                self._store, reservation=reservation, usage=usage
            )
        except BudgetAuthorityError as exc:
            raise RuntimeError(f"budget_settle_failed:{exc.code}:{exc}") from exc

    def void_budget(
        self,
        *,
        reservation: dict[str, Any],
        reason: str = "compensation_void",
        correlation_id: str | None = None,
    ) -> None:
        from .budget_authority_adapter import void_budget_reservation

        void_budget_reservation(
            self._store,
            reservation,
            reason=reason,
            correlation_id=correlation_id,
        )

    def release_budget(
        self,
        *,
        reservation: dict[str, Any],
        reason: str = "unused_release",
    ) -> None:
        from .budget_authority_adapter import release_budget_reservation

        release_budget_reservation(
            self._store, reservation, reason=reason
        )

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
            store=self._store,
        )
        _require_canonical_session(
            session_id=handle.session_id,
            agent_id=binding.agent_id,
        )
        return handle

    def execute_agent_turn(
        self, *, action: PendingAction, handle: AgentTaskHandle
    ) -> list[dict[str, str]]:
        from .agent_turn_completion import complete_agent_turn_outputs

        return complete_agent_turn_outputs(
            action=action,
            handle=handle,
            input_snapshot=self._run_input_snapshot(action.run_id),
        )

    def read_back_artifact(self, canonical_ref: str) -> ArtifactReadBack | None:
        return _read_back_real_artifact(canonical_ref)

    # ------------------------------------------------------------ human

    def create_human_task(self, *, action: PendingAction) -> HumanTaskHandle:
        return HumanTaskHandle(task_id=f"ht-{action.action_id}")

    # ------------------------------------------------------------ system

    def execute_system_action(
        self, *, action: PendingAction
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        return _execute_real_system_action(
            action,
            input_snapshot=self._run_input_snapshot(action.run_id),
        )

    def execute_run_smoke(
        self,
        *,
        run_id: str,
        plan_id: str,
        team_id: str = "",
        domain_payload: dict[str, Any] | None = None,
        action_id: str = "",
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """System Smoke observation — writes ``smoke_evidence`` only.

        ``smoke_gate`` remains Human: release is ``smoke_release`` via human resolve.
        """
        snapshot = self._run_input_snapshot(run_id)
        resolved_team = str(team_id or snapshot.get("teamId") or "").strip()
        if not resolved_team:
            raise RuntimeError("run_smoke requires teamId")
        resolved_plan = str(plan_id or "").strip()
        if not resolved_plan:
            request = _system_request_payload(
                snapshot, node_id="smoke_gate", alias="smokeGate"
            )
            resolved_plan = str(
                request.get("planId") or snapshot.get("planId") or ""
            ).strip()
        if not resolved_plan:
            raise RuntimeError("run_smoke requires planId")
        payload = dict(domain_payload or {})
        if not payload:
            request = _system_request_payload(
                snapshot, node_id="smoke_gate", alias="smokeGate"
            )
            payload = {
                key: value
                for key, value in request.items()
                if key not in {"idempotencyKey", "planId"}
            }
        return _ledger_run_smoke(
            run_id=run_id,
            team_id=resolved_team,
            plan_id=resolved_plan,
            source_collection_run_id=str(snapshot.get("sourceCollectionRunId") or ""),
            domain_payload=payload,
            action_id=action_id,
        )


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
    store: WorkflowLedgerStore | None = None,
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
            store=store,
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
    store: WorkflowLedgerStore | None = None,
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
                "title": "Challenge Cup workflow source collection",
                "goal": str(objective.get("question") or ""),
                "topic": str(objective.get("question") or ""),
                "inputRefs": list(input_snapshot.get("datasetRefs") or []),
                "agentRoles": [role_key] if role_key else [],
                "agentIds": {role_key: binding.agent_id} if role_key else {},
                # Deterministic production-chain verification does not consume a live
                # prompt-cache model; SC still creates canonical Session/Task/Turn.
                "promptCachePolicy": {"requirement": "disabled"},
                "scope": {
                    "workflowRunId": action.run_id,
                    "researchProjectId": project_id,
                },
            },
        )
        source_run_id = str((started_run.get("run") or {}).get("runId") or "").strip()
        if source_run_id and store is not None:
            _persist_source_collection_run_id(store, action.run_id, source_run_id)
            input_snapshot["sourceCollectionRunId"] = source_run_id
    if not source_run_id:
        raise RuntimeError("source collection adapter did not return a runId")
    evidence_remediation_contract: dict[str, Any] = {}
    if action.node_id == "source_extraction" and int(action.attempt) > 1:
        from .agent_claim_evidence_materializer import (
            build_formal_evidence_retry_contract,
        )

        evidence_remediation_contract = build_formal_evidence_retry_contract(
            team_id=team_id,
            workflow_run_id=action.run_id,
            source_collection_run_id=source_run_id,
        )
    return start_source_collection_stage_session_task(
        team_id,
        source_run_id,
        {
            "stageId": stage_id,
            "agentId": binding.agent_id,
            "agentRole": role_key,
            "idempotencyKey": idempotency_key,
            "returnLabel": "科研工作流",
            # Evidence remediation defines the extraction scope, not session
            # lifecycle.  The stage-session authority reuses a reviewable
            # session and independently opens a formal retry after a failed
            # terminal task.
            "formalRetry": False,
            "evidenceRemediationContract": evidence_remediation_contract,
        },
    )


def _persist_source_collection_run_id(
    store: WorkflowLedgerStore,
    run_id: str,
    source_run_id: str,
) -> None:
    """Freeze the SC run id into the Ledger input snapshot for successor nodes."""

    def mutate(uow):
        run = uow.repository.get_run(run_id)
        if run is None or not run.input_snapshot_json:
            return
        try:
            snapshot = json.loads(run.input_snapshot_json)
        except (TypeError, ValueError):
            return
        if not isinstance(snapshot, dict):
            return
        if str(snapshot.get("sourceCollectionRunId") or "") == source_run_id:
            return
        snapshot["sourceCollectionRunId"] = source_run_id
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ?, updated_at_ms = ? "
            "WHERE run_id = ?",
            (
                json.dumps(snapshot, ensure_ascii=False),
                int(__import__("time").time() * 1000),
                run_id,
            ),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)


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
    *,
    input_snapshot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Dispatch System nodes to the same domain executors the UI adapters use.

    Returns ``(materialized_refs, meta)`` where ``meta`` must include a non-empty
    ``runnerId`` for ``SystemActionAdapter.verify``. Silent empty success is
    forbidden — missing inputs or incomplete domain results raise.

    ``smoke_gate`` is ActorKind.HUMAN — Smoke domain execution is
    :meth:`RealDomainPorts.execute_run_smoke`, not a SystemActionAdapter path.
    """
    node_id = str(action.node_id or "").strip()
    snapshot = dict(input_snapshot or {})
    if node_id == "controlled_run":
        return _ledger_controlled_run(action, snapshot)
    if node_id == "result_package":
        return _ledger_result_package(action, snapshot)
    if node_id == "smoke_gate":
        raise RuntimeError(
            "smoke_gate is a Human gate; use execute_run_smoke for Smoke evidence "
            "and Human resolve for smoke_release"
        )
    raise RuntimeError(
        f"system node {node_id} has no system executor wired for Ledger production path"
    )


def _persist_workflow_artifact(
    *,
    kind: str,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    payload: dict[str, Any],
    artifact_identity: str,
) -> None:
    from .workflow_artifact_store import put_workflow_artifact

    put_workflow_artifact(
        team_id,
        kind=kind,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id or workflow_run_id,
        payload=payload,
        artifact_identity=artifact_identity,
    )


def _collect_kind_refs(
    kinds: tuple[str, ...],
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    """Collect refs for an explicit kind set (not full node producesArtifactKinds)."""
    from .artifact_readback_registry import (
        build_canonical_ref,
        load_scoped_artifact_payload,
    )
    from .human_gate_artifacts import canonical_sha256

    authority_run_id = (
        str(source_collection_run_id or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not team_id or not authority_run_id:
        raise RuntimeError("team_id and run scope are required to collect artifact refs")
    refs: list[dict[str, str]] = []
    for kind in kinds:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
        if payload is None:
            continue
        content_hash = canonical_sha256(payload)
        refs.append(
            {
                "canonicalRef": build_canonical_ref(
                    kind=kind,
                    team_id=team_id,
                    authority_run_id=authority_run_id,
                    content_hash=content_hash,
                ),
                "kind": kind,
                "sha256": content_hash,
                "version": "1.0.0",
            }
        )
    return refs


def _system_request_payload(
    snapshot: dict[str, Any], *, node_id: str, alias: str
) -> dict[str, Any]:
    """Resolve operator/domain request fields frozen into the run input snapshot."""
    nested = snapshot.get(alias)
    if isinstance(nested, dict):
        return dict(nested)
    requests = snapshot.get("systemActionRequests")
    if isinstance(requests, dict):
        node_payload = requests.get(node_id)
        if isinstance(node_payload, dict):
            return dict(node_payload)
    return {}


def _collect_system_artifact_refs(
    node_id: str,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> list[dict[str, str]]:
    from .agent_turn_completion import collect_required_artifact_refs

    refs = collect_required_artifact_refs(
        node_id,
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
    )
    if not refs:
        raise RuntimeError(
            f"system node {node_id} produced no readable artifact refs"
        )
    return refs


def _ledger_controlled_run(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for controlled_run — same domain call as UI system adapter."""
    from core.research.workflow.contracts import (
        ContractValidationError,
        ExperimentCampaign,
    )
    from core.web.services.team_workflow.experiment_api.full_run import (
        execute_experiment_full_run,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("controlled_run requires teamId in input snapshot")
    request = _system_request_payload(
        snapshot, node_id="controlled_run", alias="controlledRun"
    )
    plan_id = str(
        request.get("planId") or snapshot.get("planId") or ""
    ).strip()
    if not plan_id:
        raise RuntimeError("controlled_run requires planId")
    campaign_raw = request.get("campaign")
    if campaign_raw is None:
        campaign_raw = snapshot.get("campaign")
    if not isinstance(campaign_raw, dict):
        raise RuntimeError("controlled_run requires an ExperimentCampaign")

    domain_payload = {
        key: value
        for key, value in request.items()
        if key not in {"idempotencyKey", "planId", "campaign"}
    }
    result = execute_experiment_full_run(team_id, plan_id, domain_payload)
    execution = dict(result.get("execution") or {})
    execution_id = str(execution.get("executionId") or "").strip()
    if not execution_id or execution.get("status") != "completed":
        raise RuntimeError("controlled run did not return a completed execution")

    result_ref = f"experiment-run:{execution_id}"
    try:
        ExperimentCampaign.from_dict(
            {
                **campaign_raw,
                "runId": action.run_id,
                "experimentRunRefs": [result_ref],
                "resultArtifactRefs": [result_ref],
            }
        )
    except ContractValidationError as exc:
        raise RuntimeError(str(exc)) from exc

    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "sourceCollectionRunId": sc_run_id or action.run_id,
        "planId": plan_id,
        "executionId": execution_id,
        "observationRef": result_ref,
        "execution": execution,
        "campaign": {
            **campaign_raw,
            "runId": action.run_id,
            "experimentRunRefs": [result_ref],
            "resultArtifactRefs": [result_ref],
        },
    }
    _persist_workflow_artifact(
        kind="run_artifacts",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload=artifact_payload,
    )
    refs = _collect_system_artifact_refs(
        "controlled_run",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    runner_id = str(
        execution.get("adapterId")
        or result.get("adapterId")
        or execution.get("runnerId")
        or "formal_runner"
    ).strip()
    if not runner_id:
        raise RuntimeError("controlled_run requires a non-empty runnerId")
    return refs, {
        "systemActionId": f"sys-{action.action_id}",
        "runnerId": runner_id,
        "executionId": execution_id,
        "planId": plan_id,
        "observationRef": result_ref,
    }


def _ledger_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for result_package — same builder as UI system adapter."""
    from .result_package import ResultPackageError, build_result_package

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        raise RuntimeError("result_package requires teamId in input snapshot")
    request = _system_request_payload(
        snapshot, node_id="result_package", alias="resultPackage"
    )
    record = request.get("workflowRecord")
    if not isinstance(record, dict):
        record = snapshot.get("workflowRunProjection")
    if not isinstance(record, dict):
        raise RuntimeError(
            "result_package requires a workflow run projection in input snapshot"
        )
    research_ledger = request.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = snapshot.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = {}

    try:
        package = build_result_package(record, research_ledger=research_ledger)
    except ResultPackageError as exc:
        raise RuntimeError(str(exc)) from exc
    if not isinstance(package, dict) or not str(package.get("packageId") or "").strip():
        raise RuntimeError("result_package builder returned an incomplete package")

    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "sourceCollectionRunId": sc_run_id or action.run_id,
        "package": package,
    }
    _persist_workflow_artifact(
        kind="research_result_package",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload=artifact_payload,
    )
    refs = _collect_system_artifact_refs(
        "result_package",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    return refs, {
        "systemActionId": f"sys-{action.action_id}",
        "runnerId": "package_builder",
        "packageId": str(package["packageId"]),
        "factChainHash": str(package.get("factChainHash") or ""),
        "observationRef": str(
            package.get("packageId") or f"research_result_package:{action.action_id}"
        ),
    }


def _ledger_run_smoke(
    *,
    run_id: str,
    team_id: str,
    plan_id: str,
    source_collection_run_id: str = "",
    domain_payload: dict[str, Any] | None = None,
    action_id: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """System Smoke execution: persist ``smoke_evidence`` only (Human releases)."""
    from core.web.services.team_workflow.experiment_api.smoke import (
        run_experiment_smoke_run,
    )

    result = run_experiment_smoke_run(team_id, plan_id, dict(domain_payload or {}))
    smoke_run = dict(result.get("smokeRun") or {})
    smoke_run_id = str(smoke_run.get("smokeRunId") or "").strip()
    status = str(result.get("status") or smoke_run.get("status") or "").strip()
    if not smoke_run_id:
        raise RuntimeError("Smoke result has no smokeRunId")

    sc_run_id = str(source_collection_run_id or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": run_id,
        "sourceCollectionRunId": sc_run_id or run_id,
        "nodeId": "smoke_gate",
        "planId": plan_id,
        "status": status or "unknown",
        "smokeRunId": smoke_run_id,
        "observationRef": f"smoke-run:{smoke_run_id}",
        "artifactHash": str(smoke_run.get("artifactHash") or ""),
    }
    _persist_workflow_artifact(
        kind="smoke_evidence",
        team_id=team_id,
        workflow_run_id=run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action_id or smoke_run_id,
        payload=artifact_payload,
    )
    refs = _collect_kind_refs(
        ("smoke_evidence",),
        team_id=team_id,
        workflow_run_id=run_id,
        source_collection_run_id=sc_run_id,
    )
    if not refs:
        raise RuntimeError("run_smoke produced no readable smoke_evidence refs")
    return refs, {
        "systemActionId": f"sys-{action_id or smoke_run_id}",
        "runnerId": "smoke_runner",
        "smokeRunId": smoke_run_id,
        "planId": plan_id,
        "observationRef": f"smoke-run:{smoke_run_id}",
        "status": status or "unknown",
        "command": "run_smoke",
    }
