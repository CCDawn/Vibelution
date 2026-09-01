"""Pydantic models for the hypothesis-first team workflow routes.

DTO 只做边界校验与字段声明；业务语义校验一律留在
``core/web/services/team_workflow/`` 的 service 层（fail closed）。
响应模型保留稳定顶层字段并允许额外键透传 service 返回的完整记录。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

# ---------------------------------------------------------------------------
# Payloads — selection (HF-1)
# ---------------------------------------------------------------------------


class HypothesisSelectionRecordPayload(BaseModel):
    """Payload for ``POST /teams/{team_id}/hypothesis-first/selections``.

    完整 scope 六元组由调用方（UI 经 selection-context 端点、或 HF-7 端到端
    编排）提供，route 原样透传给 service；service 对空 scope fail closed。
    """

    program: str = Field(..., min_length=1, max_length=200)
    theme: str = Field(..., min_length=1, max_length=200)
    campaign: str = Field(..., min_length=1, max_length=200)
    question: str = Field(..., min_length=1, max_length=200)
    branch: str = Field("main", min_length=1, max_length=200)
    workflow: str = Field("hypothesis_first", min_length=1, max_length=200)
    agentId: str = Field(..., min_length=1, max_length=200)
    mode: str = Field("formal", max_length=50)
    workflowRunId: str = Field("", max_length=200)
    questionId: str = Field(..., min_length=1, max_length=200)
    selectedCandidateIds: list[str] = Field(..., min_length=2, max_length=16)
    previousSelectionId: str = Field("", max_length=200)
    decidedBy: str = Field(..., min_length=1, max_length=200)
    createdAt: str = Field("", max_length=50)
    selectionId: str = Field("", max_length=200)


# ---------------------------------------------------------------------------
# Payloads — meeting rounds (HF-2)
# ---------------------------------------------------------------------------


class MeetingSummaryBeginPayload(BaseModel):
    """Payload for ``POST /meeting-rounds/{meeting_round_id}/summary``."""

    actor: str = Field("", max_length=200)
    humanTriggered: bool = False


class MeetingSummaryDraftRequest(BaseModel):
    """Payload for ``POST /meeting-rounds/{meeting_round_id}/summary-draft``."""

    actor: str = Field("", max_length=200)
    force: bool = False


class MeetingSearchEnvelopeDraft(BaseModel):
    """Typed search envelope inside a digest evidence request."""

    model_config = ConfigDict(extra="allow")

    keywords: list[str] = Field(default_factory=list)
    sourceTypes: list[str] = Field(default_factory=list)
    evidenceLevels: list[str] = Field(default_factory=list)


class MeetingEvidenceRequestDraft(BaseModel):
    """Typed evidence-request row on a meeting digest draft."""

    model_config = ConfigDict(extra="allow")

    rationale: str = Field("", max_length=10000)
    candidateRefs: list[str] = Field(default_factory=list)
    evidenceRefs: list[str] = Field(default_factory=list)
    searchEnvelope: MeetingSearchEnvelopeDraft = Field(
        default_factory=MeetingSearchEnvelopeDraft
    )
    requirements: dict[str, Any] = Field(default_factory=dict)
    writebackPolicy: dict[str, Any] = Field(default_factory=dict)


class MeetingDigestDraftPayload(BaseModel):
    """Payload for ``POST /meeting-rounds/{meeting_round_id}/digest-draft``.

    章节键集合对齐 ``MeetingDigest`` 契约；service 侧
    ``_validate_digest_draft`` 对必需章节 fail closed。
    """

    summary: str = Field(..., min_length=1, max_length=10000)
    discussionTopics: list[str] = Field(default_factory=list)
    agendaSummary: str = Field("", max_length=10000)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[dict[str, Any]] = Field(default_factory=list)
    actionItems: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    knowledgeCandidates: list[str] = Field(default_factory=list)
    proposedCandidates: list[dict[str, Any]] = Field(default_factory=list)
    evidenceRequests: list[MeetingEvidenceRequestDraft] = Field(default_factory=list)
    validationErrors: list[dict[str, Any]] = Field(default_factory=list)
    sourceMessageRefs: list[str] = Field(..., min_length=1)
    sourceMessageContentHash: str = Field("", max_length=200)
    contentHash: str = Field("", max_length=200)


class MeetingDigestRejectPayload(BaseModel):
    """Payload for ``POST /meeting-rounds/{meeting_round_id}/digest-reject``."""

    actor: str = Field("", max_length=200)
    reason: str = Field("", max_length=2000)


# ---------------------------------------------------------------------------
# Payloads — meeting closure (HF-2) & hypothesis-first chain (HF-4)
# ---------------------------------------------------------------------------


class MeetingDecisionPayload(BaseModel):
    """One decision item inside a meeting-closure payload.

    字段对齐 ``DecisionRecord.from_dict`` 与 chain
    ``_process_collection_decisions`` 读取的原始键（``searchEnvelope`` 等仅由
    chain 在关门时瞬时消费，不落 DecisionRecord）。
    """

    decision: str = Field(..., min_length=1, max_length=100)
    rationale: str = Field(..., min_length=1, max_length=10000)
    decidedBy: str = Field(..., min_length=1, max_length=200)
    candidateRefs: list[str] = Field(default_factory=list)
    evidenceRefs: list[str] = Field(default_factory=list)
    status: str = Field("adopted", max_length=50)
    searchEnvelope: dict[str, Any] | None = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    writebackPolicy: dict[str, Any] | None = None


class MeetingApproveDigestPayload(BaseModel):
    """Payload for ``POST .../chain/meetings/{id}/approve-digest``."""

    closedBy: str = Field(..., min_length=1, max_length=200)
    expectedDigestContentHash: str = Field(..., min_length=1, max_length=200)


class ReviewNextRoundResponse(BaseModel):
    """Result of opening the next review round for a selection.

    ``status`` is ``opened``、``reused`` 或 ``budget_exhausted``；``meetingRound``
    仅在新开/复用时返回。
    """

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    selectionId: str = ""
    previousMeetingRoundId: str = ""
    collectionRequestId: str = ""
    roundIndex: int = 0
    budget: int = 0
    meetingRound: dict[str, Any] = Field(default_factory=dict)


class MeetingClosureApprovePayload(BaseModel):
    """Payload for meeting closure approval (generic + chain close).

    ``approve_meeting_closure`` 与 ``close_review_meeting`` 消费同一份
    closure payload；chain 版本额外触发搜集/轮次/恢复副作用。
    """

    decisions: list[MeetingDecisionPayload] = Field(..., min_length=1)
    closedBy: str = Field("", max_length=200)


class CollectionHandoffPayload(BaseModel):
    """Payload for ``POST .../chain/collection-requests/{request_id}/handoff``."""

    handoffRef: str = Field("", max_length=500)


class QuestionRunResetPayload(BaseModel):
    """Typed confirmation for a destructive, question-scoped reset."""

    confirmationQuestionId: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Responses — keys mirror the service return dicts; extra keys pass through.
# Routes must use response_model_exclude_unset=True so fields the service did
# not return stay absent instead of being filled with defaults.
# ---------------------------------------------------------------------------


class HypothesisSelectionRecordResponse(BaseModel):
    """Result of ``record_hypothesis_selection`` (created / reused)."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    selection: dict[str, Any] = Field(default_factory=dict)
    reviewMeeting: dict[str, Any] | None = None
    storagePath: str = ""


