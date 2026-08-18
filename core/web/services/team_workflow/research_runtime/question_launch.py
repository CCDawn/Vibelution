"""Canonical Challenge Cup question-to-workflow launch contract.

The approved question artifact is the only source for a new workflow's
identity and immutable research contract.  Operators may set safety ceilings,
but they never supply a parallel project, rules, evidence hash, or model
contract.

The two frozen deep experiments (SCI-091, SCI-096) are governed separately:
their launch options derive only from the frozen Program core, the existing
campaign activation ledger, approved formal v2 question artifacts, and the
persisted DEV control snapshot.  A DEV fixture result is never formal
approval; DEV readiness only unlocks the ability to activate the real
campaign.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from core.research.workflow.contracts import DEFAULT_PROGRAM_ID
from core.web.services.team_workflow.challenge_question_runs import (
    REQUIRED_HUMAN_GATE_KEYS,
    challenge_question_run_summary,
    get_challenge_question_run_detail,
)
from core.web.services.team_workflow.research_projects import (
    ResearchProjectError,
    ensure_challenge_question_project,
    get_theme_activation,
)

_MODEL_REF = "relay_openai/gpt-5.6-luna"
_MODEL_PURPOSES = (
    "source_discovery",
    "extraction",
    "reasoning",
    "review",
    "governance",
)
_STAGES = (
    "knowledge_collection",
    "experiment_design",
    "execution_iteration",
)
_MAX_STAGE_TOKENS = 500_000
_MAX_TOOL_CALLS = 600
_MAX_WALL_CLOCK_SECONDS = 12 * 60 * 60
_MAX_RETRIES = 5


class QuestionLaunchError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _output_identity(output: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(output.get("identity"))


def _output_result_classification(output: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(output.get("result_classification"))


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
    """Read the two required independent experiments from the frozen Program core."""
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
    """DEV fixtures must be complete so the next legal action is authorization.

    A DEV fixture result never counts as formal approval; reaching this marker
    only unlocks the ability to activate the real campaign.
    """
    try:
        from core.web.services.team_workflow.challenge_cup_dev_controls import (
            get_challenge_cup_dev_control_snapshot,
        )

        snapshot = get_challenge_cup_dev_control_snapshot(team_id)
    except Exception:
        return False
    return _text(snapshot.get("nextLegalAction")) == "RESEARCH_AUTHORIZATION_REQUIRED"


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
    existing = get_theme_activation(team_id, record["themeId"])
    if (
        bool(existing)
        and _text(existing.get("status")) == "active"
        and _text(existing.get("campaignId")) == record["campaignId"]
    ):
        return {"experimentId": normalized_experiment_id, **dict(existing)}
    if not _dev_authorization_ready(team_id):
        raise QuestionLaunchError(
            "Experiment activation requires completed DEV fixtures and RESEARCH_AUTHORIZATION_REQUIRED.",
            code="experiment_activation_not_allowed",
        )
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


def list_question_launch_options(team_id: str) -> dict[str, Any]:
    """Return only fully approved questions that may start a workflow run."""

    questions: list[dict[str, Any]] = []
    for question_id, detail in _approved_details(team_id).items():
        output = _mapping(detail.get("output"))
        artifact = _mapping(detail.get("artifact"))
        questions.append(
            {
                "questionId": question_id,
                "title": _question_title(output, question_id),
                "scope": _question_scope(output),
                "catalogId": _text(_output_identity(output).get("catalog_id")),
                "reviewRunId": _text(detail.get("selectedRunId")),
                "artifactSha256": _text(artifact.get("sha256")),
            }
        )
    return {"teamId": _text(team_id), "questions": questions}


def _positive_int(value: Any, *, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise QuestionLaunchError(
            f"{field} must be an integer between 1 and {maximum}.",
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
            maximum=_MAX_STAGE_TOKENS,
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


def build_question_run_input(
    team_id: str,
    *,
    question_id: str,
    safety_limits: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the complete immutable run input from one approved question."""

    normalized_question_id = _text(question_id).upper()
    detail = _approved_details(team_id).get(normalized_question_id)
    if detail is None:
        raise QuestionLaunchError(
            "The selected question is not approved for workflow launch.",
            code="challenge_question_not_launchable",
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
    competition_program_snapshot = {
        "programContractVersion": _text(program.get("contractVersion")),
        "programCoreBehaviorHash": CORE_BEHAVIOR_HASH,
        "fullCatalogPolicyVersion": _text(policy.get("version")),
        "fullCatalogCorePolicyHash": CORE_POLICY_HASH,
        "catalogId": CATALOG_ID,
        "catalogQuestionCount": CATALOG_QUESTION_COUNT,
        "catalogSha256": CATALOG_SHA256,
        "questionSchemaVersion": 2,
        "directionMode": "a_plus_b",
        "directions": directions,
    }
    if catalog.get("catalog_id") != CATALOG_ID or len(directions) != 2:
        raise QuestionLaunchError(
            "The frozen competition Program, Policy, catalog, or A+B direction snapshot is invalid.",
            code="challenge_competition_snapshot_invalid",
        )
    artifact_ref = f"challenge-question-artifact://{catalog_id}/{normalized_question_id}/{review_run_id}/{artifact_sha256}"
    hypothesis_first = False
    try:
        from core.web.services.team_workflow import hypothesis_selection

        hypothesis_first = bool(
            hypothesis_selection.get_latest_hypothesis_selection(
                team_id, normalized_question_id
            ).get("selection")
        )
    except Exception:
        hypothesis_first = False
    return {
        "teamId": _text(team_id),
        "projectId": _text(project.get("projectId")),
        "questionId": normalized_question_id,
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
            "directionMode": "a_plus_b",
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
        "modelRoutingPolicy": {purpose: _MODEL_REF for purpose in _MODEL_PURPOSES},
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11, 29, 47],
            "questionArtifactSha256": artifact_sha256,
        },
        "createdBy": "operator",
    }
