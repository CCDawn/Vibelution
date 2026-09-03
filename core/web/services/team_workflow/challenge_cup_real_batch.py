"""Team-scoped Challenge Cup real catalog batch service.

Owns team storage resolution and persistence for the real-question batch
surface: the ``CatalogExecutionState`` checkpoints plus the run-reference
sidecar envelope (run ids, start attempts, awaiting-approval index, circuit
breaker counters). The pure planning contracts live in
``core.research.competition.real_control_batch``; run creation, START_NODE
dispatch, run status reads and approved-output reads are injectable callables
so tests never touch the formal runtime.

Authorization is fail-closed: a current readiness boundary, explicit client
confirmation, and a durable ``CatalogRunAuthorization`` for the exact plan
scope/report hash are all required. Each progressive gate (G5/G12/G125) also
requires the previous gate's batch to be fully succeeded before it may start.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    CatalogExecutionState,
    QuestionStatus,
)
from core.research.competition.question_result_package import (
    QuestionResultPackage,
    QuestionResultPackageError,
)
from core.research.competition.real_control_batch import (
    DEFAULT_REAL_FAILURE_BUDGET,
    MAX_REAL_START_ATTEMPTS,
    PREVIOUS_GATE,
    PREVIOUS_GATE_PLAN_ID,
    RealBatchError,
    circuit_breaker_tripped,
    frozen_execution_policy,
    new_real_batch_state,
    project_real_batch_state,
    real_plan,
    validate_real_batch_plan,
    validate_real_concurrency,
    validate_real_failure_budget,
)
from core.research.competition.result_set import CatalogScope, QuestionResult
from core.research.competition.stage_one_completion_policy import (
    STAGE_ONE_POLICY_QUESTION_IDS,
    STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID,
    stage_one_policy_snapshot_for,
)
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services import team_service
from core.web.services.team_workflow.challenge_cup_dev_controls import (
    get_challenge_cup_dev_control_snapshot,
)
from core.web.services.team_workflow.research_projects import formal_team_workspace_root
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    CatalogRunAuthorizationError,
    authorization_to_dict,
    authorized_model_policy_sha256,
    find_catalog_run_authorization,
    readiness_hash_from_snapshot,
    resolve_catalog_model_policy,
)
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    record_catalog_run_authorization as _record_catalog_run_authorization,
)
from core.web.services.team_workflow.research_runtime.budget_contract import (
    default_safety_limits,
)

CONTROLS_DIRNAME = "challenge_cup_real_batch"
BATCHES_DIRNAME = "batches"
ENVELOPE_SCHEMA_VERSION = 1
AWAITING_APPROVAL_BLOCKED_PREFIX = "awaiting_human_approval"
CANCELLED_BLOCKED_REASON = "cancelled_by_operator"

_AUTHORIZATION_BINDING_FIELDS = (
    "authorizationId",
    "teamId",
    "planId",
    "scopeHash",
    "readinessReportSha256",
    "recordHash",
)

_store_lock = threading.Lock()

QuestionRunLauncher = Callable[[str, str, str], dict[str, Any]]
StartDispatcher = Callable[[str, dict[str, Any], str, str], dict[str, Any]]
RunStatusReader = Callable[[str], dict[str, dict[str, Any]]]
ApprovedOutputReader = Callable[[str, str], dict[str, Any] | None]


class ChallengeCupRealBatchError(ValueError):
    """A real catalog batch service contract was violated."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class RealBatchStorageError(RuntimeError):
    """The real batch envelope could not be read or persisted."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_team_id(team_id: str) -> str:
    detail = team_service.get_team(team_id)
    canonical = str(detail.get("teamId") or detail.get("id") or "").strip()
    return canonical or str(team_id).strip()


def _batches_root(team_id: str) -> Path:
    return formal_team_workspace_root(team_id) / CONTROLS_DIRNAME / BATCHES_DIRNAME


def _envelope_path(team_id: str, plan_id: str) -> Path:
    return _batches_root(team_id) / f"{plan_id}.json"


def _default_safety_limits() -> dict[str, Any]:
    return default_safety_limits()


def _default_question_run_launcher(
    team_id: str,
    question_id: str,
    idempotency_key: str,
    *,
    authorization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one real question workflow run (ledger only; no dispatch here)."""
    from core.web.services.team_workflow.research_runtime.run_creation import (
        create_question_run,
    )

    return create_question_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id=team_id,
        question_id=question_id,
        safety_limits=_default_safety_limits(),
        idempotency_key=idempotency_key,
        catalog_run_authorization=authorization,
    )


