"""Create a WorkflowRun in the Ledger (T8; no JSON writer)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from core.research.competition.stage_one_completion_policy import (
    StageOneCompletionPolicyError,
    require_current_stage_one_policy_snapshot,
    stage_one_policy_snapshot_for_definition,
)
from core.research.workflow.bindings import (
    AgentBindingLayers,
    build_run_binding_snapshots,
)
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger import EventRecord, RunRecord
from core.research.workflow.models import ActorKind, WorkflowDefinition

from .binding_config import WorkflowBindingConfigStore
from .checkpoint_lifecycle import prepare_initial_checkpoint
from .challenge_cup_maintenance_fence import assert_writes_allowed
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


def _require_stage_one_authorization_binding(
    run_input: Mapping[str, Any],
    catalog_run_authorization: Mapping[str, Any] | None,
    *,
    workflow_definition_id: str = "",
) -> None:
    raw_policy = run_input.get("stageOneCompletionPolicy")
    if raw_policy is None:
        return
    if not isinstance(raw_policy, Mapping):
        raise ResearchWorkflowError(
            "stage-one completion policy is invalid",
            code="invalid_run_input",
        )
    try:
        normalized_definition_id = str(workflow_definition_id or "").strip()
        if normalized_definition_id:
            # The tracked policy stays pinned to its 2.1.0 identity; a run
            # driven by another registered stage-one definition (the
            # truncated 2.2.0-stage-one chain) embeds the re-targeted copy so
            # run-input and closeout identity checks keep matching the
            # resolved definition.
            expected_policy = stage_one_policy_snapshot_for_definition(
                raw_policy,
                workflow_definition_id=normalized_definition_id,
            )
        else:
            expected_policy = require_current_stage_one_policy_snapshot(raw_policy)
    except StageOneCompletionPolicyError as exc:
        raise ResearchWorkflowError(
            "stage-one completion policy is invalid",
            code="invalid_run_input",
        ) from exc
    if not isinstance(catalog_run_authorization, Mapping):
        raise ResearchWorkflowError(
            "stage-one completion policy authorization is required",
            code="catalog_run_authorization_required",
        )
    batch_scope = catalog_run_authorization.get("batchScope")
    authorized_policy = (
        batch_scope.get("stageOneCompletionPolicy")
        if isinstance(batch_scope, Mapping)
        else None
    )
    if not isinstance(authorized_policy, Mapping):
        raise ResearchWorkflowError(
            "stage-one completion policy authorization is required",
            code="catalog_run_authorization_required",
        )
    try:
        normalized_authorized_policy = stage_one_policy_snapshot_for_definition(
            authorized_policy,
            workflow_definition_id=str(expected_policy.get("workflowDefinitionId") or ""),
        )
    except StageOneCompletionPolicyError as exc:
        raise ResearchWorkflowError(
            "stage-one completion policy authorization does not match the run input",
            code="catalog_run_authorization_invalid",
        ) from exc
    if normalized_authorized_policy != expected_policy:
        raise ResearchWorkflowError(
            "stage-one completion policy authorization does not match the run input",
            code="catalog_run_authorization_invalid",
        )


def _retarget_stage_one_policy_binding(
    run_input: Mapping[str, Any],
    definition: WorkflowDefinition,
) -> Mapping[str, Any]:
    """Re-target the embedded stage-one policy at the resolved run definition.

    The tracked stage-one completion policy stays pinned to its 2.1.0
    identity (authorization scopes and historical runs keep it); a run driven
    by another registered stage-one definition (the truncated
    ``2.2.0-stage-one`` chain) embeds a re-targeted copy so the run-input
    contract and the stage-one closeout identity check keep matching the
    definition that actually drives the run.  Fail-closed: the policy must be
    the tracked current policy modulo the definition identity, and its
    closure node must exist in the resolved definition.
    """
    raw_policy = run_input.get("stageOneCompletionPolicy")
    if raw_policy is None:
        return run_input
    definition_id = f"{definition.workflowId}@{definition.schemaVersion}"
    try:
        policy = stage_one_policy_snapshot_for_definition(
            raw_policy,
            workflow_definition_id=definition_id,
        )
    except StageOneCompletionPolicyError as exc:
        raise ResearchWorkflowError(
            "stage-one completion policy is invalid",
            code="invalid_run_input",
        ) from exc
    closure_node = str(policy.get("closureNodeId") or "").strip()
    if closure_node and closure_node not in {node.nodeId for node in definition.nodes}:
        raise ResearchWorkflowError(
            "stage-one completion policy closure node is missing from the run definition",
            code="stage_one_policy_mismatch",
        )
    return {**run_input, "stageOneCompletionPolicy": policy}


def _auto_open_candidate_generation(
    run_input: Mapping[str, Any],
    *,
    created_run: Mapping[str, Any],
) -> dict[str, Any] | None:
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
        from core.research.workflow.contracts.discussion_scope import (
            WorkflowDiscussionScopeV1,
        )
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )
        from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
            authority_from_created_run,
        )

        team_id = str(run_input.get("teamId") or "").strip()
        question_id = str(run_input.get("questionId") or "").strip()
        if not team_id or not question_id:
            return None
        workflow_run_id = str(created_run.get("runId") or "").strip()
        stage_one_authority = ""
        raw_stage_one_policy = run_input.get("stageOneCompletionPolicy")
        if isinstance(raw_stage_one_policy, Mapping):
            require_current_stage_one_policy_snapshot(raw_stage_one_policy)
            stage_one_authority = (
                hypothesis_first_chain.EXPLORATORY_DRAFT_AUTHORITY
            )
        if not hypothesis_first_chain.needs_candidate_generation(
            team_id,
            question_id,
            workflow_run_id=workflow_run_id,
        ):
            return None
        discussion_scope = WorkflowDiscussionScopeV1.generation(
            teamId=team_id,
            researchProjectId=str(run_input.get("projectId") or "").strip(),
            workflowRunId=workflow_run_id,
            workflowNodeId=hypothesis_first_chain.HYPOTHESIS_DESIGN_NODE_ID,
            questionId=question_id,
        )
        opened = hypothesis_first_chain.open_candidate_generation_meeting(
            team_id,
            question_id,
            background=True,
            _model_invocation_receipt_authority=authority_from_created_run(
                run_input,
                created_run,
            ),
            _discussion_scope=discussion_scope.to_dict(),
            _candidate_authority=stage_one_authority,
        )
        return {
            "status": str(opened.get("status") or ""),
            "meetingRoundId": str(
                (opened.get("meetingRound") or {}).get("meetingRoundId") or ""
            ),
        }
    except Exception as exc:  # run fact stays; report the side effect
        return {"status": "failed", "error": str(exc), "errorType": type(exc).__name__}


def _formal_hypothesis_handoff(
    team_id: str,
    question_id: str,
    *,
    hypothesis_round_id: str,
) -> dict[str, dict[str, Any]]:
    """Freeze a complete converged-review handoff before creating a run.

    Closed hypothesis rounds and meeting artifacts are append-only authorities.
    Re-reading and validating them before the Ledger mutation makes the run
    creation fail closed: an incomplete handoff never leaves a ``created`` run
    behind, while a replay freezes the same immutable selection and evidence.
    """

    from core.research.workflow.contracts import HypothesisRound
    from core.web.services.team_workflow import hypothesis_rounds, meeting_rounds

    normalized_question_id = str(question_id or "").strip().upper()
    normalized_round_id = str(hypothesis_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchWorkflowError(
            "formal hypothesis handoff requires a round and confirmed candidate",
            code="formal_hypothesis_handoff_incomplete",
        )
    try:
        round_record = hypothesis_rounds.get_hypothesis_round(
            team_id,
            normalized_round_id,
        )["round"]
        parsed_round = HypothesisRound.from_dict(round_record)
        parsed_round.validate_complete()
    except Exception as exc:
        raise ResearchWorkflowError(
            "formal hypothesis handoff has no complete closed review round",
            code="formal_hypothesis_handoff_incomplete",
        ) from exc
    if parsed_round.question.upper() != normalized_question_id:
        raise ResearchWorkflowError(
            "formal hypothesis handoff round belongs to another question",
            code="formal_hypothesis_handoff_mismatch",
        )
    recommended_candidate_id = parsed_round.metaReview.recommendationCandidateId
    if parsed_round.metaReview.accepted:
        normalized_acceptance_kind = "meta_review"
        accepted = parsed_round.metaReview.accepted
    else:
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        accepted = any(
            str(item.get("recordKind") or "") == "human_adjudication"
            and str(item.get("questionId") or "").strip().upper()
            == normalized_question_id
            and str(item.get("hypothesisRoundId") or "").strip()
            == normalized_round_id
            and str(item.get("decision") or "").strip().lower() == "accepted"
            for item in hypothesis_first_chain._records(team_id)
        )
        normalized_acceptance_kind = "human_adjudication"
    if not accepted:
        raise ResearchWorkflowError(
            "formal hypothesis handoff has no accepted convergence decision",
            code="formal_hypothesis_handoff_incomplete",
        )
    candidate_snapshot = next(
        (
            item.to_dict()
            for item in parsed_round.candidates
            if item.candidateId == recommended_candidate_id
        ),
        None,
    )
    if candidate_snapshot is None:
        raise ResearchWorkflowError(
            "formal hypothesis handoff candidate is missing from the closed round",
            code="formal_hypothesis_handoff_incomplete",
        )

    # R2.2 direct fail-closed gate: the formal handoff never advances a
    # hypothesis whose core claims are refuted/disputed (or unevaluable),
    # even when the convergence authority came from the meta review instead
    # of a human adjudication (which the chain gates itself).  The chain's
    # gate helper runs ``evaluate_claim_belief_gate`` and raises
    # ``ClaimBeliefGateBlockedError`` with structured blockers.
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
    )

    hypothesis_first_chain._assert_claim_belief_gate_allows(
        team_id,
        normalized_question_id,
        recommended_candidate_id,
        stage="formal_run_handoff",
    )

    refs_by_kind: dict[str, list[str]] = {
        "meeting_round": [],
        "meeting_digest": [],
        "decision_record": [],
    }
    for ref in parsed_round.meetingRefs:
        refs_by_kind.setdefault(ref.kind, []).append(ref.id)
    if not all(refs_by_kind.get(kind) for kind in refs_by_kind):
        raise ResearchWorkflowError(
            "formal hypothesis handoff is missing review evidence references",
            code="formal_hypothesis_handoff_incomplete",
        )

    digest_records = meeting_rounds._read_jsonl(meeting_rounds._digests_path(team_id))
    decision_records = meeting_rounds._read_jsonl(
        meeting_rounds._decisions_path(team_id)
    )
    selection_ids: set[str] = set()
    for meeting_id in refs_by_kind["meeting_round"]:
        try:
            meeting = meeting_rounds.get_meeting_round(team_id, meeting_id)[
                "meetingRound"
            ]
        except Exception as exc:
            raise ResearchWorkflowError(
                "formal hypothesis handoff review meeting does not resolve",
                code="formal_hypothesis_handoff_incomplete",
            ) from exc
        if (
            str(meeting.get("meetingType") or "") != "hypothesis_review"
            or str(meeting.get("status") or "") != "closed"
            or str(meeting.get("question") or "").strip().upper()
            != normalized_question_id
        ):
            raise ResearchWorkflowError(
                "formal hypothesis handoff review meeting is not closed for this question",
                code="formal_hypothesis_handoff_incomplete",
            )
        digest_id = str(meeting.get("digestId") or "").strip()
        decision_ids = [
            str(item or "").strip()
            for item in list(meeting.get("decisionRefs") or [])
            if str(item or "").strip()
        ]
        if (
            digest_id not in refs_by_kind["meeting_digest"]
            or any(item not in refs_by_kind["decision_record"] for item in decision_ids)
            or meeting_rounds._latest_by_id(digest_records, "digestId", digest_id)
            is None
            or any(
                meeting_rounds._latest_by_id(
                    decision_records,
                    "decisionId",
                    decision_id,
                )
                is None
                for decision_id in decision_ids
            )
        ):
            raise ResearchWorkflowError(
                "formal hypothesis handoff review evidence does not resolve",
                code="formal_hypothesis_handoff_incomplete",
            )
        for ref in list(meeting.get("inputArtifactRefs") or []):
            text = str(ref or "").strip()
            if text.startswith("hypothesis_selection:"):
                selection_id = text.split(":", 1)[1].strip()
                if selection_id:
                    selection_ids.add(selection_id)
    if len(selection_ids) != 1:
        raise ResearchWorkflowError(
            "formal hypothesis handoff does not resolve one review selection",
            code="formal_hypothesis_handoff_incomplete",
        )
    selection_id = next(iter(selection_ids))
    evidence_refs = [
        f"hypothesis_round:{parsed_round.roundId}",
        *[
            f"{kind}:{ref_id}"
            for kind in ("meeting_round", "meeting_digest", "decision_record")
            for ref_id in refs_by_kind[kind]
        ],
    ]
    return {
        "hypothesisSelection": {
            "schemaVersion": 1,
            "selectionId": selection_id,
            "selectedCandidateIds": [recommended_candidate_id],
            "candidateSnapshots": [candidate_snapshot],
            "sourceRoundId": parsed_round.roundId,
            "sourceScopeHash": parsed_round.scopeHash,
        },
        "hypothesisConvergenceHandoff": {
            "schemaVersion": 1,
            "roundId": parsed_round.roundId,
            "selectionId": selection_id,
            "confirmedCandidateId": recommended_candidate_id,
            "acceptedByMetaReview": parsed_round.metaReview.accepted,
            "acceptanceKind": normalized_acceptance_kind,
            "metaReviewId": parsed_round.metaReview.metaReviewId,
            "scopeHash": parsed_round.scopeHash,
            "evidenceRefs": evidence_refs,
        },
    }


def create_question_run(
    workflow_id: str,
    *,
    team_id: str,
    question_id: str,
    safety_limits: Mapping[str, Any],
    idempotency_key: str,
    catalog_run_authorization: Mapping[str, Any] | None = None,
    formal_hypothesis_round_id: str = "",
) -> dict[str, Any]:
    if workflow_id != CHALLENGE_CUP_WORKFLOW_ID:
        raise ResearchWorkflowError(f"Unknown workflowId: {workflow_id}", code="unknown_workflow")
    # Check before resolving the catalog/project or opening the Ledger: those
    # steps can persist Challenge Cup state and must not start after a governed
    # reset has acquired its maintenance fence.
    assert_writes_allowed(team_id, operation="question_launch")
    get_write_store()
    try:
        run_input = build_question_run_input(
            team_id,
            question_id=question_id,
            safety_limits=safety_limits,
        )
    except QuestionLaunchError as exc:
        raise ResearchWorkflowError(str(exc), code=exc.code) from exc
    if not isinstance(run_input.get("researchScopeEnvelope"), Mapping) or not isinstance(
        run_input.get("catalogScope"), Mapping
    ):
        raise ResearchWorkflowError(
            "new Challenge runs require server-derived researchScopeEnvelope and catalogScope",
            code="invalid_run_input",
        )
    if formal_hypothesis_round_id:
        run_input = {
            **run_input,
            **_formal_hypothesis_handoff(
                team_id,
                question_id,
                hypothesis_round_id=formal_hypothesis_round_id,
            ),
        }
    created = create_run(
        workflow_id,
        run_input=run_input,
        idempotency_key=idempotency_key,
        catalog_run_authorization=catalog_run_authorization,
        workflow_definition=_question_run_creation_definition(),
    )
    generation = _auto_open_candidate_generation(run_input, created_run=created)
    if generation is not None:
        created = {**created, "candidateGeneration": generation}
    return created


def _question_run_creation_definition() -> WorkflowDefinition:
    """The pinned definition for NEW question runs.

    Product decision (挑战杯假说链第一阶段): the hypothesis chain stops at
    ``hypothesis_design``, so question runs are created against the
    registered stage-one truncated definition
    (``challenge-cup-research@2.2.0-stage-one``) instead of the full
    2.1.0/3.0.0 chains.  Historical runs keep their own pinned registry
    identity.
    """
    from core.research.workflow.stage_one_definition import (
        build_stage_one_workflow_definition,
    )

    return build_stage_one_workflow_definition()


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


def _ensure_existing_run_identity(run: Any, run_input: Mapping[str, Any]) -> None:
    """Keep an idempotency key bound to its original team/question identity."""

    expected_team_id = str(run_input.get("teamId") or "").strip()
    expected_question_id = str(run_input.get("questionId") or "").strip().upper()
    if (
        str(run.team_id or "").strip() != expected_team_id
        or str(run.question_id or "").strip().upper() != expected_question_id
    ):
        raise ResearchWorkflowError(
            "idempotencyKey was already used with different run input",
            code="idempotency_conflict",
        )


def _catalog_authorization_payload(record: Any) -> dict[str, Any]:
    from .catalog_run_authorization import authorization_to_dict

    return authorization_to_dict(record)


def _catalog_authorization_events(source: Any, run_id: str) -> list[Any]:
    """Return every authorization marker, including a deterministic bad marker."""

    event_id = f"evt-catalog-run-authorized-{run_id}"
    return [
        event
        for event in source.list_events(run_id)
        if event.event_type == "catalog_run_authorized" or event.event_id == event_id
    ]


def _raise_catalog_authorization_replay_mismatch(message: str) -> None:
    raise ResearchWorkflowError(
        message,
        code="catalog_run_authorization_replay_mismatch",
    )


def _validate_catalog_authorization_event(
    source: Any,
    *,
    run_id: str,
    idempotency_key: str,
    expected_payload: Mapping[str, Any],
) -> None:
    """Require one complete, structurally valid authorization event."""

    events = _catalog_authorization_events(source, run_id)
    if len(events) != 1:
        _raise_catalog_authorization_replay_mismatch(
            "existing run does not have exactly one catalog authorization event"
        )
    event = events[0]
    event_id = f"evt-catalog-run-authorized-{run_id}"
    if (
        event.run_id != run_id
        or event.event_id != event_id
        or event.sequence != 2
        or event.event_type != "catalog_run_authorized"
        or event.run_version != 1
        or event.correlation_id != (idempotency_key or run_id)
        or event.causation_id != f"evt-created-{run_id}"
        or event.occurred_at_ms <= 0
    ):
        _raise_catalog_authorization_replay_mismatch(
            "existing run has a malformed catalog authorization event"
        )
    try:
        actor = json.loads(event.actor_json)
        payload = json.loads(event.payload_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        _raise_catalog_authorization_replay_mismatch(
            "existing run has an unreadable catalog authorization event"
        )
    if actor != {"actorType": "system", "actorId": "catalog-run-authorization"}:
        _raise_catalog_authorization_replay_mismatch(
            "existing run has an invalid catalog authorization event actor"
        )
    if not isinstance(payload, Mapping) or dict(payload) != dict(expected_payload):
        _raise_catalog_authorization_replay_mismatch(
            "catalog run authorization does not match the existing run"
        )


def _validate_existing_run_authorization_replay(
    store_or_repository: Any,
    *,
    run_id: str,
    idempotency_key: str,
    catalog_run_authorization: Mapping[str, Any] | None,
    team_id: str,
    question_id: str,
) -> None:
    """Apply the same authorization decision in fast and writer paths."""

    existing_events = _catalog_authorization_events(store_or_repository, run_id)
    if catalog_run_authorization is None:
        if existing_events:
            _raise_catalog_authorization_replay_mismatch(
                "catalog run authorization is required to replay this run"
            )
        return
    if not isinstance(catalog_run_authorization, Mapping):
        _raise_catalog_authorization_replay_mismatch(
            "catalog run authorization is missing or invalid"
        )
    if len(existing_events) != 1:
        _raise_catalog_authorization_replay_mismatch(
            "catalog run authorization does not match the existing run"
        )
    try:
        authorization_record = _load_catalog_run_authorization(
            store_or_repository,
            catalog_run_authorization,
            team_id=team_id,
            question_id=question_id,
        )
    except ResearchWorkflowError as exc:
        _raise_catalog_authorization_replay_mismatch(str(exc))
    _validate_catalog_authorization_event(
        store_or_repository,
        run_id=run_id,
        idempotency_key=idempotency_key,
        expected_payload=_catalog_authorization_payload(authorization_record),
    )


def _load_catalog_run_authorization(
    store: Any,
    payload: Mapping[str, Any],
    *,
    team_id: str,
    question_id: str,
) -> Any:
    from .catalog_run_authorization import validate_catalog_run_authorization

    authorization_id = str(payload.get("authorizationId") or "").strip()
    record = store.get_catalog_run_authorization(authorization_id)
    require_model_policy = isinstance(payload.get("batchScope"), Mapping) and (
        "modelPolicy" in payload.get("batchScope", {})
    )
    require_stage_one_policy = isinstance(payload.get("batchScope"), Mapping) and (
        "stageOneCompletionPolicy" in payload.get("batchScope", {})
    )
    if record is None or not validate_catalog_run_authorization(
        record,
        team_id=team_id,
        plan_id=str(payload.get("planId") or ""),
        scope_hash=str(payload.get("scopeHash") or ""),
        readiness_sha256=str(payload.get("readinessReportSha256") or ""),
        question_id=question_id,
        require_model_policy=require_model_policy,
        require_stage_one_policy=require_stage_one_policy,
    ):
        raise ResearchWorkflowError(
            "catalog run authorization is missing or invalid",
            code="catalog_run_authorization_invalid",
        )
    expected_payload = _catalog_authorization_payload(record)
    if dict(payload) != expected_payload:
        raise ResearchWorkflowError(
            "catalog run authorization is missing or invalid",
            code="catalog_run_authorization_invalid",
        )
    return record


def create_run(
    workflow_id: str,
    *,
    run_input: Mapping[str, Any],
    idempotency_key: str,
    binding_layers: AgentBindingLayers | None = None,
    catalog_run_authorization: Mapping[str, Any] | None = None,
    workflow_definition: WorkflowDefinition | None = None,
) -> dict[str, Any]:
    store = get_write_store()
    # Register-or-resolve: the definition driving this run is pinned by its
    # (workflowId, workflowVersionId, structureHash) identity in the registry
    # before any checkpoint or ledger write happens.  Question-run callers
    # pass the stage-one truncated definition explicitly; the default keeps
    # the rollout-mode behavior (off/shadow → frozen 2.1.0, on → main-flow
    # 3.0.0).  Historical runs are always read through their own pinned
    # version identity, so this choice never re-shapes an in-flight run.
    if workflow_definition is not None:
        definition = workflow_definition
        identity = register_or_resolve(definition)
    else:
        from .knowledge_rollout import creation_workflow_definition

        definition, identity = creation_workflow_definition()
    workflow_version_id = identity.workflowVersionId
    definition_id = f"{definition.workflowId}@{definition.schemaVersion}"
    # Fingerprint the request AS RECEIVED (tracked policy identity) so an
    # idempotent replay of a pre-truncation creation stays compatible; the
    # re-targeted copy only shapes the frozen snapshot below.
    fingerprints = _create_request_fingerprints(run_input)
    fingerprint = fingerprints[0]
    run_input = _retarget_stage_one_policy_binding(run_input, definition)
    _require_stage_one_authorization_binding(
        run_input,
        catalog_run_authorization,
        workflow_definition_id=definition_id,
    )
    run_id = run_id_for_create(workflow_id, idempotency_key)
    existing = store.get_run(run_id)
    if existing is not None:
        _ensure_create_fingerprint(existing, fingerprints)
        _ensure_existing_run_identity(existing, run_input)
        _validate_existing_run_authorization_replay(
            store,
            run_id=run_id,
            idempotency_key=idempotency_key,
            catalog_run_authorization=catalog_run_authorization,
            team_id=existing.team_id,
            question_id=existing.question_id,
        )
        return catalog_dict_from_run(existing)

    team_id = str(run_input.get("teamId") or "").strip()
    binding_root = research_workflow_data_root() / "runs"
    layers = binding_layers or WorkflowBindingConfigStore(binding_root).load(workflow_id, team_id)
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
    checkpoint_id = prepare_initial_checkpoint(
        checkpoint_path,
        thread_id,
        definition=definition,
    )
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
    authorization_record = None
    if catalog_run_authorization is not None:
        if not isinstance(catalog_run_authorization, Mapping):
            raise ResearchWorkflowError(
                "catalog run authorization is missing or invalid",
                code="catalog_run_authorization_invalid",
            )
        authorization_record = _load_catalog_run_authorization(
            store,
            catalog_run_authorization,
            team_id=input_snapshot.teamId,
            question_id=input_snapshot.questionId,
        )
    auth_payload = None
    if authorization_record is not None:
        auth_payload = _catalog_authorization_payload(authorization_record)
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
        last_event_sequence=2 if auth_payload is not None else 1,
        input_snapshot_json=json.dumps(snapshot_dict, ensure_ascii=False),
        input_snapshot_hash=input_snapshot.snapshotHash,
        safety_limits_json=json.dumps(dict(run_input.get("safetyLimits") or {}), ensure_ascii=False),
        binding_snapshot_set_id=binding_set_id,
        active_node_id=first_agent,
        parent_run_id=None,
        forked_from_checkpoint_id=None,
        structure_hash=definition.structureHash,
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
        payload_json=json.dumps(
            {
                "inputSnapshotHash": input_snapshot.snapshotHash,
                **(
                    {"catalogRunAuthorization": auth_payload}
                    if auth_payload is not None
                    else {}
                ),
            }
        ),
        occurred_at_ms=now_ms,
    )
    authorization_event = (
        EventRecord(
            run_id=run_id,
            sequence=2,
            event_id=f"evt-catalog-run-authorized-{run_id}",
            run_version=1,
            event_type="catalog_run_authorized",
            actor_json=json.dumps(
                {"actorType": "system", "actorId": "catalog-run-authorization"}
            ),
            correlation_id=idempotency_key or run_id,
            causation_id=event.event_id,
            payload_json=json.dumps(auth_payload, ensure_ascii=False),
            occurred_at_ms=now_ms,
        )
        if auth_payload is not None
        else None
    )

    def mutate(uow) -> None:
        # Concurrent create with the same key: the single writer serializes
        # mutations, so the later request sees the winner's row here and
        # replays idempotently instead of hitting the run_id primary key.
        existing_in_tx = uow.repository.get_run(run_id)
        if existing_in_tx is not None:
            _ensure_create_fingerprint(existing_in_tx, fingerprints)
            _ensure_existing_run_identity(existing_in_tx, run_input)
            _validate_existing_run_authorization_replay(
                uow.repository,
                run_id=run_id,
                idempotency_key=idempotency_key,
                catalog_run_authorization=catalog_run_authorization,
                team_id=existing_in_tx.team_id,
                question_id=existing_in_tx.question_id,
            )
            return
        uow.repository.insert_run(record)
        uow.repository.insert_event(event)
        if authorization_event is not None:
            uow.repository.insert_event(authorization_event)

    store.submit(mutate, force_flush=True).result(timeout=15)
    created = store.get_run(run_id)
    if created is not None:
        _ensure_create_fingerprint(created, fingerprints)
        _ensure_existing_run_identity(created, run_input)
        if auth_payload is not None:
            _validate_catalog_authorization_event(
                store,
                run_id=run_id,
                idempotency_key=idempotency_key,
                expected_payload=auth_payload,
            )
        elif _catalog_authorization_events(store, run_id):
            _raise_catalog_authorization_replay_mismatch(
                "unexpected catalog authorization event on an unauthorized run"
            )
    if created is None:
        raise ResearchWorkflowError("created run was not readable", code="workflow_ledger_unavailable")
    return catalog_dict_from_run(created)
