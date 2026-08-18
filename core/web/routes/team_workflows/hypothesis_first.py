"""Team workflow routes: hypothesis-first flow (HF-5).

薄路由层：selection（HF-1）、meeting rounds（HF-2 四态关门流）、
hypothesis rounds（HF-3 查询）与 chain 编排（HF-4）的 HTTP 透传。
业务语义、状态机与 fail-closed 校验一律留在
``core/web/services/team_workflow/`` 的 service 层；route 只做边界校验、
DTO 转换与错误映射。UI 的完成态一律来自服务端投影（chain state /
round 记录），不由客户端推断。
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import Query, status

from core.research.workflow.contracts import ContractValidationError
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow import (
    hypothesis_rounds,
    hypothesis_selection,
    meeting_rounds,
)
from core.web.services.team_workflow.challenge_question_runs import (
    get_challenge_question_run_detail,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
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
from .hypothesis_first_models import (
    ChainStateResponse,
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
    MeetingClosureApprovePayload,
    MeetingDigestDraftPayload,
    MeetingDigestRejectPayload,
    MeetingRoundListResponse,
    MeetingRoundMutationResponse,
    MeetingRoundResponse,
    MeetingSourceMessagesResponse,
    MeetingSummaryBeginPayload,
    ReviewRoundLinkListResponse,
    SelectionContextResponse,
)

_HYPOTHESIS_FIRST_WORKFLOW = "hypothesis_first"
_DEFAULT_BRANCH = "main"
_OPERATOR_AGENT_ID = "operator"


def _map_domain_error(action: str, team_id: str, exc: Exception) -> NoReturn:
    """Map service exceptions to HTTP errors with route-error diagnostics."""
    if isinstance(exc, TeamNotFoundError):
        status_code = 404
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
    hypothesis_selection.ResearchHypothesisSelectionError,
    meeting_rounds.ResearchMeetingRoundError,
    hypothesis_rounds.ResearchHypothesisRoundError,
    hypothesis_first_chain.HypothesisFirstChainError,
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
) -> dict:
    try:
        return hypothesis_selection.list_hypothesis_selections(
            team_id,
            question_id=question_id,
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
) -> dict:
    try:
        return hypothesis_selection.get_latest_hypothesis_selection(
            team_id,
            question_id,
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
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/questions/{question_id}/selection-context",
    response_model=SelectionContextResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_selection_context(
    team_id: str,
    question_id: str,
) -> dict:
    """Derive the server-authoritative scope + candidates for the selection UI.

    scope 六元组由冻结节目核心（questionId → theme/campaign）与 theme 激活
    台账推导；候选假说来自赛题 artifact。UI 回显该 scope 提交选择，不在
    客户端自行拼装。
    """
    normalized_question_id = question_id.strip().upper()
    try:
        detail = get_challenge_question_run_detail(team_id, normalized_question_id)
    except TeamNotFoundError as exc:
        _map_domain_error("hypothesis_first.selection.context", team_id, exc)
    except ValueError as exc:
        _raise_team_workflow_route_error(
            "hypothesis_first.selection.context",
            team_id,
            exc,
            status_code=404,
            fields={"questionId": normalized_question_id},
        )
    output = detail.get("output") if isinstance(detail.get("output"), dict) else {}
    hypotheses = output.get("hypotheses") if isinstance(output.get("hypotheses"), list) else []
    candidates = [
        item
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("hypothesis_id") or "").strip()
    ]
    selection_section = output.get("selection") if isinstance(output.get("selection"), dict) else {}
    default_selected = str(selection_section.get("selected_hypothesis_id") or "").strip()

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

    latest_selection: dict[str, Any] | None = None
    try:
        latest_selection = hypothesis_selection.get_latest_hypothesis_selection(
            team_id,
            normalized_question_id,
        )["selection"]
    except hypothesis_selection.ResearchHypothesisSelectionNotFoundError:
        latest_selection = None

    review_meeting: dict[str, Any] | None = None
    try:
        meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    except _DOMAIN_ERRORS:
        meetings = []
    for meeting in meetings:
        if not isinstance(meeting, dict):
            continue
        if str(meeting.get("meetingType") or "") != "hypothesis_review":
            continue
        if str(meeting.get("question") or "").strip().upper() != normalized_question_id:
            continue
        review_meeting = meeting

    return {
        "schemaVersion": 1,
        "teamId": team_id,
        "questionId": normalized_question_id,
        "scope": {
            "program": contract.programId,
            "theme": contract.themeId,
            "campaign": contract.campaignId,
            "question": normalized_question_id,
            "branch": _DEFAULT_BRANCH,
            "workflow": _HYPOTHESIS_FIRST_WORKFLOW,
            "agentId": _OPERATOR_AGENT_ID,
        },
        "mode": mode,
        "candidates": candidates,
        "defaultSelectedCandidateIds": [default_selected] if default_selected else [],
        "latestSelection": latest_selection,
        "reviewMeeting": review_meeting,
    }


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
) -> dict:
    try:
        return hypothesis_first_chain.chain_state(team_id, question_id)
    except _DOMAIN_ERRORS as exc:
        _map_domain_error("hypothesis_first.chain.state", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/hypothesis-first/chain/collection-requests",
    response_model=CollectionRequestListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_hypothesis_first_collection_requests(
    team_id: str,
    question_id: str = Query("", alias="questionId", max_length=200),
) -> dict:
    try:
        return hypothesis_first_chain.list_collection_requests(
            team_id,
            question_id=question_id,
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
) -> dict:
    try:
        return hypothesis_first_chain.list_review_round_links(
            team_id,
            question_id=question_id,
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
