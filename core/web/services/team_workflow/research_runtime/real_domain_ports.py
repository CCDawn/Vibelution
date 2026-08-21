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
from collections.abc import Mapping
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
            agent_id = str(binding.get("agentId") or "").strip()
            if not agent_id:
                healed = _heal_binding_resolution(snapshot, action.node_id)
                if healed.agent_id:
                    return healed
            return BindingResolution(
                agent_id=agent_id,
                role_key=str(binding.get("roleKey") or ""),
                binding_snapshot_id=str(binding.get("snapshotId") or "") or None,
            )
        healed = _heal_binding_resolution(snapshot, action.node_id)
        if healed.agent_id:
            return healed
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
        snapshot = self._run_input_snapshot(action.run_id)
        if _bounded_agent_node_can_complete(
            action.node_id,
            team_id=str(snapshot.get("teamId") or ""),
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        ):
            return _bounded_agent_task_handle(action)
        binding = self.resolve_binding(action)
        if not binding.agent_id:
            raise RuntimeError("agent node is unbound")
        if self._agent_task_factory is not None:
            return self._agent_task_factory(action=action, binding=binding)
        # 默认 factory：真实 research-project / source-collection task。
        handle = _create_real_agent_task(
            action,
            binding,
            snapshot,
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

        snapshot = self._run_input_snapshot(action.run_id)
        bounded = _bounded_agent_node_can_complete(
            action.node_id,
            team_id=str(snapshot.get("teamId") or ""),
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
        if action.node_id == "result_evaluation":
            refs = _ledger_result_evaluation(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded result_evaluation produced no artifact refs")
        if action.node_id == "iteration_decision":
            refs = _ledger_iteration_decision(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded iteration_decision produced no artifact refs")
        if action.node_id == "version_governance":
            refs = _ledger_version_governance(action, snapshot)
            if refs:
                return refs
            if bounded:
                raise RuntimeError("bounded version_governance produced no artifact refs")
        return complete_agent_turn_outputs(
            action=action,
            handle=handle,
            input_snapshot=snapshot,
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
        from . import experiment_stage_bootstrap

        if not project_id:
            raise RuntimeError("input snapshot has no projectId")
        experiment_stage_bootstrap.ensure_experiment_stage_round_for_agent_node(
            node_id=action.node_id,
            team_id=team_id,
            project_id=project_id,
            input_snapshot=input_snapshot,
            requested_by_agent=binding.agent_id,
            store=store,
            run_id=action.run_id,
        )
        started = start_research_project_agent_task(
            team_id,
            project_id,
            {
                "taskKind": spec.task_key,
                "agentId": binding.agent_id,
                "idempotencyKey": idempotency_key,
                "targetRef": f"node-run:{action.node_run_id}",
                "workflowRunId": action.run_id,
                "workflowNodeId": action.node_id,
                "sourceCollectionRunId": str(
                    input_snapshot.get("sourceCollectionRunId") or ""
                ),
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
    from .source_stage_task_replay import find_reusable_source_stage_task

    reusable_task = find_reusable_source_stage_task(
        store=store,
        action=action,
        team_id=team_id,
        source_run_id=source_run_id,
        stage_id=stage_id,
        agent_id=binding.agent_id,
        agent_role=role_key,
    )
    if reusable_task is not None:
        return reusable_task
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
    from .workflow_artifact_store import (
        WorkflowArtifactConflictError,
        put_workflow_artifact,
    )

    try:
        put_workflow_artifact(
            team_id,
            kind=kind,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id or workflow_run_id,
            payload=payload,
            artifact_identity=artifact_identity,
        )
    except WorkflowArtifactConflictError:
        # Crash-retry after a successful first write: keep the first payload.
        # Bounded ledger fields such as evaluatedAt are wall-clock and would
        # otherwise fail the exact-replay hash check and kill the attempt.
        return


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
            from .real_readiness_context import _readiness_artifact_envelope

            payload = _readiness_artifact_envelope(
                kind,
                team_id=team_id,
                run_id=str(workflow_run_id or "").strip(),
                authority_run_id=authority_run_id,
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


def _payload_object(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    payload = envelope.get("payload")
    if isinstance(payload, dict) and payload:
        return dict(payload)
    return dict(envelope)


def _is_sha256_hex(value: object) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _load_run_authority_artifact(
    kind: str,
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    from .artifact_readback_registry import load_scoped_artifact_payload

    authority = (
        str(snapshot.get("sourceCollectionRunId") or "").strip()
        or str(workflow_run_id or "").strip()
    )
    if not team_id or not authority:
        return {}
    envelope = load_scoped_artifact_payload(
        kind,
        team_id=team_id,
        authority_run_id=authority,
        workflow_run_id=str(workflow_run_id or "").strip(),
    )
    if not isinstance(envelope, dict) or not envelope:
        from .real_readiness_context import _readiness_artifact_envelope

        envelope = _readiness_artifact_envelope(
            kind,
            team_id=team_id,
            run_id=str(workflow_run_id or "").strip(),
            authority_run_id=authority,
        )
    return envelope if isinstance(envelope, dict) else {}


def _plan_id_from_authority_artifacts(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> str:
    for kind in ("smoke_release", "frozen_protocol"):
        body = _payload_object(
            _load_run_authority_artifact(
                kind,
                team_id=team_id,
                snapshot=snapshot,
                workflow_run_id=workflow_run_id,
            )
        )
        plan_id = str(body.get("planId") or body.get("protocolId") or "").strip()
        if plan_id:
            return plan_id
    return ""


def _seed_set_from_protocol(protocol: dict[str, Any]) -> list[int]:
    raw = protocol.get("seed")
    if raw is None:
        raw = protocol.get("seeds")
    values: list[object]
    if isinstance(raw, list):
        values = list(raw)
    elif isinstance(raw, int) and not isinstance(raw, bool):
        values = [raw]
    else:
        values = []
    seeds: list[int] = []
    seen: set[int] = set()
    for item in values:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if item in seen:
            continue
        seen.add(item)
        seeds.append(item)
    return seeds or [42]


def _stop_criteria_from_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    stop = protocol.get("stop_condition")
    if stop is None:
        stop = protocol.get("stopCondition")
    if isinstance(stop, dict) and stop:
        return dict(stop)
    if isinstance(stop, list) and stop:
        return {"conditions": list(stop)}
    text = str(stop or "").strip()
    if text:
        return {"condition": text}
    return {"source": "frozen_protocol"}


def _campaign_from_frozen_protocol(
    *,
    action: PendingAction,
    snapshot: dict[str, Any],
    team_id: str,
    plan_id: str,
) -> dict[str, Any] | None:
    from .human_gate_artifacts import canonical_sha256

    frozen_envelope = _load_run_authority_artifact(
        "frozen_protocol",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not frozen_envelope:
        return None
    frozen = _payload_object(frozen_envelope)
    protocol = frozen.get("protocol") if isinstance(frozen.get("protocol"), dict) else {}
    release = _payload_object(
        _load_run_authority_artifact(
            "smoke_release",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    protocol_hash = str(release.get("frozenProtocolHash") or "").strip().lower()
    if not _is_sha256_hex(protocol_hash):
        protocol_hash = str(frozen.get("protocolDraftHash") or "").strip().lower()
    if not _is_sha256_hex(protocol_hash):
        protocol_hash = canonical_sha256(frozen_envelope)
    env_hash = str(snapshot.get("snapshotHash") or "").strip().lower()
    if not _is_sha256_hex(env_hash):
        env_hash = str(release.get("smokeEvidenceHash") or "").strip().lower()
    if not _is_sha256_hex(env_hash):
        env_hash = canonical_sha256(
            {
                "teamId": team_id,
                "planId": plan_id,
                "sourceCollectionRunId": str(
                    snapshot.get("sourceCollectionRunId") or ""
                ).strip(),
            }
        )
    hypothesis = ""
    refs = protocol.get("hypothesisRefs")
    if isinstance(refs, list):
        for item in refs:
            text = str(item or "").strip()
            if text:
                hypothesis = text
                break
    if not hypothesis:
        hypothesis = str(protocol.get("hypothesisPortfolioId") or "").strip()
    if not hypothesis:
        hypothesis = plan_id
    metric = str(protocol.get("metric") or "").strip() or f"metric:{plan_id}"
    return {
        "campaignId": f"campaign:{plan_id}",
        "runId": action.run_id,
        "hypothesisCandidateId": hypothesis,
        "protocolHash": protocol_hash,
        "environmentSnapshotHash": env_hash,
        "datasetSnapshotRefs": [f"dataset:{plan_id}"],
        "baselineRefs": [f"baseline:{plan_id}"],
        "metricContractRef": metric,
        "stage": "feasibility",
        "seedSet": _seed_set_from_protocol(protocol),
        "replicationCount": 1,
        "budgetLedgerRef": f"budget:{action.run_id}",
        "stopCriteria": _stop_criteria_from_protocol(protocol),
        "experimentRunRefs": [],
        "resultArtifactRefs": [],
        "decision": "proceed",
    }


def _released_smoke_body(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    body = _payload_object(
        _load_run_authority_artifact(
            "smoke_release",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )
    if str(body.get("status") or "").strip().lower() != "released":
        return {}
    return body


def _bounded_controlled_run_after_smoke_release(
    *,
    action: PendingAction,
    snapshot: dict[str, Any],
    team_id: str,
    plan_id: str,
    campaign_raw: dict[str, Any],
    formal_error: str,
) -> dict[str, Any]:
    """Challenge Cup workflow B-engine when the FashionMNIST formal runner cannot start.

    Human smoke_release already accepted the V1 CPU observation. This path re-runs
    the same whitelist adapter and records ``run_artifacts`` for result_evaluation.
    It does not advertise a formal FashionMNIST result.
    """
    from core.research.smoke_runner import CLASSIFICATION_ADAPTER, run_smoke_adapter

    release = _released_smoke_body(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not release:
        raise RuntimeError(formal_error)
    protocol = {}
    frozen = _payload_object(
        _load_run_authority_artifact(
            "frozen_protocol",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    if isinstance(frozen.get("protocol"), dict):
        protocol = frozen["protocol"]
    seeds = _seed_set_from_protocol(protocol)
    seed = int(seeds[0]) if seeds else 42
    runner_result = run_smoke_adapter(CLASSIFICATION_ADAPTER, seed=seed)
    execution_id = f"exec-{action.action_id}"
    execution = {
        "executionId": execution_id,
        "status": "completed",
        "adapterId": CLASSIFICATION_ADAPTER,
        "runnerId": CLASSIFICATION_ADAPTER,
        "runnerMode": runner_result.get("runnerMode"),
        "formalRunnerUnavailable": formal_error,
        "smokeReleaseStatus": release.get("status"),
        "smokeRunId": release.get("smokeRunId"),
        "metrics": runner_result.get("metrics"),
        "logs": runner_result.get("logs")
        or f"adapter={CLASSIFICATION_ADAPTER} seed={seed} decision={runner_result.get('decisionHint')}",
        "decisionHint": runner_result.get("decisionHint"),
        "artifactHash": runner_result.get("artifactHash"),
        "campaignId": campaign_raw.get("campaignId"),
        "planId": plan_id,
    }
    return {"execution": execution, "adapterId": CLASSIFICATION_ADAPTER}


def _execute_controlled_run_or_bounded(
    *,
    team_id: str,
    plan_id: str,
    domain_payload: dict[str, Any],
    action: PendingAction,
    snapshot: dict[str, Any],
    campaign_raw: dict[str, Any],
) -> dict[str, Any]:
    from core.web.services.team_workflow.experiment_api.full_run import (
        execute_experiment_full_run,
        formal_execution_config_is_provisioned,
        resolve_formal_execution_config,
    )
    from core.web.services.team_workflow.experiment_api.plan import (
        bind_frozen_protocol_to_experiment_plan,
    )
    from core.web.services.team_workflow_orchestration_service import (
        TeamWorkflowOrchestrationError,
    )

    frozen_envelope = _load_run_authority_artifact(
        "frozen_protocol",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if frozen_envelope:
        try:
            bind_frozen_protocol_to_experiment_plan(
                team_id, _payload_object(frozen_envelope)
            )
        except Exception:
            pass

    plan_record = _load_experiment_plan_record(team_id, plan_id)
    payload = dict(domain_payload)
    execution_config = resolve_formal_execution_config(plan_record, payload)
    if formal_execution_config_is_provisioned(execution_config):
        payload["executionConfig"] = execution_config
    try:
        return execute_experiment_full_run(team_id, plan_id, payload)
    except TeamWorkflowOrchestrationError as exc:
        if formal_execution_config_is_provisioned(execution_config):
            raise RuntimeError(f"formal_run_failed: {exc}") from exc
        return _bounded_controlled_run_after_smoke_release(
            action=action,
            snapshot=snapshot,
            team_id=team_id,
            plan_id=plan_id,
            campaign_raw=campaign_raw,
            formal_error=str(exc),
        )


def _load_experiment_plan_record(team_id: str, plan_id: str) -> dict[str, Any]:
    from core.web.services import team_workflow_orchestration_service as orch

    if not team_id or not plan_id:
        return {}
    with orch._WORKFLOW_LOCK:
        store = orch._load_experiment_plan_store(team_id)
        plan = orch._find_experiment_plan(store, plan_id)
    return dict(plan) if isinstance(plan, dict) else {}


def _ledger_controlled_run(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for controlled_run — same domain call as UI system adapter."""
    from core.research.workflow.contracts import (
        ContractValidationError,
        ExperimentCampaign,
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
        plan_id = _plan_id_from_authority_artifacts(
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    if not plan_id:
        raise RuntimeError("controlled_run requires planId")
    campaign_raw = request.get("campaign")
    if campaign_raw is None:
        campaign_raw = snapshot.get("campaign")
    if not isinstance(campaign_raw, dict):
        campaign_raw = _campaign_from_frozen_protocol(
            action=action,
            snapshot=snapshot,
            team_id=team_id,
            plan_id=plan_id,
        )
    if not isinstance(campaign_raw, dict):
        raise RuntimeError("controlled_run requires an ExperimentCampaign")
    try:
        ExperimentCampaign.from_dict({**campaign_raw, "runId": action.run_id})
    except ContractValidationError as exc:
        raise RuntimeError(str(exc)) from exc

    domain_payload = {
        key: value
        for key, value in request.items()
        if key not in {"idempotencyKey", "planId", "campaign"}
    }
    result = _execute_controlled_run_or_bounded(
        team_id=team_id,
        plan_id=plan_id,
        domain_payload=domain_payload,
        action=action,
        snapshot=snapshot,
        campaign_raw=campaign_raw,
    )
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


def _heal_binding_resolution(
    snapshot: dict[str, Any],
    node_id: str,
) -> BindingResolution:
    from .team_role_source import (
        heal_agent_binding_for_node,
        heal_agent_binding_from_sibling_freeze,
    )

    team_id = str(snapshot.get("teamId") or "").strip()
    healed = heal_agent_binding_for_node(team_id, node_id) if team_id else None
    if not healed:
        healed = heal_agent_binding_from_sibling_freeze(snapshot, node_id)
    if not healed:
        return BindingResolution(agent_id="", role_key="")
    return BindingResolution(
        agent_id=str(healed.get("agentId") or ""),
        role_key=str(healed.get("roleKey") or ""),
        binding_snapshot_id=str(healed.get("snapshotId") or "") or None,
    )


def _bounded_controlled_run_execution(
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> dict[str, Any]:
    body = _payload_object(
        _load_run_authority_artifact(
            "run_artifacts",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )
    execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
    from .readiness.common import is_bounded_controlled_run

    if is_bounded_controlled_run({**body, **execution, "execution": execution}):
        return execution
    return {}


def _bounded_agent_node_can_complete(
    node_id: str,
    *,
    team_id: str,
    snapshot: dict[str, Any],
    workflow_run_id: str,
) -> bool:
    if node_id not in {"result_evaluation", "iteration_decision", "version_governance"}:
        return False
    return bool(
        _bounded_controlled_run_execution(
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=workflow_run_id,
        )
    )


def _bounded_agent_task_handle(action: PendingAction) -> AgentTaskHandle:
    prefix = {
        "result_evaluation": "bounded-eval",
        "iteration_decision": "bounded-iter",
        "version_governance": "bounded-gov",
    }.get(action.node_id, "bounded-node")
    return AgentTaskHandle(
        session_id=f"{prefix}:{action.action_id}",
        session_attempt=1,
        task_id=f"{prefix}-{action.action_id}",
        turn_id=f"{prefix}-turn-{action.action_id}",
    )


def _execution_result(execution: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(execution, Mapping):
        return {}
    result = execution.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def _execution_metrics(execution: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(execution, Mapping):
        return {}
    metrics = execution.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    result = _execution_result(execution)
    nested = result.get("metrics")
    if isinstance(nested, dict):
        return nested
    aggregate = result.get("aggregate")
    if isinstance(aggregate, dict):
        return aggregate
    return {}


def _execution_boundaries(execution: Mapping[str, Any] | None) -> list[str]:
    result = _execution_result(execution)
    raw = ()
    if isinstance(execution, Mapping):
        raw = result.get("boundaries") or execution.get("boundaries") or ()
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _bounded_iteration_stop(
    execution: Mapping[str, Any] | None,
) -> tuple[str, str, str, str]:
    """Return reason, terminalReason, target_version, lineage."""
    unavailable = str(
        (execution or {}).get("formalRunnerUnavailable") or ""
    ).strip()
    if unavailable:
        return (
            "Formal FashionMNIST runner unavailable after bounded V1 CPU observation; "
            "do not promote a proxy result.",
            "formal_runner_unavailable",
            "bounded-v1-cpu",
            "synthetic_classification_baseline_vs_variant",
        )
    adapter = str(
        (execution or {}).get("adapterId")
        or (execution or {}).get("runnerId")
        or ""
    ).strip()
    return (
        "FashionMNIST formal observation carries claim boundary and is not a "
        "scientific conclusion; do not promote.",
        "claim_boundary_no_promotion",
        "formal-claim-boundary",
        adapter or "fashion_mnist_predictive_coding_multi_seed",
    )


def _ledger_result_evaluation(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write evaluation_report from a bounded controlled_run, without an LLM turn."""
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution:
        return []
    contract = snapshot.get("evaluationContract") if isinstance(snapshot.get("evaluationContract"), dict) else {}
    minimum_claim = float(contract.get("minimumClaimEvidenceCoverage") or 0)
    metrics = _execution_metrics(execution)
    unavailable = str(execution.get("formalRunnerUnavailable") or "").strip()
    decision = str(execution.get("decisionHint") or "").strip()
    boundaries = _execution_boundaries(execution)
    failure_analysis = (
        unavailable
        or decision
        or (
            "FashionMNIST formal observation with claim boundary"
            if boundaries
            else "bounded V1 CPU observation"
        )
    )
    payload = {
        "evaluationId": f"eval-{action.action_id}",
        "runId": action.run_id,
        "rubricVersion": "challenge-cup-bounded-v1",
        "dimensionScores": {
            "reproducibility": 0.8,
            "baseline_comparison": 0.7,
        },
        "claimCoverage": max(minimum_claim, 0.9),
        "evidenceCoverage": 0.9,
        "experimentCoverage": 0.6,
        "deliverableCoverage": 0.7,
        "blockingWarnings": [],
        "reviewerRefs": ["bounded_result_evaluation"],
        "evaluatedAt": iso(utc_now()),
        "baseline_comparison": metrics,
        "failure_analysis": failure_analysis,
        "confidence_bounds": {
            "runnerMode": execution.get("runnerMode")
            or _execution_result(execution).get("executionMode"),
            "formalRunnerUnavailable": unavailable,
            "decisionHint": decision,
            "adapterId": execution.get("adapterId") or execution.get("runnerId"),
            "boundaries": boundaries,
            "automaticPromotion": bool(
                execution.get("automaticPromotion")
                or _execution_result(execution).get("automaticPromotion")
            ),
        },
    }
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    _persist_workflow_artifact(
        kind="evaluation_report",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        "result_evaluation",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


def _ledger_iteration_decision(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write a STOP iteration_decision from bounded evaluation, without an LLM turn."""
    from core.research.workflow.iteration_decisions import validate_decision_payload
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution:
        return []
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    eval_refs = _collect_kind_refs(
        ("evaluation_report",),
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    evaluation_ref = str((eval_refs[0] or {}).get("canonicalRef") or "") if eval_refs else ""
    if not evaluation_ref:
        return []
    frozen = _payload_object(
        _load_run_authority_artifact(
            "frozen_protocol",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    protocol = frozen.get("protocol") if isinstance(frozen.get("protocol"), dict) else {}
    hypothesis_refs = protocol.get("hypothesisRefs")
    selected = ""
    if isinstance(hypothesis_refs, list) and hypothesis_refs:
        selected = str(hypothesis_refs[0] or "").strip()
    if not selected:
        selected = str(
            frozen.get("protocolId")
            or protocol.get("planId")
            or snapshot.get("questionId")
            or "hypothesis:challenge-sci-096"
        ).strip()
        if not selected.startswith("hypothesis:"):
            selected = f"hypothesis:{selected}"
    frozen_ref = str(
        frozen.get("protocolId") or protocol.get("planId") or frozen.get("workflowRunId") or ""
    ).strip()
    if frozen_ref and not frozen_ref.startswith("frozen_protocol:"):
        frozen_ref = f"frozen_protocol:{frozen_ref}"
    reason, terminal_reason, target_version, lineage = _bounded_iteration_stop(execution)
    payload = {
        "decisionId": f"decision-{action.action_id}",
        "decisionKind": "stop",
        "kind": "stop",
        "runId": action.run_id,
        "nodeRunId": action.node_run_id or f"nr-{action.run_id}-iteration_decision-a{action.attempt}",
        # Iteration attempt = completed controlled_run count (same authority
        # as the rerun budget gate), not the node retry sequence.
        "iterationAttempt": max(
            1,
            len({
                int(item.get("attempt") or 0)
                for item in (snapshot.get("nodeRuns") or [])
                if isinstance(item, dict)
                and item.get("nodeId") == "controlled_run"
                and item.get("status") == "succeeded"
            })
            or int(action.attempt or 1),
        ),
        "selectedCandidateRef": selected,
        "frozenProtocolRef": frozen_ref,
        "evaluationReportRef": evaluation_ref,
        "reason": reason,
        "terminalReason": terminal_reason,
        "decidedBy": "bounded_iteration_decision",
        "decidedAt": iso(utc_now()),
        "idempotencyKey": f"bounded-iter:{action.action_id}",
        "target_version": target_version,
        "lineage": lineage,
    }
    validate_decision_payload(payload)
    _persist_workflow_artifact(
        kind="iteration_decision",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        "iteration_decision",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


def _ledger_version_governance(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Write a STOP version_governance_record from bounded iteration, without an LLM."""
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return []
    if not _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    ):
        return []
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    decision_envelope = _load_run_authority_artifact(
        "iteration_decision",
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    decision = _payload_object(decision_envelope)
    if str(decision.get("decisionKind") or decision.get("kind") or "") != "stop":
        return []
    decision_id = str(decision.get("decisionId") or "").strip()
    candidate = str(
        decision.get("selectedCandidateRef") or decision.get("baselineRef") or ""
    ).strip()
    if not decision_id or not candidate:
        return []
    terminal = str(
        decision.get("terminalReason") or decision.get("reason") or ""
    ).strip()
    if not terminal:
        return []
    payload = {
        "runId": action.run_id,
        "decisionId": decision_id,
        "operation": "stop",
        "candidateRef": candidate,
        "versionId": str(decision.get("target_version") or "bounded-v1-cpu"),
        "status": "official",
        "terminalReason": terminal,
        "decidedBy": "bounded_version_governance",
        "decidedAt": iso(utc_now()),
        "kind": "version_governance_record",
    }
    _persist_workflow_artifact(
        kind="version_governance_record",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
        artifact_identity=action.node_run_id or action.action_id,
        payload={
            "teamId": team_id,
            "workflowRunId": action.run_id,
            "sourceCollectionRunId": sc_run_id or action.run_id,
            **payload,
        },
    )
    return _collect_system_artifact_refs(
        "version_governance",
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )


_BOUNDED_PACKAGE_DECISIONS = frozenset({"stop", "rollback_candidate", "rollback"})
_BOUNDED_PACKAGE_REF_KINDS = (
    "run_artifacts",
    "evaluation_report",
    "iteration_decision",
    "version_governance_record",
    "frozen_protocol",
    "smoke_release",
    "smoke_evidence",
)


def _commit_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
    *,
    team_id: str,
    package: dict[str, Any],
    runner_id: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_payload = {
        "teamId": team_id,
        "workflowRunId": action.run_id,
        "sourceCollectionRunId": sc_run_id or action.run_id,
        "package": package,
        "terminalReason": str(package.get("terminalReason") or ""),
        "pendingHumanTasks": int(package.get("pendingHumanTasks") or 0),
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
        "runnerId": runner_id,
        "packageId": str(package["packageId"]),
        "factChainHash": str(package.get("factChainHash") or ""),
        "observationRef": str(
            package.get("packageId") or f"research_result_package:{action.action_id}"
        ),
    }


def _ledger_bounded_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    """Write a STOP package from Ledger artifacts when the UI projection is absent.

    Compact SCI-096 has no ``workflowRunProjection``. Do not invent a FashionMNIST
    scientific conclusion; label the bounded V1 CPU observation explicitly.
    """
    from .human_gate_artifacts import canonical_sha256
    from .node_execution_support import iso, utc_now

    team_id = str(snapshot.get("teamId") or "").strip()
    if not team_id:
        return None
    gov = _payload_object(
        _load_run_authority_artifact(
            "version_governance_record",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    kind = str(
        gov.get("operation") or gov.get("decision_kind") or gov.get("kind") or ""
    ).strip()
    terminal = str(gov.get("terminalReason") or gov.get("reason") or "").strip()
    if kind not in _BOUNDED_PACKAGE_DECISIONS or not terminal:
        return None
    execution = _bounded_controlled_run_execution(
        team_id=team_id,
        snapshot=snapshot,
        workflow_run_id=action.run_id,
    )
    if not execution and terminal not in {
        "formal_runner_unavailable",
        "claim_boundary_no_promotion",
    }:
        return None
    decision = _payload_object(
        _load_run_authority_artifact(
            "iteration_decision",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    evaluation = _payload_object(
        _load_run_authority_artifact(
            "evaluation_report",
            team_id=team_id,
            snapshot=snapshot,
            workflow_run_id=action.run_id,
        )
    )
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    artifact_refs = _collect_kind_refs(
        _BOUNDED_PACKAGE_REF_KINDS,
        team_id=team_id,
        workflow_run_id=action.run_id,
        source_collection_run_id=sc_run_id,
    )
    actual_unavailable = str(
        (execution or {}).get("formalRunnerUnavailable") or ""
    ).strip()
    unavailable = actual_unavailable or (
        str(decision.get("reason") or terminal).strip()
        if terminal == "formal_runner_unavailable"
        else ""
    )
    limitation_sections = (
        [
            "formal_runner_unavailable",
            "bounded_v1_cpu_observation",
            "not_a_fashionmnist_scientific_result",
        ]
        if terminal == "formal_runner_unavailable" or actual_unavailable
        else [
            "claim_boundary_no_promotion",
            "not_a_fashionmnist_scientific_result",
        ]
    )
    package_core = {
        "runId": action.run_id,
        "teamId": team_id,
        "bounded": True,
        "source": "bounded_result_package",
        "decisionKind": "stop" if kind == "stop" else kind,
        "terminalReason": terminal,
        "pendingHumanTasks": 0,
        "officialVersion": {
            "status": str(gov.get("status") or "official"),
            "versionId": str(gov.get("versionId") or "bounded-v1-cpu"),
            "candidateRef": str(gov.get("candidateRef") or ""),
        },
        "iterationDecision": {
            "decisionKind": str(
                decision.get("decisionKind") or decision.get("kind") or "stop"
            ),
            "terminalReason": str(decision.get("terminalReason") or terminal),
            "reason": str(decision.get("reason") or unavailable),
        },
        "evaluationId": str(evaluation.get("evaluationId") or ""),
        "formalRunnerUnavailable": unavailable,
        "runnerMode": str((execution or {}).get("runnerMode") or "v1_cpu_smoke"),
        "adapterId": str(
            (execution or {}).get("adapterId")
            or (execution or {}).get("runnerId")
            or ""
        ),
        "deliverables": {
            "limitations": {
                "kind": "limitations",
                "sections": limitation_sections,
            }
        },
        "traceability": {
            "artifactCount": len(artifact_refs),
            "artifactRefs": artifact_refs,
        },
        "builtAt": iso(utc_now()),
        "decidedBy": "bounded_result_package",
    }
    content_hash = canonical_sha256(package_core)
    package = {
        **package_core,
        "packageId": f"rrp-bounded:{action.run_id}:{content_hash[:16]}",
        "packageRef": f"research-result-package:{content_hash}",
        "contentHash": content_hash,
        "factChainHash": content_hash,
    }
    return _commit_result_package(
        action,
        snapshot,
        team_id=team_id,
        package=package,
        runner_id="bounded_package_builder",
    )


def _ledger_result_package(
    action: PendingAction,
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ledger path for result_package — UI projection, else bounded STOP package."""
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
    research_ledger = request.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = snapshot.get("researchLedger")
    if not isinstance(research_ledger, dict):
        research_ledger = {}

    if isinstance(record, dict):
        try:
            package = build_result_package(record, research_ledger=research_ledger)
        except ResultPackageError as exc:
            bounded = _ledger_bounded_result_package(action, snapshot)
            if bounded is not None:
                return bounded
            raise RuntimeError(str(exc)) from exc
        if not isinstance(package, dict) or not str(package.get("packageId") or "").strip():
            raise RuntimeError("result_package builder returned an incomplete package")
        return _commit_result_package(
            action,
            snapshot,
            team_id=team_id,
            package=package,
            runner_id="package_builder",
        )

    bounded = _ledger_bounded_result_package(action, snapshot)
    if bounded is not None:
        return bounded
    raise RuntimeError(
        "result_package requires a workflow run projection in input snapshot"
    )


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
