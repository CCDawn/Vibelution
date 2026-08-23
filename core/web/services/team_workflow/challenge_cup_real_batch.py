"""Team-scoped Challenge Cup real catalog batch service.

Owns team storage resolution and persistence for the real-question batch
surface: the ``CatalogExecutionState`` checkpoints plus the run-reference
sidecar envelope (run ids, start attempts, awaiting-approval index, circuit
breaker counters). The pure planning contracts live in
``core.research.competition.real_control_batch``; run creation, START_NODE
dispatch, run status reads and approved-output reads are injectable callables
so tests never touch the formal runtime.

Authorization is fail-closed: explicit confirmation remains a user action, but
the authorization fact is an immutable ``CatalogRunAuthorization`` bound to the
current readiness report and exact batch scope.
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
from core.research.competition.result_set import QuestionResult
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services import team_service
from core.web.services.team_workflow.challenge_cup_dev_controls import (
    get_challenge_cup_dev_control_snapshot,
)
from core.web.services.team_workflow.research_projects import team_workspace_root
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    CatalogRunAuthorizationError,
    authorization_to_dict,
    expected_batch_scope,
    find_catalog_run_authorization,
    readiness_report_sha256_from_snapshot,
)
from core.web.services.team_workflow.research_runtime.catalog_run_authorization import (
    record_catalog_run_authorization as _record_catalog_run_authorization,
)

CONTROLS_DIRNAME = "challenge_cup_real_batch"
BATCHES_DIRNAME = "batches"
ENVELOPE_SCHEMA_VERSION = 1
AWAITING_APPROVAL_BLOCKED_PREFIX = "awaiting_human_approval"
CANCELLED_BLOCKED_REASON = "cancelled_by_operator"
TEMPLATE_VERSION = "question-output-v2"

DEFAULT_STAGE_TOKENS = 200_000
DEFAULT_TOOL_CALLS = 600
DEFAULT_WALL_CLOCK_SECONDS = 4 * 60 * 60
DEFAULT_MAX_RETRIES = 3

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
    return team_workspace_root(team_id) / CONTROLS_DIRNAME / BATCHES_DIRNAME


def _envelope_path(team_id: str, plan_id: str) -> Path:
    return _batches_root(team_id) / f"{plan_id}.json"


def _default_safety_limits() -> dict[str, int]:
    return {
        "stageTokens": {
            "knowledge_collection": DEFAULT_STAGE_TOKENS,
            "experiment_design": DEFAULT_STAGE_TOKENS,
            "execution_iteration": DEFAULT_STAGE_TOKENS,
        },
        "toolCalls": DEFAULT_TOOL_CALLS,
        "wallClockSeconds": DEFAULT_WALL_CLOCK_SECONDS,
        "maxRetries": DEFAULT_MAX_RETRIES,
    }


def _default_question_run_launcher(
    team_id: str,
    question_id: str,
    idempotency_key: str,
    *,
    catalog_run_authorization: Mapping[str, Any] | None = None,
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
        catalog_run_authorization=catalog_run_authorization,
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
        "officialModelCall": record.get("validation", {})
        .get("officialModelCall")
        is True,
    }


def _question_result_from_approved(
    state: CatalogExecutionState,
    question_id: str,
    approved: dict[str, Any],
) -> QuestionResult:
    knowledge_locator = (
        f"challenge-question-artifact://{approved['catalogId']}/{question_id}/"
        f"{approved['reviewRunId']}/{approved['artifactSha256']}"
    )
    model_receipt_locator = (
        f"challenge-model-evidence://{question_id}/{approved['reviewRunId']}"
    )
    return QuestionResult.create(
        scope=state.scope,
        question_id=question_id,
        model_receipt_locator=model_receipt_locator,
        knowledge_locator=knowledge_locator,
        template_version=TEMPLATE_VERSION,
    )


def _seed_from_previous_gates(team_id: str, state: CatalogExecutionState) -> int:
    """Seed already-approved results from earlier gate batches.

    Progressive gates are cumulative (G5 includes G1's questions); an approved
    result from an earlier gate carries forward instead of being re-run.
    """
    seeded = 0
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
                pending = state.status(result.question_id) is QuestionStatus.PENDING
            except CatalogExecutionError:
                continue
            if pending:
                state.record_success(result.question_id, result)
                seeded += 1
    return seeded


def _new_envelope(
    team_id: str,
    plan_id: str,
    *,
    concurrency: int,
    failure_budget: int,
    catalog_run_authorization: Mapping[str, Any],
) -> dict[str, Any]:
    state = new_real_batch_state(plan_id)
    _seed_from_previous_gates(team_id, state)
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
        "catalogRunAuthorization": dict(catalog_run_authorization),
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
        return CatalogExecutionState.from_checkpoint(envelope["checkpoint"])
    except (KeyError, CatalogExecutionError) as exc:
        raise RealBatchStorageError(
            f"The real batch checkpoint is malformed: {exc}"
        ) from exc


def _require_platform_authorization_boundary(team_id: str) -> dict[str, Any]:
    try:
        snapshot = get_challenge_cup_dev_control_snapshot(team_id)
    except Exception as exc:
        raise ChallengeCupRealBatchError(
            "The DEV control snapshot is unavailable; real batches stay closed.",
            code="platform_not_authorized",
        ) from exc
    if (
        not isinstance(snapshot, Mapping)
        or str(snapshot.get("nextLegalAction") or "")
        != "RESEARCH_AUTHORIZATION_REQUIRED"
    ):
        raise ChallengeCupRealBatchError(
            "Platform flow is not at RESEARCH_AUTHORIZATION_REQUIRED; real batches stay closed.",
            code="platform_not_authorized",
        )
    snapshot_team_id = str(snapshot.get("teamId") or "").strip()
    if snapshot_team_id and snapshot_team_id != team_id:
        raise ChallengeCupRealBatchError(
            "The DEV control snapshot belongs to a different team; real batches stay closed.",
            code="platform_not_authorized",
        )
    return dict(snapshot)


def _readiness_hash_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    return readiness_report_sha256_from_snapshot(snapshot)


def _current_catalog_run_authorization(
    team_id: str,
    plan_id: str,
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only the exact current approval needed to dispatch a real run."""

    try:
        boundary = dict(snapshot) if snapshot is not None else _require_platform_authorization_boundary(team_id)
        scope = expected_batch_scope(plan_id)
        report_hash = _readiness_hash_from_snapshot(boundary)
        record = find_catalog_run_authorization(
            team_id,
            plan_id=plan_id,
            batch_scope=scope,
            readiness_report_sha256_value=report_hash,
        )
        if record is None:
            raise CatalogRunAuthorizationError("no matching authorization record")
        return authorization_to_dict(record)
    except ChallengeCupRealBatchError:
        raise
    except Exception as exc:
        raise ChallengeCupRealBatchError(
            "A durable CatalogRunAuthorization record is required before dispatch.",
            code="catalog_run_authorization_required",
        ) from exc


def record_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    approved_by: str,
) -> dict[str, Any]:
    """Record a server-principal approval for the exact current plan/report."""

    normalized_team = _resolve_team_id(team_id)
    normalized_plan = validate_real_batch_plan(plan_id)
    try:
        snapshot = _require_platform_authorization_boundary(normalized_team)
        record = _record_catalog_run_authorization(
            normalized_team,
            plan_id=normalized_plan,
            batch_scope=expected_batch_scope(normalized_plan),
            approved_by=approved_by,
            readiness_report_sha256_value=_readiness_hash_from_snapshot(snapshot),
        )
        return authorization_to_dict(record)
    except ChallengeCupRealBatchError:
        raise
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
    catalog_run_authorization: Mapping[str, Any],
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
            "catalogRunAuthorization": dict(catalog_run_authorization),
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


