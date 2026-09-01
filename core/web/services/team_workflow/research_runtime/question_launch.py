"""Canonical Challenge Cup question-to-workflow launch contract.

Operators pick a question from the frozen 125-question catalog and either
resume its latest workflow checkpoint or start a new run.  An approved v2
question artifact remains the identity source for submission-eligible runs;
catalog-seeded runs are operator experiments and never mark formalWrites.

Clients still cannot author project, rules, evidence hash, or model contract
fields.  SCI-091 / SCI-096 campaign activation stays a separate governed
path for formal deep-experiment packages; catalog launch does not wait on it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from core.research.competition.resources import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CATALOG_SHA256,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    CompetitionResourceError,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_science_question_catalog,
)
from core.research.competition.result_set import CatalogScope
from core.research.competition.stage_one_completion_policy import (
    STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID,
    stage_one_policy_snapshot_for,
)
from core.research.workflow.contracts import DEFAULT_PROGRAM_ID
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.challenge_question_runs import (
    REQUIRED_HUMAN_GATE_KEYS,
    _package_bound_model_invocation_receipt_refs,
    challenge_question_run_summary,
    get_challenge_question_run_detail,
)
from core.web.services.team_workflow.research_projects import (
    ResearchProjectError,
    ensure_challenge_question_project,
    get_theme_activation,
)
from .budget_contract import FORMAL_STAGE_IDS

_STAGES = FORMAL_STAGE_IDS
_MAX_TOOL_CALLS = 600
_MAX_WALL_CLOCK_SECONDS = 12 * 60 * 60
_MAX_RETRIES = 5
_CATALOG_SEED_REVIEW_RUN_ID = "catalog-seed"
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def _stage_one_policy_fields(question_id: str) -> dict[str, Any]:
    snapshot = stage_one_policy_snapshot_for(
        question_id,
        STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID,
    )
    return {"stageOneCompletionPolicy": snapshot} if snapshot is not None else {}


class QuestionLaunchError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _server_model_routing_policy(team_id: str) -> dict[str, Any]:
    """Resolve the formal route snapshot from the server-owned Agent bindings."""

    try:
        from .catalog_run_authorization import (
            resolve_catalog_model_routing_policy,
        )

        policy = resolve_catalog_model_routing_policy(_text(team_id))
    except Exception as exc:
        raise QuestionLaunchError(
            "The formal six-Agent model routing policy is unavailable.",
            code="challenge_model_routing_policy_unavailable",
        ) from exc
    if not isinstance(policy, Mapping):
        raise QuestionLaunchError(
            "The formal six-Agent model routing policy is invalid.",
            code="challenge_model_routing_policy_invalid",
        )
    return dict(policy)


def _output_identity(output: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(output.get("identity"))


def _output_result_classification(output: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(output.get("result_classification"))


def _formal_record_receipts_ready(record: Mapping[str, Any]) -> bool:
    """Require package receipts plus the complete real-invocation trace."""

    validation = _mapping(record.get("validation"))
    if validation.get("modelInvocationReceipts") != "passed":
        return False
    try:
        receipt_refs = _package_bound_model_invocation_receipt_refs(dict(record))
    except (KeyError, OSError, TypeError, ValueError):
        return False
    if not receipt_refs:
        return False

    team_id = _text(record.get("teamId"))
    question_id = _text(record.get("questionId")).upper()
    run_id = _text(record.get("runId"))
    stored_trace_refs = record.get("modelInvocationReceiptTraceRefs")
    stored_coverage = _mapping(record.get("modelInvocationReceiptCoverage"))
    if (
        not team_id
        or not question_id
        or not run_id
        or not isinstance(stored_trace_refs, Sequence)
        or isinstance(stored_trace_refs, (str, bytes))
    ):
        return False
    try:
        from .model_invocation_receipt_registry import (
            model_invocation_receipt_coverage,
            question_model_invocation_receipt_refs,
        )

        live_trace_refs = question_model_invocation_receipt_refs(
            team_id,
            question_id=question_id,
            workflow_run_id=run_id,
        )
        live_coverage = model_invocation_receipt_coverage(live_trace_refs)
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return (
        bool(live_trace_refs)
        and list(stored_trace_refs) == live_trace_refs
        and stored_coverage == live_coverage
        and live_coverage.get("status") == "passed"
    )


def _formal_record_eligible(record: Mapping[str, Any]) -> bool:
    gates = _mapping(record.get("humanGates"))
    validation = _mapping(record.get("validation"))
    decisions = gates.get("decisions")
    return (
        record.get("schemaVersion") == 2
        and record.get("submissionEligible") is True
        and _text(record.get("status")) == "approved"
        and gates.get("allApproved") is True
        and isinstance(decisions, Mapping)
        and set(decisions) == REQUIRED_HUMAN_GATE_KEYS
        and all(_text(decisions.get(key)) == "approved" for key in REQUIRED_HUMAN_GATE_KEYS)
        and validation.get("schemaValidation") == "passed"
        and validation.get("citationValidation") == "passed"
        and validation.get("officialModelCall") is True
        and isinstance(record.get("resultPackage"), Mapping)
        and _formal_record_receipts_ready(record)
    )


def _approved_details(team_id: str) -> dict[str, dict[str, Any]]:
    summary = challenge_question_run_summary(team_id)
    details: dict[str, dict[str, Any]] = {}
    completed_results = [
        _mapping(value)
        for value in summary.get("completedQuestionResults") or []
        if isinstance(value, Mapping)
    ]
    for completed in completed_results:
        if not _formal_record_eligible(completed):
            continue
        question_id = _text(completed.get("questionId")).upper()
        run_id = _text(completed.get("runId"))
        if not question_id or not run_id:
            continue
        try:
            detail = get_challenge_question_run_detail(team_id, question_id, run_id=run_id)
        except ValueError as exc:
            raise QuestionLaunchError(
                f"Approved question artifact is unavailable for {question_id}.",
                code="challenge_question_artifact_unavailable",
            ) from exc
        record = _mapping(detail.get("record"))
        output = _mapping(detail.get("output"))
        review = _mapping(output.get("review"))
        submission = _mapping(output.get("submission"))
        if (
            not _formal_record_eligible(record)
            or output.get("schema_version") != 2
            or review.get("human_review_status") != "passed"
            or submission.get("eligible") is not True
        ):
            raise QuestionLaunchError(
                f"Approved question artifact is not a formal v2 submission candidate for {question_id}.",
                code="challenge_question_artifact_invalid",
            )
        details[question_id] = detail
    return details


def _question_title(output: Mapping[str, Any], question_id: str) -> str:
    identity = _output_identity(output)
    return _text(identity.get("question_en")) or question_id


def _question_scope(output: Mapping[str, Any]) -> str:
    understanding = _mapping(output.get("problem_understanding"))
    return _text(understanding.get("scope"))


def _frozen_deep_experiment_records() -> list[dict[str, Any]]:
    """Read required independent experiments from the frozen Program core.

    Program 2.3.0 is phased (``a_then_b``): the two experiments stay declared
    with ``executionPhase=2`` and activate only behind the full catalog
    result-set gate; the 125-question phase-1 flow never depends on them.
    """
    try:
        program = load_competition_program_core()
    except CompetitionResourceError as exc:
        raise QuestionLaunchError(
            "The frozen competition Program resource is unavailable or drifted.",
            code="challenge_competition_snapshot_invalid",
        ) from exc
    experiments = program.get("requiredDeepExperiments")
    records: list[dict[str, Any]] = []
    for item in experiments or []:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "experimentId": _text(item.get("experimentId")),
                "questionId": _text(item.get("questionId")).upper(),
                "name": _text(item.get("name")),
                "themeId": _text(item.get("themeId")),
                "campaignId": _text(item.get("campaignId")),
                "required": bool(item.get("required") is True),
            }
        )
    return records


def _deep_experiment_question_ids() -> set[str]:
    return {record["questionId"] for record in _frozen_deep_experiment_records() if record["questionId"]}


def _is_campaign_active(team_id: str, record: Mapping[str, Any]) -> bool:
    activation = get_theme_activation(team_id, _text(record.get("themeId")))
    return (
        bool(activation)
        and _text(activation.get("status")) == "active"
        and _text(activation.get("campaignId")) == _text(record.get("campaignId"))
    )


def _dev_authorization_ready(team_id: str) -> bool:
    """Return whether a current durable catalog approval is available.

    The readiness marker alone is only a platform boundary.  Campaign/run
    launch also requires an immutable ``CatalogRunAuthorization`` for the
    first real gate and the exact current readiness report hash; a rerun of
    readiness therefore invalidates the old approval until it is re-recorded.
    """
    try:
        from core.research.competition.real_control_batch import real_plan
        from core.web.services.team_workflow.challenge_cup_dev_controls import (
            get_challenge_cup_dev_control_snapshot,
        )

        from .catalog_run_authorization import (
            find_catalog_run_authorization,
            readiness_hash_from_snapshot,
            resolve_catalog_model_policy,
        )

        snapshot = get_challenge_cup_dev_control_snapshot(team_id)
    except Exception:
        return False
    if not isinstance(snapshot, Mapping):
        return False
    action = _text(snapshot.get("nextLegalAction"))
    if action != "RESEARCH_AUTHORIZATION_REQUIRED":
        return False
    snapshot_team = _text(snapshot.get("teamId"))
    requested_team = _text(team_id)
    if snapshot_team and snapshot_team != requested_team:
        return False
    try:
        report_hash = readiness_hash_from_snapshot(
            snapshot,
            expected_team_id=requested_team,
        )
        scope_plan = real_plan("real-1")
        scope = {
            **_stage_one_policy_fields(str(scope_plan.question_ids[0])),
            "planId": "real-1",
            "gateId": str(scope_plan.gate_id),
            "questionIds": [str(question_id) for question_id in scope_plan.question_ids],
            "modelPolicy": resolve_catalog_model_policy(
                requested_team
            ),
        }
        authorization = find_catalog_run_authorization(
            requested_team,
            plan_id="real-1",
            batch_scope=scope,
            readiness_report_sha256_value=report_hash,
            require_model_policy=True,
        )
    except Exception:
        return False
    return authorization is not None


def list_experiment_launch_options(team_id: str) -> dict[str, Any]:
    """Return the two frozen deep experiments with derived status fields.

    Status is derived only from the frozen Program core, the existing campaign
    activation ledger, approved formal v2 question artifacts, and the persisted
    DEV control snapshot.  DEV fixture success is never formal approval.
    """
    records = _frozen_deep_experiment_records()
    approved = set(_approved_details(team_id))
    authorization_ready = _dev_authorization_ready(team_id)
    experiments: list[dict[str, Any]] = []
    for record in records:
        question_id = record["questionId"]
        activation = get_theme_activation(team_id, record["themeId"])
        activated = (
            bool(activation)
            and _text(activation.get("status")) == "active"
            and _text(activation.get("campaignId")) == record["campaignId"]
        )
        question_result_approved = question_id in approved
        activation_allowed = authorization_ready and not activated
        blockers: list[str] = []
        if not activated and not authorization_ready:
            blockers.append("DEV fixtures are not complete; real Qwen/GPU work is not authorized")
        if not question_result_approved:
            blockers.append("question result is not formally approved")
        if activated and question_result_approved:
            next_action = "create_run"
        elif activation_allowed:
            next_action = "activate_campaign"
        elif activated:
            next_action = "await_formal_question_approval"
        else:
            next_action = "await_dev_readiness"
        experiments.append(
            {
                "experimentId": record["experimentId"],
                "questionId": question_id,
                "name": record["name"],
                "themeId": record["themeId"],
                "campaignId": record["campaignId"],
                "required": record["required"],
                "activated": activated,
                "activationStatus": "active" if activated else "not_activated",
                "activationAllowed": activation_allowed,
                "questionResultApproved": question_result_approved,
                "launchable": activated and question_result_approved,
                "nextAction": next_action,
                "blockers": blockers,
                "activatedAt": _text(activation.get("activatedAt")) if activated else "",
            }
        )
    return {"teamId": _text(team_id), "experiments": experiments}


def activate_experiment_campaign(
    team_id: str,
    *,
    experiment_id: str,
    confirmed: bool = False,
    activated_by: str = "operator",
) -> dict[str, Any]:
    """Activate one frozen deep experiment's canonical campaign (governed).

    Requires the persisted DEV control snapshot to have reached
    RESEARCH_AUTHORIZATION_REQUIRED and an explicit confirmation.  Reuses the
    existing research-scope activation so the campaign stays the single
    activation ledger.  An already-active campaign is idempotent.
    """
    normalized_experiment_id = _text(experiment_id)
    record = next(
        (
            item
            for item in _frozen_deep_experiment_records()
            if item["experimentId"] == normalized_experiment_id
        ),
        None,
    )
    if record is None:
        raise QuestionLaunchError(
            "Unknown deep experiment; only frozen Program experiments are activatable.",
            code="deep_experiment_not_found",
        )
    if not confirmed:
        raise QuestionLaunchError(
            "Experiment campaign activation requires explicit confirmation.",
            code="experiment_activation_confirmation_required",
        )
    # Enforce the DEV authorization gate BEFORE the idempotent short-circuit:
    # an already-active campaign must not bypass the gate when authorization
    # has since been revoked (reset / maintenance fence), otherwise re-activation
    # silently succeeds while the platform is not allowed to grant it.
    if not _dev_authorization_ready(team_id):
        raise QuestionLaunchError(
            "Experiment activation requires completed DEV fixtures and RESEARCH_AUTHORIZATION_REQUIRED.",
            code="experiment_activation_not_allowed",
        )
    existing = get_theme_activation(team_id, record["themeId"])
    if (
        bool(existing)
        and _text(existing.get("status")) == "active"
        and _text(existing.get("campaignId")) == record["campaignId"]
    ):
        return {"experimentId": normalized_experiment_id, **dict(existing)}
    from core.web.services.team_workflow.research_scope import (
        ResearchScopeError,
        activate_research_campaign,
    )

    try:
        activation = activate_research_campaign(
            team_id,
            program_id=DEFAULT_PROGRAM_ID,
            theme_id=record["themeId"],
            campaign_id=record["campaignId"],
            activated_by=_text(activated_by) or "operator",
            activation_ref=f"research-experiment://{normalized_experiment_id}",
        )
    except ResearchScopeError as exc:
        raise QuestionLaunchError(
            str(exc),
            code=getattr(exc, "code", "experiment_activation_not_allowed"),
        ) from exc
    return {"experimentId": normalized_experiment_id, **activation}


def _catalog_question_option(item: Mapping[str, Any]) -> dict[str, Any] | None:
    question_id = _text(item.get("id")).upper()
    if not question_id:
        return None
    domain = _text(item.get("domain"))
    return {
        "questionId": question_id,
        "title": _text(item.get("question_en")) or question_id,
        "scope": domain,
        "domain": domain,
        "catalogId": CATALOG_ID,
        "reviewRunId": "",
        "artifactSha256": "",
        "source": "catalog",
        "launchable": True,
    }


def _load_catalog_question_options() -> list[dict[str, Any]]:
    try:
        catalog = load_science_question_catalog()
    except CompetitionResourceError as exc:
        raise QuestionLaunchError(
            "The frozen competition catalog is unavailable or drifted.",
            code="challenge_competition_snapshot_invalid",
        ) from exc
    questions: list[dict[str, Any]] = []
    for item in catalog.get("questions") or []:
        if not isinstance(item, Mapping):
            continue
        option = _catalog_question_option(item)
        if option is not None:
            questions.append(option)
    return questions


def list_catalog_question_launch_options(team_id: str) -> dict[str, Any]:
    """Picker summary: frozen 125 catalog titles, no approved-artifact hydration."""

    return {"teamId": _text(team_id), "questions": _load_catalog_question_options()}


def list_question_launch_options(team_id: str) -> dict[str, Any]:
    """Return all 125 catalog questions; overlay approved artifacts when present."""

    questions = _load_catalog_question_options()
    approved = _approved_details(team_id)
    if not approved:
        return {"teamId": _text(team_id), "questions": questions}
    overlaid: list[dict[str, Any]] = []
    for row in questions:
        detail = approved.get(row["questionId"])
        if detail is None:
            overlaid.append(row)
            continue
        output = _mapping(detail.get("output"))
        artifact = _mapping(detail.get("artifact"))
        overlaid.append(
            {
                "questionId": row["questionId"],
                "title": _question_title(output, row["questionId"]),
                "scope": _question_scope(output) or row["domain"],
                "domain": row["domain"],
                "catalogId": CATALOG_ID,
                "reviewRunId": _text(detail.get("selectedRunId")),
                "artifactSha256": _text(artifact.get("sha256")),
                "source": "approved_artifact",
                "launchable": True,
            }
        )
    return {"teamId": _text(team_id), "questions": overlaid}


def _iso_to_ms(value: str) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def _run_timestamp_ms(run: Mapping[str, Any]) -> int:
    try:
        ms = int(run.get("updatedAtMs") or run.get("createdAtMs") or 0)
    except (TypeError, ValueError):
        ms = 0
    if ms:
        return ms
    return _iso_to_ms(_text(run.get("updatedAt"))) or _iso_to_ms(_text(run.get("createdAt")))


def _run_current_node_id(run: Mapping[str, Any]) -> str:
    current_ids = run.get("runtimeCurrentNodeIds")
    if isinstance(current_ids, list) and current_ids:
        return _text(current_ids[0])
    return _text(run.get("activeNodeId"))


def attach_question_run_checkpoints(
    questions: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the latest workflow checkpoint for each catalog question."""

    definition = build_challenge_cup_workflow_definition()
    node_ids = [node.nodeId for node in definition.nodes]
    labels = {node.nodeId: node.label for node in definition.nodes}
    index_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
    total_steps = len(node_ids)
    latest_by_question: dict[str, Mapping[str, Any]] = {}
    succeeded_by_question: dict[str, Mapping[str, Any]] = {}
    max_completed_by_question: dict[str, int] = {}
    for run in runs:
        question_id = _text(run.get("questionId")).upper()
        run_id = _text(run.get("runId"))
        if not question_id or not run_id:
            continue
        previous = latest_by_question.get(question_id)
        if previous is None or _run_timestamp_ms(run) >= _run_timestamp_ms(previous):
            latest_by_question[question_id] = run
        run_status = _text(run.get("status"))
        if run_status == "succeeded":
            previous_success = succeeded_by_question.get(question_id)
            if previous_success is None or _run_timestamp_ms(run) >= _run_timestamp_ms(previous_success):
                succeeded_by_question[question_id] = run
        run_node_index = index_by_id.get(_run_current_node_id(run), 0)
        run_completed = total_steps if run_status == "succeeded" else run_node_index
        max_completed_by_question[question_id] = max(
            max_completed_by_question.get(question_id, 0),
            run_completed,
        )
    attached: list[dict[str, Any]] = []
    for question in questions:
        record = dict(question)
        question_id = _text(record.get("questionId")).upper()
        run = latest_by_question.get(question_id)
        if run is None:
            record["checkpoint"] = None
            attached.append(record)
            continue
        status = _text(run.get("status")) or "queued"
        # A finished retry must not erase a previous success: once any run
        # succeeded the question keeps its succeeded checkpoint (artifacts
        # remain usable), while an in-flight newer run still shows as running.
        status_run = run
        if status in _TERMINAL_RUN_STATUSES and status != "succeeded":
            status_run = succeeded_by_question.get(question_id) or run
            status = _text(status_run.get("status")) or status
        node_id = _run_current_node_id(status_run)
        record["checkpoint"] = {
            "runId": _text(status_run.get("runId")),
            "status": status,
            "currentNodeId": node_id,
            "currentNodeLabel": labels.get(node_id, ""),
            "completedCount": max_completed_by_question.get(question_id, 0),
            "totalSteps": total_steps,
            "resumable": _text(run.get("status")) not in _TERMINAL_RUN_STATUSES,
        }
        attached.append(record)
    return attached


