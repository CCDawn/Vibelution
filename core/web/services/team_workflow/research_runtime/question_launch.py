"""Canonical Challenge Cup question-to-workflow launch contract.

The approved question artifact is the only source for a new workflow's
identity and immutable research contract.  Operators may set safety ceilings,
but they never supply a parallel project, rules, evidence hash, or model
contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.web.services.team_workflow.challenge_question_runs import (
    challenge_question_run_summary,
    get_challenge_question_run_detail,
)
from core.web.services.team_workflow.research_projects import (
    ResearchProjectError,
    ensure_challenge_question_project,
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


def _approved_details(team_id: str) -> dict[str, dict[str, Any]]:
    summary = challenge_question_run_summary(team_id)
    approved_ids = sorted({_text(value).upper() for value in summary.get("completedQuestionIds") or [] if _text(value)})
    details: dict[str, dict[str, Any]] = {}
    for question_id in approved_ids:
        try:
            detail = get_challenge_question_run_detail(team_id, question_id)
        except ValueError as exc:
            raise QuestionLaunchError(
                f"Approved question artifact is unavailable for {question_id}.",
                code="challenge_question_artifact_unavailable",
            ) from exc
        record = _mapping(detail.get("record"))
        gates = _mapping(record.get("humanGates"))
        if _text(record.get("status")) != "approved" or gates.get("allApproved") is not True:
            continue
        details[question_id] = detail
    return details


def _question_title(output: Mapping[str, Any], question_id: str) -> str:
    return _text(output.get("question_en")) or _text(output.get("question")) or question_id


def _question_scope(output: Mapping[str, Any]) -> str:
    understanding = _mapping(output.get("problem_understanding"))
    return _text(understanding.get("scope"))


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
                "catalogId": _text(output.get("catalog_id")),
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
    output = _mapping(detail.get("output"))
    artifact = _mapping(detail.get("artifact"))
    review_run_id = _text(detail.get("selectedRunId"))
    artifact_sha256 = _text(artifact.get("sha256"))
    catalog_id = _text(output.get("catalog_id"))
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

    final_summary = _mapping(output.get("final_summary"))
    research_plan = _mapping(output.get("research_plan"))
    artifact_ref = f"challenge-question-artifact://{catalog_id}/{normalized_question_id}/{review_run_id}/{artifact_sha256}"
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
        },
        "competitionRuleRef": catalog_id,
        "competitionRuleVersion": f"question-output-v{int(output.get('schema_version') or 1)}",
        "trackAndRubricSnapshot": {
            "track": "赛道一 / 方向一 / A 科学假设生成与研究计划设计",
            "blockingRules": ["approved_question_artifact_required"],
        },
        "researchObjectiveContract": {
            "question": title,
            "scope": scope,
            "falsifiableOutcome": _text(final_summary.get("next_validation_step"))
            or _text(research_plan.get("failure_criteria")),
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