class HypothesisSelectionResponse(BaseModel):
    """Single hypothesis selection record response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    selection: dict[str, Any] = Field(default_factory=dict)
    storagePath: str = ""


class HypothesisSelectionListResponse(BaseModel):
    """Selection history response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    selectionCount: int = 0
    selections: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""


class CandidateEvidenceEntry(BaseModel):
    """One cited discussion excerpt for a candidate (PaperQA2-style trail)."""

    meetingRoundId: str = ""
    meetingLabel: str = ""
    messageId: str = ""
    speaker: str = ""
    excerpt: str = ""
    createdAt: str = ""


class CandidateEvidenceTrail(BaseModel):
    candidateId: str
    entries: list[CandidateEvidenceEntry] = Field(default_factory=list)


class CandidateEvidenceTrailResponse(BaseModel):
    """Result of ``GET .../candidates/evidence-trail``."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    trails: list[CandidateEvidenceTrail] = Field(default_factory=list)
    storagePath: str = ""


class SelectionContextResponse(BaseModel):
    """Server-derived scope + candidate context for the selection UI."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    mode: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    defaultSelectedCandidateIds: list[str] = Field(default_factory=list)
    latestSelection: dict[str, Any] | None = None
    reviewMeeting: dict[str, Any] | None = None
    generationMeeting: dict[str, Any] | None = None