def _catalog_seed_hash(question_id: str) -> str:
    payload = f"{CATALOG_SHA256}:{question_id}:{_CATALOG_SEED_REVIEW_RUN_ID}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _competition_program_snapshot() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        program = load_competition_program_core()
        policy = load_full_catalog_execution_core()
        catalog = load_science_question_catalog()
    except CompetitionResourceError as exc:
        raise QuestionLaunchError(
            "The frozen competition Program, Policy, or catalog resource is unavailable or drifted.",
            code="challenge_competition_snapshot_invalid",
        ) from exc
    program_body = _mapping(program.get("program"))
    directions = [_text(item) for item in program_body.get("dimensions") or [] if _text(item)]
    snapshot = {
        "programContractVersion": _text(program.get("contractVersion")),
        "programCoreBehaviorHash": CORE_BEHAVIOR_HASH,
        "fullCatalogPolicyVersion": _text(policy.get("version")),
        "fullCatalogCorePolicyHash": CORE_POLICY_HASH,
        "catalogId": CATALOG_ID,
        "catalogQuestionCount": CATALOG_QUESTION_COUNT,
        "catalogSha256": CATALOG_SHA256,
        "questionSchemaVersion": 2,
        "directionMode": "a_then_b",
        "directions": directions,
    }
    if catalog.get("catalog_id") != CATALOG_ID or len(directions) != 2:
        raise QuestionLaunchError(
            "The frozen competition Program, Policy, catalog, or phased A→B direction snapshot is invalid.",
            code="challenge_competition_snapshot_invalid",
        )
    return snapshot, program_body