def _authorization_identity(value: Any) -> tuple[str, str, str, str] | None:
    if not isinstance(value, Mapping):
        return None
    identity = tuple(
        str(value.get(key) or "").strip()
        for key in (
            "authorizationId",
            "scopeHash",
            "readinessReportSha256",
            "recordHash",
        )
    )
    return identity if all(identity) else None


def _entry_matches_authorization(
    entry: Mapping[str, Any], authorization: Mapping[str, Any]
) -> bool:
    entry_identity = _authorization_identity(entry.get("catalogRunAuthorization"))
    authorization_identity = _authorization_identity(authorization)
    return entry_identity is not None and entry_identity == authorization_identity


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
    readiness_snapshot = _require_platform_authorization_boundary(normalized_team)
    plan = real_plan(normalized_plan)
    _require_gate_progression(normalized_team, plan.gate_id)
    catalog_run_authorization = _current_catalog_run_authorization(
        normalized_team,
        normalized_plan,
        snapshot=readiness_snapshot,
    )
    above_default_allowed = (
        plan.gate_id == "G125"
        and _gate_complete(normalized_team, "G12")
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
                catalog_run_authorization=catalog_run_authorization,
            )
            _save_envelope(normalized_team, envelope)
        if envelope.get("cancelled"):
            raise ChallengeCupRealBatchError(
                "This real batch was cancelled and cannot be resumed.",
                code="batch_cancelled",
            )
        envelope["concurrency"] = resolved_concurrency
        envelope["failureBudget"] = resolved_budget
        envelope["catalogRunAuthorization"] = dict(catalog_run_authorization)
        state = _state_of(envelope)
        resolved_launcher = launcher or partial(
            _default_question_run_launcher,
            catalog_run_authorization=catalog_run_authorization,
        )
        launched = _launch_pending(
            normalized_team,
            envelope,
            state,
            max_items=max_items,
            launcher=resolved_launcher,
            start_dispatcher=start_dispatcher or _default_start_dispatcher,
            catalog_run_authorization=catalog_run_authorization,
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
        harvested: list[dict[str, Any]] = []
        unstarted_entries: list[tuple[str, dict[str, Any]]] = []
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
                envelope["runRefs"].pop(question_id, None)
                if _authorization_identity(entry.get("catalogRunAuthorization")) is None:
                    state.record_failure(question_id, "catalog_run_authorization_missing")
                    envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
                    harvested.append(
                        {"questionId": question_id, "outcome": "catalog_run_authorization_missing"}
                    )
                    continue
                if status == "succeeded":
                    approved = approved_reader(normalized_team, question_id)
                    if approved is None:
                        state.record_blocked(
                            question_id,
                            f"{AWAITING_APPROVAL_BLOCKED_PREFIX}:{entry['runId']}",
                        )
                        envelope["awaitingApproval"][question_id] = {
                            "runId": str(entry["runId"]),
                            "catalogRunAuthorization": dict(
                                entry["catalogRunAuthorization"]
                            ),
                            "since": _utc_now(),
                        }
                        harvested.append(
                            {"questionId": question_id, "outcome": "awaiting_human_approval"}
                        )
                    else:
                        state.record_success(
                            question_id,
                            _question_result_from_approved(state, question_id, approved),
                        )
                        envelope["consecutiveFailures"] = 0
                        harvested.append({"questionId": question_id, "outcome": "succeeded"})
                else:
                    state.record_failure(question_id, f"run_{status}")
                    envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
                    harvested.append({"questionId": question_id, "outcome": f"run_{status}"})
            elif not entry.get("started"):
                unstarted_entries.append((question_id, entry))
        for question_id in list(envelope["awaitingApproval"]):
            if state.status(question_id) is QuestionStatus.BLOCKED:
                approved = approved_reader(normalized_team, question_id)
                if approved is not None:
                    awaiting = envelope["awaitingApproval"].get(question_id)
                    if not isinstance(awaiting, Mapping) or _authorization_identity(
                        awaiting.get("catalogRunAuthorization")
                    ) is None:
                        continue
                    state.record_success(
                        question_id,
                        _question_result_from_approved(state, question_id, approved),
                    )
                    envelope["awaitingApproval"].pop(question_id, None)
                    envelope["consecutiveFailures"] = 0
                    harvested.append({"questionId": question_id, "outcome": "approved"})
        envelope["checkpoint"] = state.to_checkpoint()
        _save_envelope(normalized_team, envelope)
        needs_refill = any(
            state.status(question_id) is QuestionStatus.PENDING
            for question_id in state.plan.question_ids
        )
        current_authorization: dict[str, Any] | None = None
        if unstarted_entries or needs_refill:
            try:
                current_authorization = _current_catalog_run_authorization(
                    normalized_team,
                    normalized_plan,
                )
            except ChallengeCupRealBatchError:
                # Harvested state is durable, but no dispatch/refill may happen
                # without a current, matching approval.
                envelope["checkpoint"] = state.to_checkpoint()
                _save_envelope(normalized_team, envelope)
                raise
            envelope["catalogRunAuthorization"] = dict(current_authorization)
            for question_id, entry in unstarted_entries:
                if not _entry_matches_authorization(entry, current_authorization):
                    state.record_failure(question_id, "catalog_run_authorization_stale")
                    envelope["consecutiveFailures"] = int(envelope["consecutiveFailures"]) + 1
                    envelope["runRefs"].pop(question_id, None)
                    harvested.append(
                        {"questionId": question_id, "outcome": "catalog_run_authorization_stale"}
                    )
                    continue
                _dispatch_start(
                    normalized_team,
                    envelope,
                    state,
                    question_id,
                    entry,
                    resolved_dispatcher,
                )
        refill: list[dict[str, Any]] = []
        if current_authorization is not None:
            resolved_launcher = launcher or partial(
                _default_question_run_launcher,
                catalog_run_authorization=current_authorization,
            )
            refill = _launch_pending(
                normalized_team,
                envelope,
                state,
                max_items=None,
                launcher=resolved_launcher,
                start_dispatcher=resolved_dispatcher,
                catalog_run_authorization=current_authorization,
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
        ),
    }