def _default_start_dispatcher(
    team_id: str,
    run: dict[str, Any],
    node_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Submit the START_NODE command that drives the created run."""
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )
    from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
        get_command_service,
    )
    from core.web.services.team_workflow.research_runtime.ids import new_id

    receipt = get_command_service().submit(
        CommandRequest(
            command_id=new_id("cmd"),
            run_id=str(run.get("runId") or ""),
            team_id=team_id,
            command=WorkflowCommandKind.START_NODE,
            node_id=node_id or None,
            expected_run_version=int(run.get("runVersion") or 1),
            idempotency_key=idempotency_key,
            payload={},
            requested_by=ActorRef("system", "challenge-cup-real-batch"),
            requested_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
    )
    return {"commandId": receipt.command_id, "status": receipt.status}


def _default_run_status_reader(team_id: str) -> dict[str, dict[str, Any]]:
    from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
        get_query_service,
    )

    runs = get_query_service().list_runs(
        team_id=team_id,
        workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
    )["runs"]
    return {
        str(run.get("runId") or ""): run
        for run in runs
        if isinstance(run, dict) and run.get("runId")
    }


def _default_approved_output_reader(
    team_id: str,
    question_id: str,
) -> dict[str, Any] | None:
    """Return the formally approved v2 output detail for one question, or None."""
    from core.web.services.team_workflow.challenge_question_runs import (
        challenge_question_run_summary,
        get_challenge_question_run_detail,
    )
    from core.web.services.team_workflow.research_runtime.question_launch import (
        _formal_record_eligible,
    )

    summary = challenge_question_run_summary(team_id)
    completed = [
        value
        for value in summary.get("completedQuestionResults") or []
        if isinstance(value, dict)
        and str(value.get("questionId") or "").upper() == question_id
        and _formal_record_eligible(value)
    ]
    if not completed:
        return None
    run_id = str(completed[0].get("runId") or "").strip()
    if not run_id:
        return None
    detail = get_challenge_question_run_detail(team_id, question_id, run_id=run_id)
    record = detail.get("record") if isinstance(detail.get("record"), dict) else {}
    output = detail.get("output") if isinstance(detail.get("output"), dict) else {}
    review = output.get("review") if isinstance(output.get("review"), dict) else {}
    submission = (
        output.get("submission") if isinstance(output.get("submission"), dict) else {}
    )
    if (
        not _formal_record_eligible(record)
        or output.get("schema_version") != 2
        or review.get("human_review_status") != "passed"
        or submission.get("eligible") is not True
    ):
        return None
    artifact = detail.get("artifact") if isinstance(detail.get("artifact"), dict) else {}
    identity = output.get("identity") if isinstance(output.get("identity"), dict) else {}
    catalog_id = str(identity.get("catalog_id") or "").strip()
    artifact_sha256 = str(artifact.get("sha256") or "").strip()
    if not catalog_id or not artifact_sha256:
        return None
    return {
        "reviewRunId": run_id,
        "catalogId": catalog_id,
        "artifactSha256": artifact_sha256,
        "resultPackage": detail.get("resultPackage"),
        "officialModelCall": record.get("validation", {})
        .get("officialModelCall")
        is True,
    }


def _validated_approved_package(
    state: CatalogExecutionState,
    question_id: str,
    expected_run_id: str,
    approved: dict[str, Any],
    *,
    expected_model_policy_sha256: str,
) -> QuestionResultPackage:
    raw_package = approved.get("resultPackage")
    if not isinstance(raw_package, Mapping):
        raise ChallengeCupRealBatchError(
            f"Approved output has no canonical result package: {question_id}.",
            code="result_package_invalid",
        )
    try:
        package = QuestionResultPackage.from_dict(
            dict(raw_package),
            expected_model_policy_sha256=expected_model_policy_sha256,
        )
    except (QuestionResultPackageError, TypeError, KeyError) as exc:
        raise ChallengeCupRealBatchError(
            f"Approved output canonical result package is invalid: {question_id}: {exc}",
            code="result_package_invalid",
        ) from exc
    if package.question_id != question_id:
        raise ChallengeCupRealBatchError(
            f"Approved output package question does not match {question_id}.",
            code="result_package_invalid",
        )
    if package.run_id != expected_run_id:
        raise ChallengeCupRealBatchError(
            f"Approved output package run does not match {expected_run_id}: {question_id}.",
            code="result_package_invalid",
        )
    if package.scope.to_dict() != state.scope.to_dict():
        raise ChallengeCupRealBatchError(
            f"Approved output package scope does not match the real batch: {question_id}.",
            code="result_package_invalid",
        )
    result = QuestionResult.from_package(package)
    if result.submission_eligible is not True or result.receipt_complete is not True:
        raise ChallengeCupRealBatchError(
            f"Approved output package is not submission-approved: {question_id}.",
            code="result_package_invalid",
        )
    return package


def _validated_seed_package(
    state: CatalogExecutionState,
    result: QuestionResult,
    *,
    expected_model_policy_sha256: str,
) -> QuestionResultPackage:
    """Restore one already-trusted in-memory package before any target mutation."""

    snapshot = result.package_snapshot
    if snapshot is None:
        raise CatalogExecutionError(
            f"Previous gate package result has no snapshot: {result.question_id}."
        )
    try:
        package = QuestionResultPackage.from_dict(
            snapshot,
            expected_model_policy_sha256=expected_model_policy_sha256,
        )
    except QuestionResultPackageError as exc:
        raise CatalogExecutionError(
            f"Previous gate package is not canonical: {result.question_id}: {exc}"
        ) from exc

    canonical = package.to_dict()
    expected_scope = state.scope.to_dict()
    if package.question_id != result.question_id:
        raise CatalogExecutionError(
            "Previous gate package question does not match its result locator."
        )
    if package.scope.to_dict() != expected_scope:
        raise CatalogExecutionError(
            f"Previous gate package scope does not match the target catalog: "
            f"{result.question_id}."
        )
    if result.locator != state.scope.locator_for(result.question_id):
        raise CatalogExecutionError(
            f"Previous gate result locator does not match the full target catalog "
            f"scope: {result.question_id}."
        )
    if snapshot != canonical or QuestionResult.from_package(package) != result:
        raise CatalogExecutionError(
            f"Previous gate package projection changed canonical content: "
            f"{result.question_id}."
        )
    if (
        package.result_classification.get("status") != "approved"
        or package.selection.get("human_gate", {}).get("decision") != "approved"
        or package.research_plan.get("human_gate", {}).get("decision") != "approved"
        or result.submission_eligible is not True
        or result.receipt_complete is not True
    ):
        raise CatalogExecutionError(
            f"Previous gate package is not submission-approved: {result.question_id}."
        )
    return package


def _same_seed_result(
    existing: QuestionResult | None,
    incoming_package: QuestionResultPackage,
) -> bool:
    if existing is None:
        return False
    existing_snapshot = existing.package_snapshot
    return (
        existing_snapshot is not None
        and existing_snapshot == incoming_package.to_dict()
        and existing_snapshot.get("canonical_sha256")
        == incoming_package.canonical_sha256
    )


def _seed_from_previous_gates(
    team_id: str,
    state: CatalogExecutionState,
    *,
    expected_model_policy_sha256: str,
) -> int:
    """Seed already-approved results from earlier gate batches.

    Progressive gates are cumulative (G5 includes G1's questions); an approved
    result from an earlier gate carries forward instead of being re-run.
    """
    candidates: dict[
        str,
        tuple[QuestionResult, QuestionResultPackage],
    ] = {}
    gate_id = state.plan.gate_id
    chain: list[str] = []
    while gate_id in PREVIOUS_GATE:
        prior_plan = PREVIOUS_GATE_PLAN_ID[gate_id]
        chain.append(prior_plan)
        gate_id = PREVIOUS_GATE[gate_id]
    for prior_plan in chain:
        envelope = _load_envelope(team_id, prior_plan)
        if envelope is None:
            continue
        prior_state = _state_of(envelope)
        for result in prior_state.succeeded_results():
            try:
                target_status = state.status(result.question_id)
            except CatalogExecutionError as exc:
                raise CatalogExecutionError(
                    f"Previous gate result is outside the cumulative target plan: "
                    f"{result.question_id}."
                ) from exc

            if not result.is_package_backed:
                raise CatalogExecutionError(
                    f"Previous gate result has no canonical package: {result.question_id}."
                )
            package = _validated_seed_package(
                state,
                result,
                expected_model_policy_sha256=expected_model_policy_sha256,
            )

            if target_status is not QuestionStatus.PENDING:
                if target_status is QuestionStatus.SUCCEEDED and not _same_seed_result(
                    state.result_for(result.question_id),
                    package,
                ):
                    raise CatalogExecutionError(
                        f"Target already succeeded with a different canonical package: "
                        f"{result.question_id}."
                    )
                continue

            existing_candidate = candidates.get(result.question_id)
            if existing_candidate is not None:
                if not _same_seed_result(
                    existing_candidate[0],
                    package,
                ):
                    raise CatalogExecutionError(
                        f"Previous gates contain different canonical packages for "
                        f"{result.question_id}."
                    )
                continue
            candidates[result.question_id] = (result, package)

    seeded = 0
    for result, package in candidates.values():
        state.record_package(package)
        seeded += 1
    return seeded


def _durable_authorization_record(
    bound: Mapping[str, Any] | None,
    *,
    team_id: str,
    plan_id: str,
):
    """Restore and compare the exact durable authorization before trusting it."""

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    if not isinstance(bound, Mapping) or not normalized_team or not normalized_plan:
        raise CatalogRunAuthorizationError(
            "real batch has no complete durable catalog authorization"
        )
    scope = bound.get("batchScope")
    readiness_hash = str(bound.get("readinessReportSha256") or "").strip()
    if (
        str(bound.get("teamId") or "").strip() != normalized_team
        or str(bound.get("planId") or "").strip() != normalized_plan
        or not isinstance(scope, Mapping)
        or not readiness_hash
    ):
        raise CatalogRunAuthorizationError(
            "real batch has an incomplete durable catalog authorization"
        )
    authorization = find_catalog_run_authorization(
        normalized_team,
        plan_id=normalized_plan,
        batch_scope=scope,
        readiness_report_sha256_value=readiness_hash,
        require_model_policy=True,
    )
    if authorization is None:
        raise CatalogRunAuthorizationError(
            "real batch durable catalog authorization is stale or invalid"
        )
    durable = authorization_to_dict(authorization)
    if any(
        str(bound.get(field) or "").strip()
        != str(durable.get(field) or "").strip()
        for field in _AUTHORIZATION_BINDING_FIELDS
    ):
        raise CatalogRunAuthorizationError(
            "real batch durable catalog authorization binding is tampered"
        )
    if bound.get("batchScope") != durable.get("batchScope"):
        raise CatalogRunAuthorizationError(
            "real batch durable catalog authorization scope is tampered"
        )
    return authorization


def _new_envelope(
    team_id: str,
    plan_id: str,
    *,
    concurrency: int,
    failure_budget: int,
    authorization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    durable_authorization = _durable_authorization_record(
        authorization,
        team_id=team_id,
        plan_id=plan_id,
    )
    durable_binding = authorization_to_dict(durable_authorization)
    expected_policy_sha256 = authorized_model_policy_sha256(durable_authorization)
    state = new_real_batch_state(plan_id)
    _seed_from_previous_gates(
        team_id,
        state,
        expected_model_policy_sha256=expected_policy_sha256,
    )
    return {
        "schemaVersion": ENVELOPE_SCHEMA_VERSION,
        "kind": "challenge_cup_real_batch",
        "teamId": team_id,
        "planId": plan_id,
        "gateId": state.plan.gate_id,
        "checkpoint": state.to_checkpoint(),
        "runRefs": {},
        "awaitingApproval": {},
        "concurrency": concurrency,
        "failureBudget": failure_budget,
        "consecutiveFailures": 0,
        "cancelled": False,
        "catalogRunAuthorization": durable_binding,
        "createdAt": _utc_now(),
        "updatedAt": _utc_now(),
    }


def _load_envelope(team_id: str, plan_id: str) -> dict[str, Any] | None:
    path = _envelope_path(team_id, plan_id)
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RealBatchStorageError(f"The real batch envelope is unreadable: {exc}") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("schemaVersion") != ENVELOPE_SCHEMA_VERSION
        or envelope.get("planId") != plan_id
    ):
        raise RealBatchStorageError(
            f"The real batch envelope for {plan_id} is malformed or drifted."
        )
    return envelope


def _save_envelope(team_id: str, envelope: dict[str, Any]) -> None:
    path = _envelope_path(team_id, str(envelope.get("planId")))
    envelope["updatedAt"] = _utc_now()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, envelope)
    except OSError as exc:
        raise RealBatchStorageError(f"The real batch envelope could not be persisted: {exc}") from exc


def _state_of(envelope: dict[str, Any]) -> CatalogExecutionState:
    try:
        bound = envelope.get("catalogRunAuthorization")
        authorization = _durable_authorization_record(
            bound,
            team_id=str(envelope.get("teamId") or "").strip(),
            plan_id=str(envelope.get("planId") or "").strip(),
        )
        expected_policy_sha256 = authorized_model_policy_sha256(authorization)
        return CatalogExecutionState.from_checkpoint(
            envelope["checkpoint"],
            expected_model_policy_sha256=expected_policy_sha256,
        )
    except (KeyError, CatalogExecutionError, CatalogRunAuthorizationError) as exc:
        raise RealBatchStorageError(
            f"The real batch checkpoint is malformed: {exc}"
        ) from exc


def get_real_batch_catalog_state(
    team_id: str,
    *,
    plan_id: str = "real-125",
) -> tuple[CatalogExecutionState, str] | None:
    """Load one durable real-batch state and its authorized model policy hash.

    This is the read-only bridge for catalog projections.  It deliberately
    reuses the same envelope loader and ``_state_of`` validation as the real
    batch lifecycle, so a checkpoint is never projected without revalidating
    its durable authorization and canonical model-policy snapshot.  A missing
    envelope is represented as ``None``; malformed storage/authentication
    raises ``RealBatchStorageError`` so callers can fail closed.
    """

    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    with _store_lock:
        envelope = _load_envelope(normalized_team, normalized_plan)
        if envelope is None:
            return None
        state = _state_of(envelope)
        canonical_plan = real_plan(normalized_plan)
        if (
            state.plan.plan_id != canonical_plan.plan_id
            or state.plan.gate_id != canonical_plan.gate_id
            or state.plan.question_ids != canonical_plan.question_ids
            or state.scope != CatalogScope.from_tracked_resources()
        ):
            raise RealBatchStorageError(
                "The real batch checkpoint is not the canonical formal catalog plan."
            )
        try:
            authorization = _durable_authorization_record(
                envelope.get("catalogRunAuthorization"),
                team_id=normalized_team,
                plan_id=normalized_plan,
            )
            policy_sha256 = authorized_model_policy_sha256(authorization)
        except CatalogRunAuthorizationError as exc:
            raise RealBatchStorageError(
                f"The real batch durable authorization is invalid: {exc}"
            ) from exc
    return state, policy_sha256


def _platform_snapshot_allows_real_batch(snapshot: Mapping[str, Any]) -> bool:
    """Recognize the current readiness boundary without owning its schema.

    The legacy DEV control surface projects ``RESEARCH_AUTHORIZATION_REQUIRED``.
    The real-batch service accepts only that exact action.  The durable approval
    record below remains mandatory as a separate authorization proof.
    """

    return (
        str(snapshot.get("nextLegalAction") or "").strip()
        == "RESEARCH_AUTHORIZATION_REQUIRED"
    )


def _readiness_evidence_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Resolve the exact current readiness hash used by authorization lookup."""
    return readiness_hash_from_snapshot(snapshot)


def _batch_scope(team_id: str, plan_id: str) -> dict[str, Any]:
    plan = real_plan(plan_id)
    model_policy = resolve_catalog_model_policy(team_id)
    scope = {
        "planId": str(plan_id),
        "gateId": str(plan.gate_id),
        "questionIds": [str(question_id) for question_id in plan.question_ids],
        "modelPolicy": model_policy,
    }
    if scope["questionIds"] and set(scope["questionIds"]) <= set(
        STAGE_ONE_POLICY_QUESTION_IDS
    ):
        snapshot = stage_one_policy_snapshot_for(
            STAGE_ONE_POLICY_QUESTION_IDS[0],
            STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID,
        )
        if snapshot is not None:
            scope["stageOneCompletionPolicy"] = snapshot
    return scope


def _require_authorization(team_id: str) -> dict[str, Any]:
    try:
        snapshot = get_challenge_cup_dev_control_snapshot(team_id)
    except Exception as exc:
        raise ChallengeCupRealBatchError(
            "The DEV control snapshot is unavailable; real batches stay closed.",
            code="platform_not_authorized",
        ) from exc
    if not isinstance(snapshot, Mapping) or not _platform_snapshot_allows_real_batch(
        snapshot
    ):
        raise ChallengeCupRealBatchError(
            "Platform flow is not at RESEARCH_AUTHORIZATION_REQUIRED; real batches stay closed.",
            code="platform_not_authorized",
        )
    snapshot_team = str(snapshot.get("teamId") or "").strip()
    if snapshot_team and snapshot_team != str(team_id or "").strip():
        raise ChallengeCupRealBatchError(
            "The DEV control snapshot belongs to another team; real batches stay closed.",
            code="platform_not_authorized",
        )
    return dict(snapshot)


def _require_catalog_run_authorization(
    team_id: str,
    plan_id: str,
    snapshot: Mapping[str, Any],
):
    try:
        scope = _batch_scope(team_id, plan_id)
        report_hash = readiness_hash_from_snapshot(
            snapshot,
            expected_team_id=team_id,
        )
        authorization = find_catalog_run_authorization(
            team_id,
            plan_id=plan_id,
            batch_scope=scope,
            readiness_report_sha256_value=report_hash,
            require_model_policy=True,
        )
    except Exception as exc:
        raise ChallengeCupRealBatchError(
            "A durable CatalogRunAuthorization record is required before a real batch can start.",
            code="catalog_run_authorization_required",
        ) from exc
    if authorization is None:
        raise ChallengeCupRealBatchError(
            "A durable CatalogRunAuthorization record is required before a real batch can start.",
            code="catalog_run_authorization_required",
        )
    return authorization


def _current_catalog_run_authorization(
    team_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Resolve the durable authorization for the current readiness boundary."""

    snapshot = _require_authorization(team_id)
    authorization = _require_catalog_run_authorization(team_id, plan_id, snapshot)
    return authorization_to_dict(authorization)


def _require_envelope_catalog_run_authorization(
    envelope: Mapping[str, Any],
    current_authorization: Mapping[str, Any],
) -> None:
    """Fence a persisted batch to the readiness authorization that created it."""

    bound = envelope.get("catalogRunAuthorization")
    if not isinstance(bound, Mapping) or any(
        not str(bound.get(field) or "").strip()
        for field in _AUTHORIZATION_BINDING_FIELDS
    ):
        raise ChallengeCupRealBatchError(
            "The real batch has no complete durable CatalogRunAuthorization binding.",
            code="catalog_run_authorization_required",
        )
    if any(
        str(bound.get(field) or "").strip()
        != str(current_authorization.get(field) or "").strip()
        for field in _AUTHORIZATION_BINDING_FIELDS
    ):
        raise ChallengeCupRealBatchError(
            "The real batch readiness authorization has changed; "
            "start a new batch envelope for the current readiness report.",
            code="catalog_run_authorization_stale",
        )
    if bound.get("batchScope") != current_authorization.get("batchScope"):
        raise ChallengeCupRealBatchError(
            "The real batch model-policy authorization has changed; "
            "start a new batch envelope for the current model policy.",
            code="catalog_run_authorization_stale",
        )


def record_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    approved_by: str,
    readiness_evidence: Mapping[str, Any] | list[Any] | str | None = None,
    readiness_report_sha256_value: str | None = None,
    readiness_report_hash: str | None = None,
    approved_at_ms: int | None = None,
    authorization_id: str | None = None,
):
    """Persist operator approval for one exact real-batch scope.

    This is a service API for a later governed approval control.  It does not
    infer approval from ``confirmed`` and does not require the legacy DEV action
    string; callers may provide a Catalog readiness report/hash directly.
    """

    normalized_plan = validate_real_batch_plan(plan_id)
    scope = _batch_scope(_resolve_team_id(team_id), normalized_plan)
    if (
        readiness_evidence is None
        and readiness_report_sha256_value is None
        and readiness_report_hash is None
    ):
        normalized_team = _resolve_team_id(team_id)
        snapshot = _require_authorization(normalized_team)
        readiness_report_sha256_value = readiness_hash_from_snapshot(
            snapshot,
            expected_team_id=normalized_team,
        )
    try:
        return _record_catalog_run_authorization(
            _resolve_team_id(team_id),
            plan_id=normalized_plan,
            batch_scope=scope,
            approved_by=approved_by,
            readiness_evidence=readiness_evidence,
            readiness_report_sha256_value=readiness_report_sha256_value,
            readiness_report_hash=readiness_report_hash,
            approved_at_ms=approved_at_ms,
            authorization_id=authorization_id,
            require_model_policy=True,
            require_stage_one_policy=normalized_plan == "real-1",
        )
    except CatalogRunAuthorizationError as exc:
        raise ChallengeCupRealBatchError(
            str(exc), code="catalog_run_authorization_invalid"
        ) from exc


def _gate_complete(team_id: str, gate_id: str) -> bool:
    plan_id = PREVIOUS_GATE_PLAN_ID.get(gate_id)
    if plan_id is None:
        return True
    envelope = _load_envelope(team_id, plan_id)
    if envelope is None:
        return False
    state = _state_of(envelope)
    summary = state.outcome_summary()
    return (
        summary["succeeded"] == len(state.plan.question_ids)
        and not envelope.get("cancelled")
    )


def _concurrency_elevation_allowed(team_id: str, gate_id: str) -> bool:
    """Frozen policy: concurrency above the default needs completed G12 evidence.

    Two fail-closed evidence sources, no bypass: the real-12 batch fully
    succeeded, or a completed G12 calibration pilot (decision-#13 judgement
    records persisted through the G12 store) passed its statistical gate —
    thresholds come from the loadable active policy document when one is
    configured and bound to the recorded manifest, else the frozen
    calibration defaults.  The plan-level restriction (only the real-125
    plan may exceed the frozen default) is unchanged.
    """
    if gate_id != "G125":
        return False
    if _gate_complete(team_id, "G12"):
        return True
    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )
    from core.web.services.team_workflow.research_runtime.g12_calibration_store import (
        g12_calibration_gate_verdict_for_team,
    )

    try:
        policy = automation_policy_executor.load_active_policy_from_environment()
    except Exception:  # noqa: BLE001 - evidence read never breaks batch start
        policy = None
    return (
        g12_calibration_gate_verdict_for_team(
            team_id, policy=policy
        ).get("passed")
        is True
    )


def _require_gate_progression(team_id: str, gate_id: str) -> None:
    previous_gate = PREVIOUS_GATE.get(gate_id)
    if previous_gate is None:
        return
    plan_id = PREVIOUS_GATE_PLAN_ID[gate_id]
    if not _gate_complete(team_id, gate_id):
        raise ChallengeCupRealBatchError(
            f"Gate {gate_id} requires the {plan_id} batch ({previous_gate}) to be fully succeeded first.",
            code="previous_gate_incomplete",
        )


def _running_count(envelope: dict[str, Any], state: CatalogExecutionState) -> int:
    return sum(
        1
        for question_id in state.plan.question_ids
        if state.status(question_id) is QuestionStatus.RUNNING
    )


def _envelope_concurrency_limit(envelope: dict[str, Any]) -> int | None:
    """Read-only concurrency cap of one envelope for the status projection."""
    try:
        value = int(envelope.get("concurrency"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _idempotency_key(plan_id: str, question_id: str, attempt: int, *, kind: str) -> str:
    return f"real-batch-{plan_id}-{question_id}-{kind}-a{attempt}"


def _launch_pending(
    team_id: str,
    envelope: dict[str, Any],
    state: CatalogExecutionState,
    *,
    max_items: int | None,
    launcher: QuestionRunLauncher,
    start_dispatcher: StartDispatcher | None,
) -> list[dict[str, Any]]:
    """Launch pending questions up to the concurrency budget.

    Each launch persists the envelope immediately so a crash never loses the
    run reference. A launch failure marks only that question failed and counts
    toward the circuit breaker.
    """
    launched: list[dict[str, Any]] = []
    budget = envelope["concurrency"]
    while (
        _running_count(envelope, state) < budget
        and not envelope["cancelled"]
        and not circuit_breaker_tripped(
            envelope["consecutiveFailures"], failure_budget=envelope["failureBudget"]
        )
        and (max_items is None or len(launched) < max_items)
    ):
        # Real runs stay RUNNING across calls, so only untouched PENDING items
        # are launchable; the shared pending view also lists in-flight items.
        pending = [
            question_id
            for question_id in state.plan.question_ids
            if state.status(question_id) is QuestionStatus.PENDING
        ]
        if not pending:
            break
        question_id = pending[0]
        run_refs = envelope["runRefs"]
        prior = run_refs.get(question_id) if isinstance(run_refs, dict) else None
        attempt = int(prior.get("attempt") or 0) + 1 if isinstance(prior, dict) else 1
        state.mark_running(question_id)
        try:
            run = launcher(
                team_id,
                question_id,
                _idempotency_key(str(envelope["planId"]), question_id, attempt, kind="create"),
            )
            run_id = str(run.get("runId") or "").strip()
            if not run_id:
                raise RealBatchError("The question run launcher returned no runId.")
        except Exception as exc:  # noqa: BLE001 - one launch failure must isolate its own question.
            state.record_failure(question_id, f"launch_failed: {exc}")
            envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
            launched.append({"questionId": question_id, "outcome": "launch_failed"})
            _save_envelope(team_id, envelope)
            continue
        entry = {
            "runId": run_id,
            "attempt": attempt,
            "started": False,
            "startAttempts": 0,
            "nodeId": str(run.get("activeNodeId") or ""),
            "runVersion": int(run.get("runVersion") or 1),
            "launchedAt": _utc_now(),
        }
        run_refs[question_id] = entry
        started = False
        start_error = ""
        if start_dispatcher is not None:
            try:
                start_dispatcher(
                    team_id,
                    run,
                    entry["nodeId"],
                    _idempotency_key(
                        str(envelope["planId"]), question_id, attempt, kind="start"
                    ),
                )
                started = True
            except Exception as exc:  # noqa: BLE001 - a failed start dispatch is retried by poll.
                start_error = str(exc)
        entry["started"] = started
        if start_error:
            entry["lastStartError"] = start_error[:300]
        launched.append({"questionId": question_id, "outcome": "launched"})
        _save_envelope(team_id, envelope)
    return launched


def _dispatch_start(
    team_id: str,
    envelope: dict[str, Any],
    state: CatalogExecutionState,
    question_id: str,
    entry: dict[str, Any],
    start_dispatcher: StartDispatcher,
) -> None:
    entry["startAttempts"] = int(entry.get("startAttempts") or 0) + 1
    try:
        start_dispatcher(
            team_id,
            {"runId": entry["runId"], "runVersion": entry.get("runVersion") or 1},
            str(entry.get("nodeId") or ""),
            _idempotency_key(
                str(envelope["planId"]), question_id, int(entry.get("attempt") or 1), kind="start"
            ),
        )
        entry["started"] = True
        entry.pop("lastStartError", None)
    except Exception as exc:  # noqa: BLE001 - dispatch failures stay per-question and bounded.
        entry["lastStartError"] = str(exc)[:300]
        if int(entry["startAttempts"]) >= MAX_REAL_START_ATTEMPTS:
            state.record_failure(question_id, f"start_dispatch_failed: {exc}")
            envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
            envelope["runRefs"].pop(question_id, None)


def start_real_batch(
    team_id: str,
    *,
    plan_id: str,
    confirmed: bool = False,
    concurrency: int | None = None,
    max_items: int | None = None,
    failure_budget: int | None = None,
    launcher: QuestionRunLauncher | None = None,
    start_dispatcher: StartDispatcher | None = None,
) -> dict[str, Any]:
    """Start or resume one real gate batch under fail-closed authorization."""
    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    if not confirmed:
        raise ChallengeCupRealBatchError(
            "Real batch start requires explicit operator confirmation.",
            code="confirmation_required",
        )
    plan = real_plan(normalized_plan)
    _require_gate_progression(normalized_team, plan.gate_id)
    authorization = _current_catalog_run_authorization(
        normalized_team, normalized_plan
    )
    above_default_allowed = _concurrency_elevation_allowed(
        normalized_team, plan.gate_id
    )
    resolved_concurrency = validate_real_concurrency(
        concurrency if concurrency is not None else frozen_execution_policy()[
            "defaultMaxConcurrentQuestionRuns"
        ],
        above_default_allowed=above_default_allowed,
    )
    resolved_budget = validate_real_failure_budget(
        failure_budget if failure_budget is not None else DEFAULT_REAL_FAILURE_BUDGET
    )
    if max_items is not None and (not isinstance(max_items, int) or max_items < 0):
        raise ChallengeCupRealBatchError(
            "maxItems must be a non-negative integer.",
            code="invalid_max_items",
        )
    with _store_lock:
        envelope = _load_envelope(normalized_team, normalized_plan)
        if envelope is None:
            envelope = _new_envelope(
                normalized_team,
                normalized_plan,
                concurrency=resolved_concurrency,
                failure_budget=resolved_budget,
                authorization=authorization,
            )
            _save_envelope(normalized_team, envelope)
        else:
            _require_envelope_catalog_run_authorization(envelope, authorization)
        if envelope.get("cancelled"):
            raise ChallengeCupRealBatchError(
                "This real batch was cancelled and cannot be resumed.",
                code="batch_cancelled",
            )
        envelope["concurrency"] = resolved_concurrency
        envelope["failureBudget"] = resolved_budget
        state = _state_of(envelope)
        resolved_launcher = launcher or partial(
            _default_question_run_launcher,
            authorization=authorization,
        )
        launched = _launch_pending(
            normalized_team,
            envelope,
            state,
            max_items=max_items,
            launcher=resolved_launcher,
            start_dispatcher=start_dispatcher or _default_start_dispatcher,
        )
        envelope["checkpoint"] = state.to_checkpoint()
        _save_envelope(normalized_team, envelope)
        projection = project_real_batch_state(
            state,
            updated_at=envelope["updatedAt"],
            run_refs=envelope["runRefs"],
            awaiting_approval=envelope["awaitingApproval"],
            consecutive_failures=envelope["consecutiveFailures"],
            failure_budget=envelope["failureBudget"],
            cancelled=envelope["cancelled"],
            concurrency_limit=_envelope_concurrency_limit(envelope),
        )
    return {**projection, "launched": launched}


def poll_real_batch(
    team_id: str,
    *,
    plan_id: str,
    launcher: QuestionRunLauncher | None = None,
    run_status_reader: RunStatusReader | None = None,
    approved_output_reader: ApprovedOutputReader | None = None,
    start_dispatcher: StartDispatcher | None = None,
) -> dict[str, Any]:
    """Harvest terminal runs, promote approvals, and refill concurrency."""
    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    reader = run_status_reader or _default_run_status_reader
    approved_reader = approved_output_reader or _default_approved_output_reader
    resolved_launcher = launcher or _default_question_run_launcher
    resolved_dispatcher = start_dispatcher or _default_start_dispatcher
    with _store_lock:
        envelope = _load_envelope(normalized_team, normalized_plan)
        if envelope is None:
            raise ChallengeCupRealBatchError(
                f"No real batch exists for {normalized_plan}.",
                code="batch_not_found",
            )
        state = _state_of(envelope)
        runs = reader(normalized_team)
        # Harvesting and approval promotion are pure accounting against the
        # envelope's own durable authorization, so they survive readiness
        # rotations; the current-authorization fence only guards execution
        # (start dispatch and refill) and is computed lazily at those points.
        current_authorization: dict[str, Any] | None = None
        try:
            durable_authorization = _durable_authorization_record(
                envelope.get("catalogRunAuthorization"),
                team_id=normalized_team,
                plan_id=normalized_plan,
            )
            expected_model_policy_sha256 = authorized_model_policy_sha256(
                durable_authorization
            )
        except CatalogRunAuthorizationError as exc:
            raise ChallengeCupRealBatchError(
                "The real batch durable CatalogRunAuthorization is invalid.",
                code="catalog_run_authorization_stale",
            ) from exc
        harvested: list[dict[str, Any]] = []
        for question_id in state.plan.question_ids:
            if state.status(question_id) is not QuestionStatus.RUNNING:
                continue
            entry = envelope["runRefs"].get(question_id)
            if not isinstance(entry, dict) or not entry.get("runId"):
                state.record_failure(question_id, "run_reference_missing")
                harvested.append({"questionId": question_id, "outcome": "run_reference_missing"})
                continue
            run = runs.get(str(entry["runId"]))
            if not isinstance(run, dict):
                continue
            status = str(run.get("status") or "").strip()
            if status in ("succeeded", "failed", "cancelled"):
                if status == "succeeded":
                    approved = approved_reader(normalized_team, question_id)
                    if approved is None:
                        envelope["runRefs"].pop(question_id, None)
                        state.record_blocked(
                            question_id,
                            f"{AWAITING_APPROVAL_BLOCKED_PREFIX}:{entry['runId']}",
                        )
                        envelope["awaitingApproval"][question_id] = {
                            "runId": str(entry["runId"]),
                            "since": _utc_now(),
                        }
                        harvested.append(
                            {"questionId": question_id, "outcome": "awaiting_human_approval"}
                        )
                    else:
                        package = _validated_approved_package(
                            state,
                            question_id,
                            str(entry["runId"]),
                            approved,
                            expected_model_policy_sha256=expected_model_policy_sha256,
                        )
                        state.record_package(package)
                        envelope["runRefs"].pop(question_id, None)
                        envelope["consecutiveFailures"] = 0
                        harvested.append({"questionId": question_id, "outcome": "succeeded"})
                else:
                    envelope["runRefs"].pop(question_id, None)
                    state.record_failure(question_id, f"run_{status}")
                    envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
                    harvested.append({"questionId": question_id, "outcome": f"run_{status}"})
            elif not entry.get("started"):
                if current_authorization is None:
                    current_authorization = _current_catalog_run_authorization(
                        normalized_team, normalized_plan
                    )
                    _require_envelope_catalog_run_authorization(
                        envelope, current_authorization
                    )
                _dispatch_start(
                    normalized_team, envelope, state, question_id, entry, resolved_dispatcher
                )
        for question_id in list(envelope["awaitingApproval"]):
            if state.status(question_id) is QuestionStatus.BLOCKED:
                approved = approved_reader(normalized_team, question_id)
                if approved is not None:
                    awaiting = envelope["awaitingApproval"].get(question_id)
                    if not isinstance(awaiting, Mapping) or not awaiting.get("runId"):
                        raise ChallengeCupRealBatchError(
                            f"Awaiting approval run binding is missing: {question_id}.",
                            code="result_package_invalid",
                        )
                    package = _validated_approved_package(
                        state,
                        question_id,
                        str(awaiting["runId"]),
                        approved,
                        expected_model_policy_sha256=expected_model_policy_sha256,
                    )
                    state.invalidate(question_id, "human_approval_package_available")
                    state.record_package(package)
                    envelope["awaitingApproval"].pop(question_id, None)
                    envelope["consecutiveFailures"] = 0
                    harvested.append({"questionId": question_id, "outcome": "approved"})
        envelope["checkpoint"] = state.to_checkpoint()
        _save_envelope(normalized_team, envelope)
        resolved_refill_launcher = resolved_launcher
        needs_refill = any(
            state.status(question_id) is QuestionStatus.PENDING
            for question_id in state.plan.question_ids
        )
        if needs_refill:
            current_authorization = _current_catalog_run_authorization(
                normalized_team, normalized_plan
            )
            _require_envelope_catalog_run_authorization(
                envelope, current_authorization
            )
        if launcher is None and needs_refill:
            resolved_refill_launcher = partial(
                _default_question_run_launcher,
                authorization=current_authorization,
            )
        refill = _launch_pending(
            normalized_team,
            envelope,
            state,
            max_items=None,
            launcher=resolved_refill_launcher,
            start_dispatcher=resolved_dispatcher,
        )
        envelope["checkpoint"] = state.to_checkpoint()
        _save_envelope(normalized_team, envelope)
        projection = project_real_batch_state(
            state,
            updated_at=envelope["updatedAt"],
            run_refs=envelope["runRefs"],
            awaiting_approval=envelope["awaitingApproval"],
            consecutive_failures=envelope["consecutiveFailures"],
            failure_budget=envelope["failureBudget"],
            cancelled=envelope["cancelled"],
            concurrency_limit=_envelope_concurrency_limit(envelope),
        )
    return {**projection, "harvested": harvested, "launched": refill}


def cancel_real_batch(
    team_id: str,
    *,
    plan_id: str,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Stop new launches and block remaining pending items.

    Already-running question runs are left untouched: cancelling formal
    research runs stays an explicit per-run operator command.
    """
    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    if not confirmed:
        raise ChallengeCupRealBatchError(
            "Real batch cancel requires explicit operator confirmation.",
            code="confirmation_required",
        )
    with _store_lock:
        envelope = _load_envelope(normalized_team, normalized_plan)
        if envelope is None:
            raise ChallengeCupRealBatchError(
                f"No real batch exists for {normalized_plan}.",
                code="batch_not_found",
            )
        envelope["cancelled"] = True
        state = _state_of(envelope)
        # Only untouched PENDING items are blocked; in-flight runs keep their
        # RUNNING records so a later poll can still harvest their outcomes.
        for question_id in state.plan.question_ids:
            if state.status(question_id) is QuestionStatus.PENDING:
                state.record_blocked(question_id, CANCELLED_BLOCKED_REASON)
        envelope["checkpoint"] = state.to_checkpoint()
        _save_envelope(normalized_team, envelope)
        projection = project_real_batch_state(
            state,
            updated_at=envelope["updatedAt"],
            run_refs=envelope["runRefs"],
            awaiting_approval=envelope["awaitingApproval"],
            consecutive_failures=envelope["consecutiveFailures"],
            failure_budget=envelope["failureBudget"],
            cancelled=True,
            concurrency_limit=_envelope_concurrency_limit(envelope),
        )
    return projection


def get_real_batch_status(team_id: str, plan_id: str) -> dict[str, Any]:
    """Read-only projection of one real batch envelope."""
    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    with _store_lock:
        envelope = _load_envelope(normalized_team, normalized_plan)
    if envelope is None:
        return {
            "schemaVersion": ENVELOPE_SCHEMA_VERSION,
            "planId": normalized_plan,
            "gateId": real_plan(normalized_plan).gate_id,
            "exists": False,
        }
    state = _state_of(envelope)
    return {
        "exists": True,
        **project_real_batch_state(
            state,
            updated_at=str(envelope.get("updatedAt") or ""),
            run_refs=envelope.get("runRefs") or {},
            awaiting_approval=envelope.get("awaitingApproval") or {},
            consecutive_failures=int(envelope.get("consecutiveFailures") or 0),
            failure_budget=int(envelope.get("failureBudget") or DEFAULT_REAL_FAILURE_BUDGET),
            cancelled=bool(envelope.get("cancelled")),
            concurrency_limit=_envelope_concurrency_limit(envelope),
        ),
    }