def _catalog_question(question_id: str) -> dict[str, Any] | None:
    try:
        catalog = load_science_question_catalog()
    except CompetitionResourceError:
        return None
    for item in catalog.get("questions") or []:
        if isinstance(item, dict) and _text(item.get("id")).upper() == question_id:
            return item
    return None


def _positive_int(value: Any, *, field: str, maximum: int | None) -> int:
    invalid = not isinstance(value, int) or isinstance(value, bool) or value < 1
    if maximum is not None:
        invalid = invalid or value > maximum
    if invalid:
        expected = (
            "a positive integer"
            if maximum is None
            else f"an integer between 1 and {maximum}"
        )
        raise QuestionLaunchError(
            f"{field} must be {expected}.",
            code="invalid_safety_limits",
        )
    return value


def build_safety_budget_policy(safety_limits: Mapping[str, Any]) -> dict[str, Any]:
    stage_tokens = _mapping(safety_limits.get("stageTokens"))
    if set(stage_tokens) != set(_STAGES):
        raise QuestionLaunchError(
            "stageTokens must contain exactly the three workflow stages.",
            code="invalid_safety_limits",
        )
    normalized_stage_tokens = {
        stage: _positive_int(
            stage_tokens.get(stage),
            field=f"stageTokens.{stage}",
            maximum=None,
        )
        for stage in _STAGES
    }
    tool_calls = _positive_int(
        safety_limits.get("toolCalls"), field="toolCalls", maximum=_MAX_TOOL_CALLS
    )
    wall_clock_seconds = _positive_int(
        safety_limits.get("wallClockSeconds"),
        field="wallClockSeconds",
        maximum=_MAX_WALL_CLOCK_SECONDS,
    )
    max_retries = _positive_int(
        safety_limits.get("maxRetries"), field="maxRetries", maximum=_MAX_RETRIES
    )
    return {
        "tokens": max(normalized_stage_tokens.values()),
        "toolCalls": tool_calls,
        "wallClockSeconds": wall_clock_seconds,
        "maxRetries": max_retries,
        "experiments": 12,
        "computeUnits": 100,
        "maxParallelTasks": 3,
        "stageBudgets": {
            stage: {
                "tokens": normalized_stage_tokens[stage],
                "toolCalls": tool_calls,
                "wallClockSeconds": wall_clock_seconds,
                "experiments": 12,
                "computeUnits": 100,
            }
            for stage in _STAGES
        },
    }


