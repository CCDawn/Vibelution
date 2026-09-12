"""Team workflow routes: hypothesis-first flow (HF-5).

薄路由层：selection（HF-1）、meeting rounds（HF-2 四态关门流）、
hypothesis rounds（HF-3 查询）与 chain 编排（HF-4）的 HTTP 透传。
业务语义、状态机与 fail-closed 校验一律留在
``core/web/services/team_workflow/`` 的 service 层；route 只做边界校验、
DTO 转换与错误映射。UI 的完成态一律来自服务端投影（chain state /
round 记录），不由客户端推断。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Mapping, NoReturn

from fastapi import Header, HTTPException, Query, Request, Response, status

from core.research.workflow.contracts import (
    AnomalyInbox,
    ContractValidationError,
    WorkflowCommandKind,
    scope_hash_for,
)
from core.web.services import chat_room_service
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow import (
    challenge_question_retire,
    hypothesis_rounds,
    hypothesis_selection,
    meeting_rounds,
    meeting_runtime,
)
from core.web.services.team_workflow.challenge_question_runs import (
    get_challenge_question_run_detail,
)
from core.web.services.team_workflow.research_runtime import (
    anomaly_inbox_service,
    hypothesis_first_chain,
    hypothesis_first_state_v2,
    meeting_receipt_authority,
)
from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    get_event_replay_service,
    get_query_service,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope_from_http,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    production_workflow_runtime,
)
from core.web.services.team_workflow.research_scope import (
    frozen_theme_registry,
    resolve_theme_contract,
)

from ._errors import _raise_team_workflow_route_error
from ._router import router
from .research_runtime import _submit_workflow_command
from .hypothesis_first_models import (
    AnomalyInboxExtendBudgetRequest,
    AnomalyInboxResponse,
    CandidateEvidenceTrailResponse,
    ChainStateResponse,
    ClearEvidenceGapMarkerPayload,
    ClearEvidenceGapMarkerResponse,
    CloseReviewMeetingResponse,
    CollectionHandoffPayload,
    CollectionHandoffResponse,
    CollectionRequestListResponse,
    HypothesisRoundListResponse,
    HypothesisRoundResponse,
    HypothesisSelectionListResponse,
    HypothesisSelectionRecordPayload,
    HypothesisSelectionRecordResponse,
    HypothesisSelectionResponse,
    MeetingApproveDigestPayload,
    MeetingClosureApprovePayload,
    MeetingDigestDraftPayload,
    MeetingDigestRejectPayload,
    MeetingRoundListResponse,
    MeetingRoundMutationResponse,
    MeetingRoundResponse,
    MeetingSourceMessagesResponse,
    MeetingSummaryBeginPayload,
    MeetingSummaryDraftRequest,
    QuestionExperimentRetirePayload,
    QuestionExperimentRetirePreviewResponse,
    QuestionExperimentRetireResponse,
    QuestionRunResetPayload,
    QuestionRunResetPreviewResponse,
    QuestionRunResetResponse,
    ReviewNextRoundResponse,
    ReviewRoundLinkListResponse,
    RoundFailureRetryRequest,
    SelectionContextResponse,
)
from .hypothesis_first_state_models import (
    HypothesisFirstCommandRequest,
    HypothesisFirstStateV2,
)

_HYPOTHESIS_FIRST_WORKFLOW = "hypothesis_first"
_DEFAULT_BRANCH = "main"
_OPERATOR_AGENT_ID = "operator"


def _selection_scope(team_id: str, question_id: str) -> dict[str, str]:
    """Derive the server-authoritative scope shared by context and latest reads."""
    normalized_question_id = str(question_id or "").strip().upper()
    registry = frozen_theme_registry()
    theme_record = next(
        (
            record
            for record in registry.values()
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ),
        None,
    )
    if theme_record is not None:
        contract = resolve_theme_contract(
            team_id,
            theme_id=str(theme_record.get("themeId") or ""),
            campaign_id=str(theme_record.get("campaignId") or ""),
        )
    else:
        contract = resolve_theme_contract(
            team_id,
            theme_id=f"dev-{normalized_question_id.lower()}",
            campaign_id="dev-campaign",
        )
    if contract.is_dev_theme():
        mode = "dev"
    elif contract.is_activated():
        mode = "formal"
    else:
        mode = "platform"
    return {
        "program": str(contract.programId),
        "theme": str(contract.themeId),
        "campaign": str(contract.campaignId),
        "question": normalized_question_id,
        "branch": _DEFAULT_BRANCH,
        "workflow": _HYPOTHESIS_FIRST_WORKFLOW,
        "agentId": _OPERATOR_AGENT_ID,
        "mode": mode,
    }


def _selection_read_scope(team_id: str, question_id: str) -> dict[str, str]:
    scope = _selection_scope(team_id, question_id)
    scope["scopeHash"] = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    return scope


def _map_domain_error(action: str, team_id: str, exc: Exception) -> NoReturn:
    """Map service exceptions to HTTP errors with route-error diagnostics."""
    if isinstance(exc, meeting_rounds.MeetingRoundsLockTimeoutError):
        # A bounded lock wait that expired is a transient capacity failure,
        # not a client fault: 503 with structured detail lets the client show
        # a retryable error instead of hanging or reading a 500 as a fault.
        _raise_team_workflow_route_error(
            action,
            team_id,
            exc,
            status_code=503,
            fields={
                "lockCaller": exc.caller,
                "lockWaitedSeconds": f"{exc.waited_seconds:.3f}",
            },
            detail={
                "code": exc.code,
                "message": str(exc),
                "caller": exc.caller,
                "waitedSeconds": exc.waited_seconds,
            },
        )
    if isinstance(exc, TeamNotFoundError):
        status_code = 404
    elif isinstance(
        exc,
        (
            hypothesis_first_chain.StateVersionConflictError,
            hypothesis_first_chain.StaleDigestError,
            hypothesis_first_chain.IdempotencyConflictError,
            chat_room_service.ChatRoomBusyError,
        ),
    ):
        # A busy linked chat room is a transient conflict on a V2 retry path
        # (retry_generation / resume_discussion / reopen_review restart room
        # rounds): 409 lets the client re-poll and retry instead of reading a
        # 500 as a server fault (SCI-096 UX follow-up).
        status_code = 409
    elif isinstance(
        exc,
        (
            hypothesis_selection.ResearchHypothesisSelectionNotFoundError,
            meeting_rounds.ResearchMeetingRoundNotFoundError,
            hypothesis_rounds.ResearchHypothesisRoundNotFoundError,
            hypothesis_first_chain.HypothesisFirstChainNotFoundError,
        ),
    ):
        status_code = 404
    else:
        status_code = 422
    _raise_team_workflow_route_error(
        action,
        team_id,
        exc,
        status_code=status_code,
    )


_DOMAIN_ERRORS = (
    TeamServiceError,
    ContractValidationError,
    chat_room_service.ChatRoomBusyError,
    hypothesis_selection.ResearchHypothesisSelectionError,
    meeting_rounds.ResearchMeetingRoundError,
    meeting_runtime.ResearchMeetingRuntimeError,
    hypothesis_rounds.ResearchHypothesisRoundError,
    hypothesis_first_chain.HypothesisFirstChainError,
    challenge_question_retire.ChallengeQuestionRetireError,
    meeting_receipt_authority.MeetingReceiptAuthorityError,
)


# ---------------------------------------------------------------------------
# Selection (HF-1)
# ---------------------------------------------------------------------------


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/selections",
    status_code=status.HTTP_201_CREATED,
    response_model=HypothesisSelectionRecordResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_record(
    team_id: str,
    payload: HypothesisSelectionRecordPayload,
) -> dict:
    try:
        return hypothesis_selection.record_hypothesis_selection(
            team_id,
            payload.model_dump(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.selection.record", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/selections",
    response_model=HypothesisSelectionListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_list(
    team_id: str,
    question_id: str = Query("", alias="questionId", max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    try:
        return hypothesis_selection.list_hypothesis_selections(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.selection.list", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/selections/latest",
    response_model=HypothesisSelectionResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_latest(
    team_id: str,
    question_id: str = Query(..., alias="questionId", min_length=1, max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    try:
        return hypothesis_selection.get_latest_hypothesis_selection(
            team_id,
            question_id,
            scope=_selection_read_scope(team_id, question_id),
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.selection.latest", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/selections/{selection_id}",
    response_model=HypothesisSelectionResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_get(
    team_id: str,
    selection_id: str,
) -> dict:
    try:
        return hypothesis_selection.get_hypothesis_selection(team_id, selection_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.selection.get", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/candidates/evidence-trail",
    response_model=CandidateEvidenceTrailResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_candidate_evidence_trail(
    team_id: str,
    question_id: str,
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    """Discussion-message evidence trail per candidate (click-through)."""
    try:
        return hypothesis_first_chain.candidate_evidence_trail(
            team_id,
            question_id,
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.candidates.evidence_trail", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/selection-context",
    response_model=SelectionContextResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_context(
    team_id: str,
    question_id: str,
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    """Derive the server-authoritative scope + candidates for the selection UI.

    scope 六元组由冻结节目核心（questionId → theme/campaign）与 theme 激活
    台账推导；候选假说来自赛题 artifact。UI 回显该 scope 提交选择，不在
    客户端自行拼装。目录种子题没有 approved artifact 时不 404：候选回落到
    第 0 轮候选生成讨论写入链条台账的 proposedCandidates。
    """
    normalized_question_id = question_id.strip().upper()
    normalized_workflow_run_id = str(workflow_run_id or "").strip()
    detail: dict[str, Any] | None = None
    try:
        if normalized_workflow_run_id:
            authority = meeting_receipt_authority.resolve_active_question_authority(
                team_id,
                normalized_question_id,
                normalized_workflow_run_id,
            )
            if authority is None:
                raise meeting_receipt_authority.MeetingReceiptAuthorityError(
                    "workflowRunId cannot be verified from the canonical Ledger"
                )
        detail = get_challenge_question_run_detail(
            team_id,
            normalized_question_id,
            run_id=normalized_workflow_run_id,
        )
    except TeamNotFoundError as exc:
        _map_domain_error("hypothesis_first.selection.context", team_id, exc)
    except meeting_receipt_authority.MeetingReceiptAuthorityError as exc:
        _map_domain_error("hypothesis_first.selection.context", team_id, exc)
    except ValueError as exc:
        if not str(exc).startswith("challenge_question_run_not_found"):
            _raise_team_workflow_route_error(
                "hypothesis_first.selection.context",
                team_id,
                exc,
                status_code=404,
                fields={"questionId": normalized_question_id},
            )
        detail = None
    output = detail.get("output") if isinstance(detail, dict) and isinstance(detail.get("output"), dict) else {}
    hypotheses = output.get("hypotheses") if isinstance(output.get("hypotheses"), list) else []
    candidates = [
        item
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("hypothesis_id") or "").strip()
    ]
    selection_section = output.get("selection") if isinstance(output.get("selection"), dict) else {}
    default_selected = str(selection_section.get("selected_hypothesis_id") or "").strip()
    if not candidates:
        # Catalog cold start: candidates proposed by the round-0 generation
        # discussion, projected into the artifact hypothesis shape.
        ledger_candidates = hypothesis_first_chain.list_hypothesis_candidates(
            team_id,
            question_id=normalized_question_id,
            workflow_run_id=normalized_workflow_run_id,
        )["candidates"]
        candidates = [
            {
                "hypothesis_id": str(item.get("candidateId") or ""),
                "statement": str(item.get("statement") or ""),
                "mechanism": str(item.get("rationale") or ""),
                "novelty_basis": "",
                "falsifiability": "",
                "predictions": [],
                "supporting_evidence_refs": [],
                "challenging_evidence_refs": [],
                "boundary_conditions": [],
            }
            for item in ledger_candidates
        ]

    scope = _selection_scope(team_id, normalized_question_id)
    mode = scope["mode"]

    latest_selection: dict[str, Any] | None = None
    try:
        latest_selection = hypothesis_selection.get_latest_hypothesis_selection(
            team_id,
            normalized_question_id,
            scope={
                **scope,
                "scopeHash": scope_hash_for(
                    program=scope["program"],
                    theme=scope["theme"],
                    campaign=scope["campaign"],
                    question=scope["question"],
                    branch=scope["branch"],
                    workflow=scope["workflow"],
                    agent_id=scope["agentId"],
                    mode=scope["mode"],
                ),
            },
            workflow_run_id=normalized_workflow_run_id,
        )["selection"]
    except hypothesis_selection.ResearchHypothesisSelectionNotFoundError:
        latest_selection = None

    review_meeting: dict[str, Any] | None = None
    generation_meeting: dict[str, Any] | None = None
    try:
        meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    except _DOMAIN_ERRORS:
        meetings = []
    for meeting in meetings:
        if not isinstance(meeting, dict):
            continue
        if str(meeting.get("question") or "").strip().upper() != normalized_question_id:
            continue
        if (
            normalized_workflow_run_id
            and hypothesis_first_chain._meeting_workflow_run_id(meeting)
            != normalized_workflow_run_id
        ):
            continue
        meeting_type = str(meeting.get("meetingType") or "")
        if meeting_type == "hypothesis_review":
            review_meeting = meeting
        elif meeting_type == "hypothesis_candidate_generation":
            generation_meeting = meeting

    return {
        "schemaVersion": 1,
        "teamId": team_id,
        "questionId": normalized_question_id,
        "workflowRunId": normalized_workflow_run_id,
        "scope": {
            key: scope[key]
            for key in ("program", "theme", "campaign", "question", "branch", "workflow", "agentId")
        },
        "mode": mode,
        "candidates": candidates,
        "defaultSelectedCandidateIds": [default_selected] if default_selected else [],
        "latestSelection": latest_selection,
        "reviewMeeting": review_meeting,
        "generationMeeting": generation_meeting,
    }


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/candidate-generation",
    status_code=status.HTTP_201_CREATED,
    response_model=MeetingRoundMutationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_candidate_generation_open(
    team_id: str,
    payload: dict[str, Any] | None = None,
) -> dict:
    """Open (or reuse) the round-0 candidate-generation discussion."""
    request = payload if isinstance(payload, dict) else {}
    question_id = str(request.get("questionId") or "").strip()
    workflow_run_id = str(request.get("workflowRunId") or "").strip()
    if not question_id:
        _raise_team_workflow_route_error(
            "hypothesis_first.candidate_generation.open",
            team_id,
            ContractValidationError("questionId is required"),
            status_code=422,
            fields={"questionId": question_id},
        )
    try:
        # A run-scoped entry must resolve the same grounded authority as the
        # v2 open_generation command: receipt authority, discussion scope and
        # — for stage-one runs — the formal grounded context.  A blocked
        # grounded context is a structured rejection, never a meeting with a
        # FORMAL authority and an empty evidence whitelist.
        launch = hypothesis_first_chain.resolve_stage_one_generation_launch(
            team_id,
            question_id,
            workflow_run_id,
        )
        return hypothesis_first_chain.open_candidate_generation_meeting(
            team_id,
            question_id,
            _model_invocation_receipt_authority=launch.get("receipt_authority"),
            _discussion_scope=launch.get("discussion_scope"),
            _candidate_authority=str(launch.get("candidate_authority") or ""),
            _generation_context=launch.get("generation_context"),
        )
    except hypothesis_first_chain.StageOneContextBlockedError as exc:
        _raise_team_workflow_route_error(
            "hypothesis_first.candidate_generation.open",
            team_id,
            exc,
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": str(exc),
                "blockers": exc.blockers,
            },
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.candidate_generation.open", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/run-reset-preview",
    response_model=QuestionRunResetPreviewResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_question_reset_preview(team_id: str, question_id: str) -> dict:
    """Read-only impact and active-work guard for the reset confirmation dialog."""
    try:
        return hypothesis_first_chain.preview_question_reset(team_id, question_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.question_reset.preview", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/run-reset",
    response_model=QuestionRunResetResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_question_reset(
    team_id: str,
    question_id: str,
    payload: QuestionRunResetPayload,
) -> dict:
    """Reset completed hypothesis-first working artifacts for exactly one question."""
    try:
        return hypothesis_first_chain.reset_question_chain(
            team_id,
            question_id,
            confirmation_question_id=payload.confirmationQuestionId,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.question_reset", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/experiment-retire-preview",
    response_model=QuestionExperimentRetirePreviewResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_question_retire_preview(
    team_id: str, question_id: str
) -> dict:
    """Read-only retire impact guard before removing an old experiment."""
    try:
        return challenge_question_retire.preview_question_retire(team_id, question_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.question_retire.preview", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/experiment-retire",
    response_model=QuestionExperimentRetireResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_question_retire(
    team_id: str,
    question_id: str,
    payload: QuestionExperimentRetirePayload,
) -> dict:
    """Retire one question's experiment across every question-owned store."""
    try:
        return challenge_question_retire.retire_question_experiment(
            team_id,
            question_id,
            confirmation_question_id=payload.confirmationQuestionId,
        )
    except challenge_question_retire.ChallengeQuestionRetirePartialError as exc:
        _raise_team_workflow_route_error(
            "hypothesis_first.question_retire",
            team_id,
            exc,
            status_code=500,
            detail={"code": exc.code, "message": str(exc), "result": exc.result},
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.question_retire", team_id, exc)


# ---------------------------------------------------------------------------
# Meeting rounds (HF-2)
# ---------------------------------------------------------------------------


@router.get(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds",
    response_model=MeetingRoundListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_list(team_id: str) -> dict:
    try:
        return meeting_rounds.list_meeting_rounds(team_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.list", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}",
    response_model=MeetingRoundResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_get(team_id: str, meeting_round_id: str) -> dict:
    try:
        return meeting_rounds.get_meeting_round(team_id, meeting_round_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.get", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/source-messages",
    response_model=MeetingSourceMessagesResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_source_messages(
    team_id: str,
    meeting_round_id: str,
) -> dict:
    try:
        record = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
            "meetingRound"
        ]
        messages = meeting_rounds.meeting_source_messages(record)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.source_messages", team_id, exc)
    return {
        "schemaVersion": 1,
        "teamId": team_id,
        "meetingRoundId": meeting_round_id,
        "messageCount": len(messages),
        "messages": messages,
    }


@router.post(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/summary",
    response_model=MeetingRoundMutationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_begin_summary(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingSummaryBeginPayload,
) -> dict:
    try:
        return meeting_rounds.begin_meeting_summary(
            team_id,
            meeting_round_id,
            actor=payload.actor,
            human_triggered=payload.humanTriggered,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.begin_summary", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/summary-draft",
    response_model=MeetingRoundMutationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_summary_draft(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingSummaryDraftRequest,
) -> dict:
    try:
        return meeting_runtime.prepare_meeting_summary_draft(
            team_id,
            meeting_round_id,
            actor=payload.actor,
            force=payload.force,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.summary_draft", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/digest-draft",
    response_model=MeetingRoundMutationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_submit_digest_draft(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingDigestDraftPayload,
) -> dict:
    try:
        return meeting_rounds.submit_meeting_digest_draft(
            team_id,
            meeting_round_id,
            payload.model_dump(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.submit_digest_draft", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/digest-reject",
    response_model=MeetingRoundMutationResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_reject_digest_draft(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingDigestRejectPayload,
) -> dict:
    try:
        return meeting_rounds.reject_meeting_digest_draft(
            team_id,
            meeting_round_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.reject_digest_draft", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/meeting-rounds/{meeting_round_id}/closure",
    response_model=CloseReviewMeetingResponse,
    response_model_exclude_unset=True,
)
def team_workflow_meeting_round_approve_closure(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingClosureApprovePayload,
) -> dict:
    """Generic meeting closure approval (no chain side effects)."""
    try:
        return meeting_rounds.approve_meeting_closure(
            team_id,
            meeting_round_id,
            payload.model_dump(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("meeting_round.approve_closure", team_id, exc)


# ---------------------------------------------------------------------------
# Hypothesis rounds (HF-3, read-only)
# ---------------------------------------------------------------------------


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-rounds",
    response_model=HypothesisRoundListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_round_list(team_id: str) -> dict:
    try:
        return hypothesis_rounds.list_hypothesis_rounds(team_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_round.list", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-rounds/{round_id}",
    response_model=HypothesisRoundResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_round_get(team_id: str, round_id: str) -> dict:
    try:
        return hypothesis_rounds.get_hypothesis_round(team_id, round_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_round.get", team_id, exc)


# ---------------------------------------------------------------------------
# Hypothesis-first chain (HF-4)
# ---------------------------------------------------------------------------


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/state",
    response_model=ChainStateResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_chain_state(
    team_id: str,
    question_id: str = Query(..., alias="questionId", min_length=1, max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    try:
        return hypothesis_first_chain.chain_state(
            team_id,
            question_id,
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.state", team_id, exc)


def _etag_matches(if_none_match: str | None, representation_version: str) -> bool:
    for token in str(if_none_match or "").split(","):
        normalized = token.strip()
        if normalized.startswith("W/"):
            normalized = normalized[2:].strip()
        if normalized.strip('"') == representation_version:
            return True
    return False


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/state-v2",
    response_model=HypothesisFirstStateV2,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_chain_state_v2(
    team_id: str,
    response: Response,
    question_id: str = Query(..., alias="questionId", min_length=1, max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    include_source_cursor: bool = Query(False, alias="includeSourceCursor"),
) -> dict | Response:
    try:
        snapshot = hypothesis_first_state_v2.project_hypothesis_first_state_v2(
            team_id,
            question_id,
            workflow_run_id=workflow_run_id,
            include_source_cursor=include_source_cursor,
        )
    except hypothesis_first_state_v2.HypothesisFirstStateScopeError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except hypothesis_first_state_v2.HypothesisFirstStateSourceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.state_v2", team_id, exc)

    representation_version = str(snapshot["representationVersion"])
    if include_source_cursor:
        response.headers["Cache-Control"] = "no-store"
        return snapshot
    etag = f'"{representation_version}"'
    if _etag_matches(if_none_match, representation_version):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, must-revalidate"
    return snapshot


_ANOMALY_GATE_WAIT_THRESHOLD_ENV = "VIBELUTION_ANOMALY_GATE_WAIT_THRESHOLD_MS"
_EVENT_PAGE_SIZE = 500
_KNOWLEDGE_INVOCATION_CREATED_EVENT_TYPE = "knowledge_invocation_created"


def _gate_wait_threshold_ms() -> int:
    """Configured human-gate wait threshold; env override is a positive int ms."""

    raw = str(os.environ.get(_ANOMALY_GATE_WAIT_THRESHOLD_ENV) or "").strip()
    if raw:
        try:
            normalized = int(raw)
        except ValueError:
            normalized = 0
        if normalized > 0:
            return normalized
    return anomaly_inbox_service.DEFAULT_GATE_WAIT_THRESHOLD_MS


def _meeting_scope_question_id(meeting: Mapping[str, Any]) -> str:
    """The question a meeting round belongs to (record or discussion scope)."""

    direct = str(meeting.get("questionId") or "").strip().upper()
    if direct:
        return direct
    for scope_key in ("discussionScope", "preformalDiscussionScope", "scope"):
        scope = meeting.get(scope_key)
        if isinstance(scope, Mapping):
            scoped = str(scope.get("questionId") or "").strip().upper()
            if scoped:
                return scoped
    return ""


def _collect_digest_ttl_overdues(team_id: str, question_id: str) -> list[dict[str, Any]]:
    """Read-only digest-TTL stop-loss signals for one question.

    判定口径完全复用 meeting runtime 的 ``meeting_digest_ttl_mute_state``
    （同一 TTL 配置、同一 deadline 优先语义）；这里只负责按题目归属过滤并
    附上 ``meetingRoundId``。任何读取失败都降级为「无信号」，绝不阻塞收件箱。
    """

    normalized_question_id = str(question_id or "").strip().upper()
    if not normalized_question_id:
        return []
    try:
        listing = meeting_rounds.list_meeting_rounds(
            team_id, status=("summarizing", "awaiting_approval")
        )
    except Exception:  # noqa: BLE001 - an unavailable meeting store is not an inbox error
        return []
    overdues: list[dict[str, Any]] = []
    for meeting in listing.get("meetings") or []:
        if not isinstance(meeting, Mapping):
            continue
        if _meeting_scope_question_id(meeting) != normalized_question_id:
            continue
        try:
            mute = meeting_runtime.meeting_digest_ttl_mute_state(meeting)
        except Exception:  # noqa: BLE001 - one unreadable meeting must not break the rest
            continue
        if not mute:
            continue
        round_id = str(meeting.get("meetingRoundId") or "").strip()
        if round_id:
            overdues.append({**dict(mute), "meetingRoundId": round_id})
    return overdues


def _iso_from_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _collect_budget_precheck_blocks(
    team_id: str, snapshot: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Read-only ``budget_precheck_blocked`` payloads for the blocked run.

    The state-v2 snapshot pins the current formal run to ``blocked`` but does
    not carry the structured stage-boundary problem, so the route replays the
    run's ledger tail (last ``_EVENT_PAGE_SIZE`` events) and collects the
    precheck payloads.  Budget prechecks may also block inside a knowledge
    sideflow child run: those child run ids are resolved from the
    ``knowledge_invocation_created`` events in the formal tail and each child
    tail is replayed the same way (with ``runId`` pointing at the child run,
    so the extend CTA targets the run that actually owns the block).  Each
    replay fails soft on its own — one unreadable ledger never fails the
    inbox, and one unreadable child never hides the others.

    The tail window keeps EVERY ``budget_precheck_blocked`` event, so a block
    whose node has since been extended and retried to success would keep
    rendering a live extend CTA for an already-succeeded node (and co-render
    with the next node's fresh block, letting the arm→confirm flow hit the
    wrong item).  Each tail is therefore filtered to blocks that are still
    CURRENTLY blocking: see ``_drop_stale_budget_blocks``.
    """

    formal = snapshot.get("formalRuntime")
    if not isinstance(formal, Mapping):
        return []
    run_id = str(formal.get("runId") or "").strip()
    if not run_id or str(formal.get("runStatus") or "").strip().lower() != "blocked":
        return []
    replay = get_event_replay_service()

    def _drop_stale_budget_blocks(
        ordered_events: Sequence[Any],
        block_slots: list[tuple[int, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Keep only blocks whose node is still currently blocked on budget.

        Ground truth from the live ledger (run with evidence_relations then
        knowledge_ingestion precheck blocks): the graph worker commits the
        block BEFORE the attempt ever starts, and when the operator extends
        budget and retries, progression is recorded by a later
        ``node_starting`` for a newer attempt of the same node; the
        adapter-worker path also appends ``node_succeeded`` ledger events,
        while the graph-worker path only flips the ``node_attempts`` status
        (no ledger event) before the NEXT node's precheck fires.  A block is
        therefore stale — and dropped — when a LATER event in the same tail
        proves the node moved past it:

        - ``node_starting`` for the same node on a newer attempt (the blocked
          attempt never started; a newer attempt means the retry began);
        - ``node_succeeded`` attributed to this node via the
          ``nodeRunId → nodeId`` map built from ``node_starting`` and precheck
          payloads (unattributable successes fail visible and keep the item);
        - a newer ``budget_precheck_blocked`` for a DIFFERENT node of the
          same run (that precheck only fires after this node's newer attempt
          succeeded, so the run advanced past this block);
        - ``run_succeeded`` (the run reached terminal; nothing is blocked).

        Remaining same-node re-blocks dedupe to the newest entry.  Filtering
        runs per run tail, so knowledge child-run blocks keep their own
        ``runId`` scope (defect-⑧ behaviour untouched).
        """

        if not block_slots:
            return []
        node_by_node_run: dict[str, str] = {}
        for event in ordered_events:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            node_run_id = str(payload.get("nodeRunId") or "")
            node_id = str(payload.get("nodeId") or "")
            if node_run_id and node_id:
                node_by_node_run.setdefault(node_run_id, node_id)

        def _is_stale(slot: int, entry: dict[str, Any]) -> bool:
            node_id = str(entry.get("nodeId") or "")
            blocked_node_run = str(entry.get("nodeRunId") or "")
            for event in ordered_events[slot + 1 :]:
                event_type = str(event.event_type)
                payload = event.payload if isinstance(event.payload, Mapping) else {}
                if event_type == "run_succeeded":
                    return True
                if event_type == "node_starting":
                    if (
                        str(payload.get("nodeId") or "") == node_id
                        and str(payload.get("nodeRunId") or "") != blocked_node_run
                    ):
                        return True
                elif event_type == "node_succeeded":
                    later_node_run = str(payload.get("nodeRunId") or "")
                    if (
                        later_node_run
                        and node_by_node_run.get(later_node_run) == node_id
                    ):
                        return True
                elif (
                    event_type
                    == anomaly_inbox_service.BUDGET_PRECHECK_BLOCKED_EVENT_TYPE
                    and str(payload.get("nodeId") or "") != node_id
                ):
                    return True
            return False

        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for slot, entry in block_slots:
            if _is_stale(slot, entry):
                continue
            key = (str(entry.get("runId") or ""), str(entry.get("nodeId") or ""))
            deduped[key] = entry  # later (newest) surviving block wins
        return list(deduped.values())

    def _tail_blocks_and_children(
        target_run_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        probe = replay.list_events(team_id=team_id, run_id=target_run_id, limit=1)
        after = max(0, int(probe.latest_event_sequence) - _EVENT_PAGE_SIZE)
        page = replay.list_events(
            team_id=team_id, run_id=target_run_id, after_sequence=after, limit=_EVENT_PAGE_SIZE
        )
        ordered_events = list(page.events)
        block_slots: list[tuple[int, dict[str, Any]]] = []
        child_run_ids: list[str] = []
        for slot, event in enumerate(ordered_events):
            event_type = str(event.event_type)
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            if event_type == _KNOWLEDGE_INVOCATION_CREATED_EVENT_TYPE:
                child_run_id = str(payload.get("childRunId") or "").strip()
                if child_run_id and child_run_id not in child_run_ids:
                    child_run_ids.append(child_run_id)
            if event_type != (
                anomaly_inbox_service.BUDGET_PRECHECK_BLOCKED_EVENT_TYPE
            ):
                continue
            block_slots.append(
                (
                    slot,
                    {
                        **dict(payload),
                        "runId": target_run_id,
                        "nodeId": str(payload.get("nodeId") or ""),
                        "occurredAt": _iso_from_ms(event.occurred_at_ms),
                    },
                )
            )
        return _drop_stale_budget_blocks(ordered_events, block_slots), child_run_ids

    try:
        blocks, child_run_ids = _tail_blocks_and_children(run_id)
    except Exception:  # noqa: BLE001 - an unavailable ledger is not an inbox error
        return []
    for child_run_id in child_run_ids:
        try:
            child_blocks, _ = _tail_blocks_and_children(child_run_id)
        except Exception:  # noqa: BLE001 - one unreadable child must not break the rest
            continue
        blocks.extend(child_blocks)
    return blocks


def _resolve_run_version(team_id: str, run_id: str) -> int:
    """Current ledger run version for CAS; 0 when the run cannot be seen.

    Knowledge sideflow child runs belong to their own workflow listing, so a
    miss in the challenge-cup listing falls back to that listing.  Both
    lookups fail soft; only when neither listing resolves the run does this
    return 0.
    """

    for workflow_id in (
        _challenge_workflow_id(),
        _knowledge_sideflow_workflow_id(),
    ):
        try:
            listing = get_query_service().list_runs(
                team_id=team_id,
                workflow_id=workflow_id,
            )
        except Exception:  # noqa: BLE001 - resolution failure is mapped by the caller
            continue
        for record in listing.get("runs") or []:
            if (
                isinstance(record, Mapping)
                and str(record.get("runId") or "").strip() == run_id
            ):
                version = record.get("runVersion")
                return int(version) if isinstance(version, int) and version > 0 else 0
    return 0


def _challenge_workflow_id() -> str:
    from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID

    return CHALLENGE_CUP_WORKFLOW_ID


def _knowledge_sideflow_workflow_id() -> str:
    from core.research.workflow.knowledge_sideflow_definition import (
        KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    )

    return KNOWLEDGE_SIDEFLOW_WORKFLOW_ID


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/anomaly-inbox",
    response_model=AnomalyInboxResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_anomaly_inbox(
    team_id: str,
    question_id: str = Query("", alias="questionId", max_length=200),
) -> dict:
    """R4.3 anomaly inbox: one read-only projection for the operations console.

    薄路由：把该题目的 canonical state-v2 快照交给纯投影服务
    ``build_anomaly_inbox``，并附上三类「无推送断点」的只读信号——
    digest 审批 TTL 止损（口径复用 meeting runtime）、人工门等待超阈值
    （knowledge_handoff / H1-H4，阈值可配）、阶段预算预检阻塞（带
    extend_budget CTA action）。响应在合同投影之上只增不删
    （``attach_inbox_actions``），排序/合并/完整性全部由合同保证。
    未给 questionId 时返回合法的空收件箱（无信号的合法状态）。
    """

    normalized_question_id = question_id.strip().upper()
    if not normalized_question_id:
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "questionId": "",
            "inbox": AnomalyInbox.empty().to_dict(),
        }
    try:
        snapshot = hypothesis_first_state_v2.project_hypothesis_first_state_v2(
            team_id,
            normalized_question_id,
        )
    except hypothesis_first_state_v2.HypothesisFirstStateScopeError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except hypothesis_first_state_v2.HypothesisFirstStateSourceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.anomaly_inbox", team_id, exc)
    budget_precheck_blocks = _collect_budget_precheck_blocks(team_id, snapshot)
    inbox = anomaly_inbox_service.build_anomaly_inbox(
        snapshot,
        digest_ttl_overdues=_collect_digest_ttl_overdues(
            team_id, normalized_question_id
        ),
        gate_waits=anomaly_inbox_service.derive_gate_waits(snapshot),
        budget_precheck_blocks=budget_precheck_blocks,
        gate_wait_threshold_ms=_gate_wait_threshold_ms(),
    )
    return {
        "schemaVersion": 1,
        "teamId": team_id,
        "questionId": normalized_question_id,
        "inbox": anomaly_inbox_service.attach_inbox_actions(
            inbox.to_dict(),
            blocks=budget_precheck_blocks,
        ),
    }


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/round-failures",
    response_model=dict[str, Any],
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_round_failure_list(
    team_id: str,
    unresolved_only: bool = Query(True, alias="unresolvedOnly"),
) -> dict:
    """Open round-generation failure traces for the workspace recovery panel.

    薄路由：直接返回 ``hypothesis_rounds`` 的失败账本（latest-per-failure），
    默认只列 open（failed/blocked）；``blocked`` 是纯 fan-in 等待，面板据此
    隐藏按钮。写路径不在本路由：人工重试走
    ``round-failures/{failure_id}/retry``。
    """

    try:
        return hypothesis_rounds.list_hypothesis_round_failures(
            team_id, unresolved_only=unresolved_only
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.round_failures", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/round-failures/{failure_id}/retry",
    response_model=dict[str, Any],
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_round_failure_retry(
    team_id: str,
    failure_id: str,
    payload: RoundFailureRetryRequest,
    http_request: Request,
) -> dict:
    """Accept one confirmed manual retry of an open round failure trace.

    误触防护在服务端闭合：缺少 ``confirmed=true`` 直接 428 拒绝。重新生成轮
    是分钟级 review-LLM 路径，端点只接受请求并立即返回 ``accepted``（或
    同 trace 的 ``in_flight``），由后台 worker 复用自动推进同一条
    ``regenerate_hypothesis_round`` 命令路径执行；成功后按既有语义 resolve
    对应的 open 失败记录，面板重新拉取账本即可。``blocked``（纯等待，无
    可执行重试）返回 409 ``not_retryable``；未知或已解决返回 404。
    """

    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "confirmation_required",
                "message": "round failure retry requires confirmed=true",
            },
        )
    try:
        with server_operator_scope_from_http(http_request):
            result = hypothesis_first_chain.request_round_failure_recovery(
                team_id, failure_id
            )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.round_failure_retry", team_id, exc)
    result_status = str((result or {}).get("status") or "")
    if result_status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "round_failure_not_found",
                "message": f"open round failure {failure_id} not found",
            },
        )
    if result_status == "not_retryable":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": str((result or {}).get("reasonCode") or "not_retryable"),
                "message": (
                    "this failure is a structured fan-in wait; closing the "
                    "pending sibling reviews advances it automatically"
                ),
            },
        )
    return result


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/anomaly-inbox/actions/extend-budget",
    response_model=dict[str, Any],
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_anomaly_inbox_extend_budget(
    team_id: str,
    payload: AnomalyInboxExtendBudgetRequest,
    request: Request,
) -> dict:
    """Execute the inbox one-click extend CTA (human-authorized, confirmed).

    误触防护在服务端闭合：缺少显式 ``confirmed=true``、额度数字无效或
    run/stage 缺失时直接拒绝（428/422 语义），绝不静默执行。新上限按
    overrun-aware 基线计算（准入只在节点边界拦截，已消耗可能已超过配置
    上限）：``max(stageLimitTokens, stageConsumedTokens) +
    suggestedExtensionTokens``；幂等键由 run/stage/新总额决定，因此同一
    确认重复提交会幂等重放而不是重复加预算，且旧命令不会以不足的新上限
    被重放命中。extend 只提高 stageTokens 上限，随后对该节点的
    retry_node 仍走既有命令授权面（本端点不自动补预算、不自动重试）。
    ``questionId`` 只作请求上下文；命令授权由 team+run 的既有命令面完成。
    """

    try:
        anomaly_inbox_service.assert_extend_budget_confirmation(
            confirmed=payload.confirmed,
            run_id=payload.runId,
            stage_id=payload.stageId,
            stage_limit_tokens=payload.stageLimitTokens,
            suggested_extension_tokens=payload.suggestedExtensionTokens,
        )
    except anomaly_inbox_service.InboxActionConfirmationError as exc:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    expected_run_version = payload.expectedRunVersion or _resolve_run_version(
        team_id, payload.runId
    )
    if expected_run_version < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "run_not_found",
                "message": f"workflow run {payload.runId} not found",
            },
        )
    new_stage_tokens = (
        max(payload.stageLimitTokens, payload.stageConsumedTokens)
        + payload.suggestedExtensionTokens
    )
    idempotency_key = (
        f"inbox-extend-budget:{payload.runId}:{payload.stageId}"
        f":{new_stage_tokens}"
    )
    return _submit_workflow_command(
        run_id=payload.runId,
        team_id=team_id,
        kind=WorkflowCommandKind.EXTEND_BUDGET,
        node_id=payload.nodeId or None,
        expected_run_version=expected_run_version,
        idempotency_key=idempotency_key,
        payload={
            "limits": {"stageTokens": {payload.stageId: new_stage_tokens}},
            "recovery": {"command": "extend_budget", "then": "retry_node"},
        },
        request=request,
    )


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/commands",
    response_model=dict[str, Any],
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_command(
    team_id: str,
    payload: HypothesisFirstCommandRequest,
    http_request: Request,
    question_id: str = Query("", alias="questionId", max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    """Execute one server-authorized V2 command with scope-lock CAS.

    The command is re-authorized from the latest V2 ``allowedActions`` inside
    the owning orchestration lock.  Clients send only the action envelope and
    declaration input; labels and target metadata are never trusted.

    SCI-049: the three long paths (open/retry generation, record selection,
    approve summary) return an ``accepted`` envelope with a
    ``commandAttemptId`` immediately and finish on a background worker; the
    client polls ``GET .../chain/command-attempts/{attemptId}`` until the
    attempt reaches a terminal status.  Every other command stays synchronous.
    """

    try:
        with server_operator_scope_from_http(http_request):
            # ``_find_allowed_command`` re-authorizes by strict payload
            # equality against the projected offer.  Wire models with
            # defaulted fields (RecordSelectionPayload.previousSelectionId,
            # OpenGenerationPayload.runId) inject those defaults into a plain
            # dump, so a verbatim echo of a two-key offer would gain a third
            # key and never re-authorize.  ``exclude_unset`` keeps the request
            # wire-symmetric with the response side's
            # ``response_model_exclude_unset``: only client-declared fields
            # reach the command envelope.  The same envelope feeds the async
            # gate below and the synchronous fallback.
            command_request = payload.model_dump(exclude_unset=True)
            accepted = hypothesis_first_chain.submit_v2_command_async(
                team_id,
                command_request,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
            )
            if accepted is not None:
                return accepted
            return hypothesis_first_chain.execute_v2_command(
                team_id,
                command_request,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
            )
    except hypothesis_first_chain.StateVersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "expectedStateVersion": exc.expected,
                "actualStateVersion": exc.actual,
                "snapshotUrl": exc.snapshot_path,
            },
        ) from exc
    except hypothesis_first_chain.IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "actionId": exc.action_id,
                "idempotencyKey": exc.idempotency_key,
                "expectedInputDigest": exc.expected_input_digest,
                "actualInputDigest": exc.actual_input_digest,
            },
        ) from exc
    except hypothesis_first_chain.CommandAttemptInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "questionId": exc.question_id,
                "runningCommand": exc.command,
                "runningActionId": exc.action_id,
            },
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "command_forbidden",
                "message": str(exc) or "command_forbidden",
            },
        ) from exc
    except hypothesis_first_chain.FormalCommandRejectedError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.blockers:
            detail["blockers"] = exc.blockers
        _raise_team_workflow_route_error(
            "hypothesis_first.command",
            team_id,
            exc,
            status_code=exc.status_code,
            detail=detail,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.command", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/command-attempts/{attempt_id}",
    response_model=dict[str, Any],
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_command_attempt(
    team_id: str,
    attempt_id: str,
) -> dict:
    """Read one async command attempt's delivery status (SCI-049 poll API).

    Returns the attempt's ``status`` (``queued``/``running``/``succeeded``/
    ``failed``); a succeeded attempt carries the exact response ``result`` the
    synchronous execution would have returned, and a failed one carries a
    structured ``error`` with the original domain code so the UI can render
    the same messages as before.
    """

    try:
        return hypothesis_first_chain.get_v2_command_attempt(team_id, attempt_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.command_attempt", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/collection-requests",
    response_model=CollectionRequestListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_collection_requests(
    team_id: str,
    question_id: str = Query("", alias="questionId", max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    try:
        return hypothesis_first_chain.list_collection_requests(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.collection_requests", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/review-round-links",
    response_model=ReviewRoundLinkListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_review_round_links(
    team_id: str,
    question_id: str = Query("", alias="questionId", max_length=200),
    workflow_run_id: str = Query("", alias="runId", max_length=200),
) -> dict:
    try:
        return hypothesis_first_chain.list_review_round_links(
            team_id,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.review_round_links", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/review-meetings/{meeting_round_id}/close",
    response_model=CloseReviewMeetingResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_close_review_meeting(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingClosureApprovePayload,
) -> dict:
    """Close one hypothesis-review meeting and apply chain effects."""
    try:
        return hypothesis_first_chain.close_review_meeting(
            team_id,
            meeting_round_id,
            payload.model_dump(),
            runtime=production_workflow_runtime(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.close_review_meeting", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/review-meetings/{meeting_round_id}/reopen",
    response_model=CloseReviewMeetingResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_reopen_review_meeting(
    team_id: str,
    meeting_round_id: str,
) -> dict:
    """Restart one review round whose discussion produced no successful speech."""
    try:
        return hypothesis_first_chain.reopen_failed_review_meeting(
            team_id,
            meeting_round_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.reopen_review_meeting", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/review-meetings/{meeting_round_id}/next-round",
    response_model=ReviewNextRoundResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_next_review_round(
    team_id: str,
    meeting_round_id: str,
) -> dict:
    """Open the next review round after a closed one, budget-gated.

    The sanctioned recovery path when a closed round still needs more
    discussion or an evidence request: closed meetings are immutable, so the
    operator opens the next round instead of rewriting the closure.
    """
    try:
        return hypothesis_first_chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=meeting_round_id,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.next_review_round", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/meetings/{meeting_round_id}/approve-digest",
    response_model=CloseReviewMeetingResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_approve_digest(
    team_id: str,
    meeting_round_id: str,
    payload: MeetingApproveDigestPayload,
) -> dict:
    try:
        return hypothesis_first_chain.approve_meeting_digest(
            team_id,
            meeting_round_id,
            closed_by=payload.closedBy,
            expected_digest_content_hash=payload.expectedDigestContentHash,
            runtime=production_workflow_runtime(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.approve_digest", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/collection-requests/{request_id}/handoff",
    response_model=CollectionHandoffResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_collection_handoff(
    team_id: str,
    request_id: str,
    payload: CollectionHandoffPayload,
) -> dict:
    try:
        return hypothesis_first_chain.record_collection_handoff(
            team_id,
            request_id,
            handoff_ref=payload.handoffRef,
            runtime=production_workflow_runtime(),
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.collection_handoff", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/collection-requests/{request_id}/recover",
    response_model=CollectionHandoffResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_collection_recover(
    team_id: str,
    request_id: str,
) -> dict:
    """Bind/reuse the child run and restart an orphaned collection request."""
    try:
        return hypothesis_first_chain.recover_collection_request(team_id, request_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.collection_recover", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/evidence-gap-markers/{marker_id}/clear",
    response_model=ClearEvidenceGapMarkerResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_clear_evidence_gap_marker(
    team_id: str,
    marker_id: str,
    payload: ClearEvidenceGapMarkerPayload,
) -> dict:
    """Clear one evidence-gap marker so the same goal can be re-collected.

    Operator retry path for ``evidence_gap_unavailable`` verdicts: after a
    remediation that changes what is retrievable (for example the quote-anchor
    abstract-level degradation), clearing the marker lets the next identical
    evidence request run a fresh search instead of being stopped by the
    circuit.  The response carries an operator-facing retryHint.
    """
    try:
        return hypothesis_first_chain.clear_evidence_gap_marker(
            team_id,
            marker_id,
            reason=payload.reason,
        )
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.clear_evidence_gap_marker", team_id, exc)
