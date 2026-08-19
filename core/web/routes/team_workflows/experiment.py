"""Team workflow routes: experiment."""
from __future__ import annotations
from fastapi import HTTPException, Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router
from .experiment_models import (
    CandidateStoreListResponse,
    CandidateStoreValidationResponse,
    ChallengeSubmissionReadinessResponse,
    ChallengeQuestionRunStatusResponse,
    ExperimentMethodCatalogResponse,
    ExperimentPlanningStatusResponse,
    ExperimentRouteResponse,
)

@router.get(
    "/teams/{team_id}/workflow-orchestration/experiments/status",
    response_model=ExperimentPlanningStatusResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_planning_status(team_id: str) -> dict:
    try:
        return get_experiment_planning_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/question-runs/status",
    response_model=ChallengeQuestionRunStatusResponse,
    response_model_exclude_unset=True,
)
def team_workflow_challenge_question_run_status(team_id: str) -> dict:
    try:
        return get_challenge_question_run_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/submission-readiness",
    response_model=ChallengeSubmissionReadinessResponse,
    response_model_exclude_unset=True,
)
def team_workflow_challenge_submission_readiness(team_id: str) -> dict:
    try:
        return get_challenge_submission_readiness(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/questions/{question_id}",
    response_model=ChallengeQuestionRunDetailResponse,
)
def team_workflow_challenge_question_run_detail(
    team_id: str,
    question_id: str,
    run_id: str = Query("", alias="runId", max_length=160),
) -> ChallengeQuestionRunDetailResponse:
    try:
        return ChallengeQuestionRunDetailResponse.model_validate(
            get_challenge_question_run_detail(
                team_id,
                question_id,
                run_id=run_id,
            )
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/question-runs",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_challenge_question_run_register(team_id: str, payload: ChallengeQuestionOutputPayload) -> dict:
    try:
        return register_challenge_question_output(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        _raise_team_workflow_route_error(
            "challenge_question_run.register",
            team_id,
            exc,
            status_code=422,
            fields={"registeredBy": payload.registeredBy},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/question-runs/publish",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_challenge_question_run_publish(
    team_id: str,
    payload: ChallengeQuestionPublishPayload,
) -> dict:
    try:
        return publish_research_project_challenge_question_output(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "challenge_question_run.publish",
            team_id,
            exc,
            status_code=422,
            fields={
                "researchProjectId": payload.researchProjectId,
                "questionId": payload.questionId,
                "taskId": payload.taskId,
                "turnId": payload.turnId,
            },
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/questions/{question_id}/runs/{run_id}/review",
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_challenge_question_run_review(
    team_id: str,
    question_id: str,
    run_id: str,
    payload: ChallengeQuestionReviewPayload,
) -> dict:
    try:
        return review_challenge_question_output(team_id, question_id, run_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        _raise_team_workflow_route_error(
            "challenge_question_run.review",
            team_id,
            exc,
            status_code=422,
            fields={"questionId": question_id, "runId": run_id, "reviewer": payload.reviewer},
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/experiments/methods",
    response_model=ExperimentMethodCatalogResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_method_catalog(team_id: str) -> dict:
    try:
        return get_experiment_method_catalog(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plan",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_plan_create(team_id: str, payload: ExperimentPlanCreatePayload) -> dict:
    try:
        return create_experiment_plan(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_plan.create",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": payload.stageRoundId, "createdByAgent": payload.createdByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_plan.create",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": payload.stageRoundId, "createdByAgent": payload.createdByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/hypotheses/engineering-proxy",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_proxy_hypothesis_materialize(
    team_id: str,
    plan_id: str,
    payload: ExperimentEngineeringProxyHypothesisPayload,
) -> dict:
    try:
        return materialize_experiment_proxy_hypothesis(
            team_id,
            plan_id,
            payload.model_dump(),
        )
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.materialize_proxy",
            team_id,
            exc,
            status_code=404,
            fields={
                "planId": plan_id,
                "createdByAgent": payload.createdByAgent,
            },
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.materialize_proxy",
            team_id,
            exc,
            status_code=422,
            fields={
                "planId": plan_id,
                "createdByAgent": payload.createdByAgent,
            },
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/hypotheses/{candidate_id}/complete-design",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_scientific_hypothesis_complete(
    team_id: str,
    plan_id: str,
    candidate_id: str,
    payload: ExperimentScientificHypothesisCompletionPayload,
) -> dict:
    try:
        return complete_experiment_hypothesis_from_design(
            team_id,
            source_plan_id=plan_id,
            hypothesis_candidate_id=candidate_id,
            payload=payload.model_dump(),
        )
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.complete_design",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.complete_design",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "candidateId": candidate_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/hypotheses/{candidate_id}/revision",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_hypothesis_revision_create(
    team_id: str,
    plan_id: str,
    candidate_id: str,
    payload: ExperimentHypothesisRevisionPayload,
) -> dict:
    try:
        return create_experiment_plan_revision_from_hypothesis(
            team_id,
            source_plan_id=plan_id,
            hypothesis_candidate_id=candidate_id,
            created_by_agent=payload.createdByAgent,
            idempotency_key=payload.idempotencyKey,
        )
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.create_revision",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.create_revision",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "candidateId": candidate_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/baseline-artifact",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_baseline_artifact_register(team_id: str, plan_id: str, payload: ExperimentBaselineArtifactPayload) -> dict:
    try:
        return register_experiment_baseline_artifact(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_baseline_artifact.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "registeredByAgent": payload.registeredByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_baseline_artifact.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "registeredByAgent": payload.registeredByAgent, "artifactPath": payload.artifactPath},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/hypothesis-resume",
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_hypothesis_resume(team_id: str, payload: ExperimentHypothesisResumePayload) -> dict:
    try:
        return resume_experiment_hypothesis(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.resume", team_id, exc, status_code=404, fields={}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_hypothesis.resume",
            team_id,
            exc,
            status_code=422,
            fields={"hypothesisCandidateId": payload.hypothesisCandidateId},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/freeze",
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_design_freeze(team_id: str, plan_id: str, payload: ExperimentDesignFreezePayload) -> dict:
    try:
        return freeze_experiment_design(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_design.freeze", team_id, exc, status_code=404, fields={"planId": plan_id}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_design.freeze", team_id, exc, status_code=422, fields={"planId": plan_id}
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/smoke-result",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_smoke_result_register(team_id: str, plan_id: str, payload: ExperimentSmokeResultPayload) -> dict:
    try:
        return register_experiment_smoke_result(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_result.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_result.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent, "status": payload.status},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/smoke-run",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_smoke_run(team_id: str, plan_id: str, payload: ExperimentSmokeRunPayload) -> dict:
    try:
        return run_experiment_smoke_run(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_run.execute", team_id, exc, status_code=404, fields={"planId": plan_id}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_run.execute",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "adapter": payload.adapter},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/full-run-result",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_full_run_result_register(team_id: str, plan_id: str, payload: ExperimentFullRunResultPayload) -> dict:
    try:
        return register_experiment_full_run_result(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run_result.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run_result.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent, "status": payload.status},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/full-run/prepare",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_full_run_prepare(team_id: str, plan_id: str, payload: ExperimentFullRunExecutionPayload) -> dict:
    try:
        return prepare_experiment_full_run(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run.prepare", team_id, exc, status_code=404, fields={"planId": plan_id}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run.prepare",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/full-run/execute",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_full_run_execute(team_id: str, plan_id: str, payload: ExperimentFullRunExecutionPayload) -> dict:
    try:
        return execute_experiment_full_run(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run.execute", team_id, exc, status_code=404, fields={"planId": plan_id}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run.execute",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/knowledge-ingestion-request",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_experiment_result_knowledge_ingestion_request(team_id: str, plan_id: str, payload: ExperimentResultKnowledgeIngestionPayload) -> dict:
    try:
        return request_experiment_result_knowledge_ingestion(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_result_knowledge_ingestion.request",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "requestedByAgent": payload.requestedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_result_knowledge_ingestion.request",
            team_id,
            exc,
            status_code=422,
            fields={
                "planId": plan_id,
                "requestedByAgent": payload.requestedByAgent,
                "stewardAgentId": payload.stewardAgentId,
                "knowledgeBaseId": payload.knowledgeBaseId,
            },
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/stage-rounds/{stage_round_id}/coordination/retry",
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_stage_round_coordination_retry(team_id: str, stage_round_id: str) -> dict:
    try:
        return retry_research_stage_round_coordination(team_id, stage_round_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.coordination_retry",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": stage_round_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.coordination_retry",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": stage_round_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/stage-rounds/{stage_round_id}/memory-record/retry",
    response_model=ExperimentRouteResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_stage_round_memory_retry(team_id: str, stage_round_id: str) -> dict:
    try:
        return retry_research_stage_round_memory_record(team_id, stage_round_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.memory_retry",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": stage_round_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.memory_retry",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": stage_round_id},
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/candidates",
    response_model=CandidateStoreListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_candidate_list(
    team_id: str,
    candidateType: str = "",
    currentState: str = "",
    qualityStatus: str = "",
    limit: int = 100,
    includeValidation: bool = False,
    includeStore: bool = False,
) -> dict:
    try:
        return list_candidate_store(
            team_id,
            candidate_type=candidateType,
            current_state=currentState,
            quality_status=qualityStatus,
            limit=limit,
            include_validation=includeValidation,
            include_store=includeStore,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/teams/{team_id}/workflow-orchestration/candidates/validation",
    response_model=CandidateStoreValidationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_candidate_validation(team_id: str) -> dict:
    try:
        return validate_candidate_store(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