def _hypothesis_first_scope(team_id: str, question_id: str) -> dict[str, str]:
    """Resolve the server-authoritative full scope used by latest reads."""
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain
    from core.web.services.team_workflow.research_scope import resolve_research_scope

    seed = hypothesis_first_chain._question_scope_envelope(team_id, question_id)
    return resolve_research_scope(
        team_id,
        agent_id=seed["agentId"],
        scope_seed=seed,
    )


def _tracked_catalog_scope() -> dict[str, str]:
    """Return the immutable identity of the tracked 125-question catalog."""

    return CatalogScope.from_tracked_resources().to_dict()


def _hypothesis_first_flag(
    team_id: str,
    question_id: str,
    *,
    scope: Mapping[str, Any],
) -> bool:
    """Challenge Cup catalog questions are hypothesis-first by design.

    The flag must not depend on an already-recorded selection: the selection
    is recorded *after* the run exists (chicken-and-egg), and the readiness
    gates (source_finding / hypothesis_design) only engage when the frozen
    input snapshot carries ``hypothesisFirst: true``.  Every catalog launch —
    seed or approved-artifact — therefore freezes the marker so a fresh
    question starts at hypothesis selection, not at source finding.
    """
    try:
        from core.web.services.team_workflow import hypothesis_selection

        if hypothesis_selection.get_latest_hypothesis_selection(
            team_id,
            question_id,
            scope=scope,
        ).get("selection"):
            return True
    except hypothesis_selection.ResearchHypothesisSelectionNotFoundError:
        return _catalog_question(question_id) is not None
    return False