class MeetingRoundResponse(BaseModel):
    """Single meeting round record response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    meetingRound: dict[str, Any] = Field(default_factory=dict)
    storagePath: str = ""


class MeetingRoundMutationResponse(BaseModel):
    """State-transition response carrying the updated round record."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    meetingRound: dict[str, Any] = Field(default_factory=dict)
    digestDraft: dict[str, Any] | None = None
    storagePath: str = ""


class MeetingRoundListResponse(BaseModel):
    """Meeting round list response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    meetingCount: int = 0
    meetings: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""


class MeetingSourceMessagesResponse(BaseModel):
    """Source discussion messages for one meeting round."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    meetingRoundId: str = ""
    messageCount: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)


class HypothesisRoundResponse(BaseModel):
    """Single hypothesis round record response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    round: dict[str, Any] = Field(default_factory=dict)
    storagePath: str = ""


class HypothesisRoundListResponse(BaseModel):
    """Hypothesis round list response."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    roundCount: int = 0
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""


class CollectionRequestListResponse(BaseModel):
    """Collection request records emitted by the chain."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    requestCount: int = 0
    requests: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""


class ReviewRoundLinkListResponse(BaseModel):
    """Review round link records emitted by the chain."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    linkCount: int = 0
    links: list[dict[str, Any]] = Field(default_factory=list)
    storagePath: str = ""


class ChainStateResponse(BaseModel):
    """Server-side projection of the hypothesis-first chain state."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    selectionId: str = ""
    meetingCount: int = 0
    firstMeetingId: str = ""
    firstMeetingClosed: bool = False
    openMeetingIds: list[str] = Field(default_factory=list)
    collectionRequests: list[dict[str, Any]] = Field(default_factory=list)
    collectionRequestCount: int = 0
    pendingCollectionCount: int = 0
    collectionReady: bool = False
    hypothesisRoundCount: int = 0
    latestHypothesisRoundId: str = ""
    hypothesisConverged: bool = False
    convergenceDetail: str = ""
    roundBudget: int = 0
    budgetExhausted: bool = False
    templateBaselineExists: bool = False
    templateBaselineIds: list[str] = Field(default_factory=list)


class CloseReviewMeetingResponse(BaseModel):
    """Result of ``close_review_meeting`` (closure + chain effects)."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    closed: bool = False
    meetingRound: dict[str, Any] = Field(default_factory=dict)
    digest: dict[str, Any] = Field(default_factory=dict)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    collection: dict[str, Any] = Field(default_factory=dict)
    hypothesisRound: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None
    storagePath: str = ""


class CollectionHandoffResponse(BaseModel):
    """Result of ``record_collection_handoff``."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    status: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    nextMeeting: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None


class QuestionRunResetPreviewResponse(BaseModel):
    """Read-only impact preview shown before resetting one question's run."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    canReset: bool = False
    blockingReason: str = ""
    impact: dict[str, int] = Field(default_factory=dict)


class QuestionRunResetResponse(BaseModel):
    """Completed question-scoped reset and its explicit next workflow action."""

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    removed: dict[str, int] = Field(default_factory=dict)
    nextAction: dict[str, str] = Field(default_factory=dict)


class AnomalyInboxResponse(BaseModel):
    """One anomaly-inbox projection (R4.3) for the operations console.

    ``inbox`` is the verbatim ``AnomalyInbox.to_dict()`` projection (sorted,
    merged, fail-closed contract shape); the route never reshapes it.
    ``budget_precheck`` items may additionally carry the structured
    ``action`` (one-click extend CTA) added by ``attach_inbox_actions``.
    """

    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    inbox: dict[str, Any] = Field(default_factory=dict)


class AnomalyInboxExtendBudgetRequest(BaseModel):
    """One-click extend CTA execution (inbox anomaly → extend_budget).

    ``confirmed`` is the mandatory human-authorization flag (误触防护):
    the endpoint refuses the request without it.  ``stageLimitTokens`` and
    ``suggestedExtensionTokens`` echo the amounts shown in the CTA; the
    server recomputes the new stage total and derives the idempotency key,
    so a repeated identical confirmation replays instead of double-charging.
    """

    model_config = ConfigDict(extra="forbid")

    questionId: str = Field("", max_length=200)
    runId: str = Field(..., min_length=1, max_length=200)
    nodeId: str = Field("", max_length=200)
    stageId: str = Field(..., min_length=1, max_length=200)
    stageLimitTokens: int = Field(..., ge=1)
    suggestedExtensionTokens: int = Field(..., ge=1)
    confirmed: StrictBool = False
    expectedRunVersion: int = Field(0, ge=0)
