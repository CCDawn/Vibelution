"""Create a WorkflowRun in the Ledger (T8; no JSON writer)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.bindings import (
    AgentBindingLayers,
    build_run_binding_snapshots,
)
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.ledger import EventRecord, RunRecord
from core.research.workflow.models import ActorKind

from .binding_config import WorkflowBindingConfigStore
from .checkpoint_lifecycle import prepare_initial_checkpoint
from .formal_write_runtime import get_write_store
from .paths import research_workflow_data_root
from .question_launch import QuestionLaunchError, build_question_run_input
from .run_catalog import catalog_dict_from_run
from .run_lifecycle import (
    binding_snapshot_payload,
    create_request_fingerprint,
    freeze_run_input,
    run_id_for_create,
)
from .service import ResearchWorkflowError
from .team_role_source import effective_binding_layers


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _auto_open_candidate_generation(run_input: Mapping[str, Any]) -> dict[str, Any] | None:
    """Best-effort round-0 candidate generation for hypothesis-first launches.

    The run is already persisted, so a meeting failure is reported
    structurally instead of rolling the run back.  Only fires when the frozen
    input is hypothesis-first and the question has no selectable candidates
    yet; replays reuse the deterministic meeting id.
    """
    try:
        objective = run_input.get("researchObjectiveContract")
        if not (isinstance(objective, Mapping) and objective.get("hypothesisFirst") is True):
            return None
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        team_id = str(run_input.get("teamId") or "").strip()
        question_id = str(run_input.get("questionId") or "").strip()
        if not team_id or not question_id:
            return None
        if not hypothesis_first_chain.needs_candidate_generation(team_id, question_id):
            return None
        opened = hypothesis_first_chain.open_candidate_generation_meeting(
            team_id,
            question_id,
            background=True,
        )
        return {
            "status": str(opened.get("status") or ""),
            "meetingRoundId": str(
                (opened.get("meetingRound") or {}).get("meetingRoundId") or ""
            ),
        }
    except Exception as exc:  # run fact stays; report the side effect
        return {"status": "failed", "error": str(exc), "errorType": type(exc).__name__}


def create_question_run(
    workflow_id: str,
    *,
    team_id: str,
    question_id: str,
    safety_limits: Mapping[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
        raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
    get_write_store()
    try:
        run_input = build_question_run_input(
            team_id,
            question_id=question_id,
            safety_limits=safety_limits,
        )
    except QuestionLaunchError as exc:
        raise ResearchWorkflowError(str(exc), code=exc.code) from exc
    created = create_run(workflow_id, run_input=run_input, idempotency_key=idempotency_key)
    generation = _auto_open_candidate_generation(run_input)
    if generation is not None:
        created = {**created, "candidateGeneration": generation}
    return created


def _create_request_fingerprints(run_input: Mapping[str, Any]) -> tuple[str, ...]:
    """Return current and legacy fingerprints for a create request.

    ``workflowSessionScopeV3`` is server-owned by ``freeze_run_input``.  It
    therefore must not make two requests with the same idempotency key look
    different merely because a client included (or changed) that field.  Keep
    the raw request fingerprint as a replay fallback for runs written before
    this normalization was introduced.
    """
    canonical_request = dict(run_input)
    canonical_request.pop("workflowSessionScopeV3", None)
    canonical = create_request_fingerprint(canonical_request)
    legacy = create_request_fingerprint(run_input)
    return tuple(dict.fromkeys((canonical, legacy)))


def _ensure_create_fingerprint(run: Any, fingerprints: tuple[str, ...]) -> None:
    snapshot: dict[str, Any] = {}
    try:
        snapshot = json.loads(run.input_snapshot_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    prior = str(snapshot.get("createInputFingerprint") or "")
    if prior and prior not in fingerprints:
        raise ResearchWorkflowError(
            "idempotencyKey was already used with different run input",
            code="idempotency_conflict",
        )


def create_run(
    workflow_id: str,
    *,
    run_input: Mapping[str, Any],
    idempotency_key: str,
    binding_layers: AgentBindingLayers | None = None,
) -> dict[str, Any]:
    store = get_write_store()
    definition = build_challenge_cup_workflow_definition()
    workflow_version_id = f"wv-{definition.structureHash[:12]}"
    fingerprints = _create_request_fingerprints(run_input)
    fingerprint = fingerprints[0]
    run_id = run_id_for_create(workflow_id, idempotency_key)
    existing = store.get_run(run_id)
    if existing is not None:
        _ensure_create_fingerprint(existing, fingerprints)
        return catalog_dict_from_run(existing)

    team_id = str(run_input.get("teamId") or "").strip()
    binding_root = research_workflow_data_root() / "runs"
    layers = binding_layers or WorkflowBindingConfigStore(binding_root).load(workflow_id, team_id)
    if not (
        layers.workflowDefaults or layers.stageOverrides or layers.nodeOverrides
    ):
        layers = effective_binding_layers(team_id, layers)
    created_at = _utc_now()
    snapshots = build_run_binding_snapshots(
        run_id=run_id,
        workflow_version_id=workflow_version_id,
        layers=layers,
        captured_at=created_at,
    )
    binding_payloads = [binding_snapshot_payload(item) for item in snapshots]
    try:
        input_snapshot = freeze_run_input(
            run_input,
            workflow_version_id=workflow_version_id,
            binding_snapshots=binding_payloads,
            created_at=created_at,
        )
    except ContractValidationError as exc:
        raise ResearchWorkflowError(str(exc), code="invalid_run_input") from exc

    thread_id = f"thread-{run_id}"
    data_root = research_workflow_data_root()
    checkpoint_path = str(data_root / "checkpoints.sqlite")
    checkpoint_id = prepare_initial_checkpoint(checkpoint_path, thread_id)
    now_ms = int(time.time() * 1000)
    snapshot_dict = input_snapshot.to_dict()
    snapshot_dict["createInputFingerprint"] = fingerprint
    snapshot_dict["createIdempotencyKey"] = idempotency_key
    snapshot_dict["checkpointId"] = checkpoint_id
    first_agent = next(
        (node.nodeId for node in definition.nodes if node.actorKind is ActorKind.AGENT),
        None,
    )
    binding_set_id = str(
        (binding_payloads[0] if binding_payloads else {}).get("snapshotId") or f"binding-{run_id}"
    )
    record = RunRecord(
        run_id=run_id,
        team_id=input_snapshot.teamId,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        thread_id=thread_id,
        project_id=input_snapshot.projectId,
        question_id=input_snapshot.questionId,
        status="created",
        run_version=1,
        last_event_sequence=1,
        input_snapshot_json=json.dumps(snapshot_dict, ensure_ascii=False),
        input_snapshot_hash=input_snapshot.snapshotHash,
        safety_limits_json=json.dumps(dict(run_input.get("safetyLimits") or {}), ensure_ascii=False),
        binding_snapshot_set_id=binding_set_id,
        active_node_id=first_agent,
        parent_run_id=None,
        forked_from_checkpoint_id=None,
        completion_kind=None,
        terminal_reason=None,
        blocked_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        completed_at_ms=None,
    )
    event = EventRecord(
        run_id=run_id,
        sequence=1,
        event_id=f"evt-created-{run_id}",
        run_version=1,
        event_type="run_created",
        actor_json=json.dumps({"actorType": "system", "actorId": "create_run"}),
        correlation_id=idempotency_key or run_id,
        causation_id=None,
        payload_json=json.dumps({"inputSnapshotHash": input_snapshot.snapshotHash}),
        occurred_at_ms=now_ms,
    )

    def mutate(uow) -> None:
        # Concurrent create with the same key: the single writer serializes
        # mutations, so the later request sees the winner's row here and
        # replays idempotently instead of hitting the run_id primary key.
        if uow.repository.get_run(run_id) is not None:
            return
        uow.repository.insert_run(record)
        uow.repository.insert_event(event)

    store.submit(mutate, force_flush=True).result(timeout=15)
    created = store.get_run(run_id)
    if created is not None:
        _ensure_create_fingerprint(created, fingerprints)
    if created is None:
        raise ResearchWorkflowError("created run was not readable", code="workflow_ledger_unavailable")
    return catalog_dict_from_run(created)