def _build_catalog_seed_run_input(
    team_id: str,
    *,
    question_id: str,
    catalog_item: Mapping[str, Any],
    safety_limits: Mapping[str, Any],
) -> dict[str, Any]:
    title = _text(catalog_item.get("question_en")) or question_id
    scope = _text(catalog_item.get("domain"))
    try:
        project = ensure_challenge_question_project(
            team_id,
            question_id=question_id,
            title=title,
            topic=scope,
        )["project"]
    except ResearchProjectError as exc:
        raise QuestionLaunchError(
            str(exc),
            code=getattr(exc, "code", "challenge_project_resolution_failed"),
        ) from exc
    competition_program_snapshot, program_body = _competition_program_snapshot()
    model_routing_policy = _server_model_routing_policy(team_id)
    artifact_sha256 = _catalog_seed_hash(question_id)
    artifact_ref = (
        f"challenge-question-catalog://{CATALOG_ID}/{question_id}/"
        f"{_CATALOG_SEED_REVIEW_RUN_ID}/{artifact_sha256}"
    )
    directions = [_text(item) for item in program_body.get("dimensions") or [] if _text(item)]
    hypothesis_scope = _hypothesis_first_scope(team_id, question_id)
    return {
        **_stage_one_policy_fields(question_id),
        "teamId": _text(team_id),
        "projectId": _text(project.get("projectId")),
        "questionId": question_id,
        "researchScopeEnvelope": hypothesis_scope,
        "catalogScope": _tracked_catalog_scope(),
        "researchBriefHash": artifact_sha256,
        "datasetRefs": [artifact_ref],
        "metricContract": {
            "primary": "evidence_coverage",
            "direction": "maximize",
            "source": artifact_ref,
        },
        "constraintSnapshot": {
            "formalWrites": False,
            "challengeQuestionArtifact": artifact_ref,
            "questionReviewRunId": _CATALOG_SEED_REVIEW_RUN_ID,
            "launchSource": "catalog",
            "competitionProgramSnapshot": competition_program_snapshot,
        },
        "competitionProgramSnapshot": competition_program_snapshot,
        "competitionRuleRef": CATALOG_ID,
        "competitionRuleVersion": "catalog-seed-v1",
        "trackAndRubricSnapshot": {
            "track": _text(program_body.get("track")),
            "directionMode": "a_then_b",
            "directions": directions,
            "blockingRules": [
                "catalog_seed_not_submission_eligible",
                "program_policy_catalog_snapshot_required",
            ],
        },
        "researchObjectiveContract": {
            "question": title,
            "scope": scope,
            "falsifiableOutcome": "",
            "hypothesisFirst": _hypothesis_first_flag(
                team_id,
                question_id,
                scope=hypothesis_scope,
            ),
        },
        "sourcePolicy": {"minimumPrimarySources": 3, "requireCounterEvidence": True},
        "budgetPolicy": build_safety_budget_policy(safety_limits),
        "stopPolicy": {"maxNoImprovementRounds": 2, "stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": artifact_ref,
        "modelRoutingPolicy": model_routing_policy,
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11, 29, 47],
            "questionArtifactSha256": artifact_sha256,
        },
        "createdBy": "operator",
    }


def build_question_run_input(
    team_id: str,
    *,
    question_id: str,
    safety_limits: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive immutable run input from an approved artifact or the catalog seed."""

    normalized_question_id = _text(question_id).upper()
    detail = _approved_details(team_id).get(normalized_question_id)
    if detail is None:
        catalog_item = _catalog_question(normalized_question_id)
        if catalog_item is None:
            raise QuestionLaunchError(
                "The selected question is not in the frozen 125-question catalog.",
                code="challenge_question_not_launchable",
            )
        return _build_catalog_seed_run_input(
            team_id,
            question_id=normalized_question_id,
            catalog_item=catalog_item,
            safety_limits=safety_limits,
        )
    deep_record = next(
        (
            item
            for item in _frozen_deep_experiment_records()
            if item["questionId"] == normalized_question_id
        ),
        None,
    )
    if deep_record is not None and not _is_campaign_active(team_id, deep_record):
        raise QuestionLaunchError(
            "Deep experiment run requires its canonical campaign to be activated.",
            code="deep_experiment_campaign_not_activated",
        )
    output = _mapping(detail.get("output"))
    artifact = _mapping(detail.get("artifact"))
    review_run_id = _text(detail.get("selectedRunId"))
    artifact_sha256 = _text(artifact.get("sha256"))
    identity = _output_identity(output)
    catalog_id = _text(identity.get("catalog_id"))
    if not review_run_id or not artifact_sha256 or not catalog_id:
        raise QuestionLaunchError(
            "The approved question artifact is missing immutable identity fields.",
            code="challenge_question_artifact_invalid",
        )
    title = _question_title(output, normalized_question_id)
    scope = _question_scope(output)
    try:
        project = ensure_challenge_question_project(
            team_id,
            question_id=normalized_question_id,
            title=title,
            topic=scope,
        )["project"]
    except ResearchProjectError as exc:
        raise QuestionLaunchError(
            str(exc),
            code=getattr(exc, "code", "challenge_project_resolution_failed"),
        ) from exc

    final_summary = _mapping(_output_result_classification(output).get("final_summary"))
    research_plan = _mapping(output.get("research_plan"))
    competition_program_snapshot, program_body = _competition_program_snapshot()
    model_routing_policy = _server_model_routing_policy(team_id)
    directions = [_text(item) for item in program_body.get("dimensions") or [] if _text(item)]
    artifact_ref = f"challenge-question-artifact://{catalog_id}/{normalized_question_id}/{review_run_id}/{artifact_sha256}"
    hypothesis_first = _hypothesis_first_flag(
        team_id,
        normalized_question_id,
        scope=_hypothesis_first_scope(team_id, normalized_question_id),
    )
    return {
        **_stage_one_policy_fields(normalized_question_id),
        "teamId": _text(team_id),
        "projectId": _text(project.get("projectId")),
        "questionId": normalized_question_id,
        "researchScopeEnvelope": _hypothesis_first_scope(team_id, normalized_question_id),
        "catalogScope": _tracked_catalog_scope(),
        "researchBriefHash": artifact_sha256,
        "datasetRefs": [artifact_ref],
        "metricContract": {
            "primary": "evidence_coverage",
            "direction": "maximize",
            "source": artifact_ref,
        },
        "constraintSnapshot": {
            "formalWrites": False,
            "challengeQuestionArtifact": artifact_ref,
            "questionReviewRunId": review_run_id,
            "competitionProgramSnapshot": competition_program_snapshot,
        },
        "competitionProgramSnapshot": competition_program_snapshot,
        "competitionRuleRef": catalog_id,
        "competitionRuleVersion": f"question-output-v{int(output.get('schema_version') or 1)}",
        "trackAndRubricSnapshot": {
            "track": _text(program_body.get("track")),
            "directionMode": "a_then_b",
            "directions": directions,
            "blockingRules": [
                "approved_v2_question_artifact_required",
                "program_policy_catalog_snapshot_required",
            ],
        },
        "researchObjectiveContract": {
            "question": title,
            "scope": scope,
            "falsifiableOutcome": _text(final_summary.get("next_validation_step"))
            or _text(research_plan.get("failure_criteria")),
            "hypothesisFirst": hypothesis_first,
        },
        "sourcePolicy": {"minimumPrimarySources": 3, "requireCounterEvidence": True},
        "budgetPolicy": build_safety_budget_policy(safety_limits),
        "stopPolicy": {"maxNoImprovementRounds": 2, "stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": artifact_ref,
        "modelRoutingPolicy": model_routing_policy,
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11, 29, 47],
            "questionArtifactSha256": artifact_sha256,
        },
        "createdBy": "operator",
    }
