"""Strict wire contract for canonical hypothesis-first workflow state V2.

These models validate the read-only projection boundary.  They intentionally do
not share the permissive ``extra=allow`` behavior of the legacy chain DTOs.
Business facts remain owned by their existing stores and services.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorkflowLifecycle = Literal[
    "not_started",
    "queued",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "cancelled",
    "superseded",
]
WorkflowOutcome = Literal[
    "none",
    "succeeded",
    "empty",
    "partial",
    "rejected",
    "exhausted",
]
WorkflowActionability = Literal[
    "idle",
    "available",
    "executing",
    "waiting_user",
    "waiting_system",
    "blocked",
    "terminal",
]
HypothesisFirstPhase = Literal[
    "generation",
    "selection",
    "review",
    "collection",
    "convergence",
    "formal_runtime",
    "program_delivery",
    "completed",
]
ActionCommand = Literal[
    "open_generation",
    "retry_generation",
    "record_selection",
    "retry_review_dispatch",
    "reopen_review",
    "resume_discussion",
    "stop_discussion",
    "regenerate_summary",
    "approve_summary",
    "retry_collection",
    "continue_collection",
    "stop_collection",
    "handoff_collection",
    "open_next_review",
    "human_adjudication",
    "create_formal_run",
    "retry_formal_node",
    "reconcile_formal_run",
    "cancel_run",
    "archive_run",
    "retry_program_handoff",
    "record_program_review",
    "create_formal_revision",
]
ProgramHumanGateKey = Literal[
    "H1_problem_understanding",
    "H2_hypothesis_selection",
    "H3_research_plan",
    "H4_external_output",
]
ProgramHumanGateDecision = Literal[
    "pending",
    "approved",
    "revision_requested",
    "rejected",
]

_PROGRAM_GATE_KEYS = {
    "H1_problem_understanding",
    "H2_hypothesis_selection",
    "H3_research_plan",
    "H4_external_output",
}
_NONTERMINAL_LIFECYCLES = {
    "not_started",
    "queued",
    "running",
    "waiting_human",
}
_NO_OUTCOME_LIFECYCLES = _NONTERMINAL_LIFECYCLES | {
    "failed",
    "cancelled",
    "superseded",
}


class StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowProblem(StrictWireModel):
    code: str = Field(..., min_length=1)
    category: Literal["validation", "execution", "integrity", "dependency", "stale"]
    severity: Literal["info", "warning", "error", "fatal"]
    message: str = Field(..., min_length=1)
    recoverable: bool
    sourceKind: str = Field(..., min_length=1)
    sourceId: str | None
    detectedAt: str = Field(..., min_length=1)
    # Heartbeat-stale problems only: the last observed durable activity that
    # the staleness verdict was computed from.  Absent for every other code.
    lastHeartbeatAt: str | None = None


class WorkflowAttempt(StrictWireModel):
    attemptId: str = Field(..., min_length=1)
    number: int = Field(..., ge=1)
    lifecycle: WorkflowLifecycle
    queuedAt: str | None
    startedAt: str | None
    heartbeatAt: str | None
    finishedAt: str | None
    supersedesAttemptId: str | None


class PhaseState(StrictWireModel):
    lifecycle: WorkflowLifecycle
    outcome: WorkflowOutcome
    actionability: WorkflowActionability
    attempt: WorkflowAttempt | None
    updatedAt: str | None
    problems: list[WorkflowProblem]

    @model_validator(mode="after")
    def _validate_lifecycle_outcome(self) -> PhaseState:
        if self.lifecycle == "completed" and self.outcome == "none":
            raise ValueError("completed lifecycle requires a non-none outcome")
        if self.lifecycle in _NO_OUTCOME_LIFECYCLES and self.outcome != "none":
            raise ValueError(f"{self.lifecycle} lifecycle requires outcome=none")
        return self

class ActionCommon(StrictWireModel):
    actionId: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    enabled: bool
    disabledReason: str | None
    targetPhase: HypothesisFirstPhase
    targetNodeId: str | None

    @model_validator(mode="after")
    def _validate_disabled_reason(self) -> ActionCommon:
        if not self.enabled and not (self.disabledReason or "").strip():
            raise ValueError("disabled actions require disabledReason")
        return self


class QuestionActionPayload(StrictWireModel):
    questionId: str = Field(..., min_length=1)


class RetryGenerationPayload(QuestionActionPayload):
    previousAttemptId: str = Field(..., min_length=1)


class RecordSelectionPayload(QuestionActionPayload):
    generationAttemptId: str = Field(..., min_length=1)


class RetryReviewDispatchPayload(StrictWireModel):
    selectionId: str = Field(..., min_length=1)
    candidateIds: list[str] = Field(..., min_length=1)


class MeetingActionPayload(StrictWireModel):
    meetingRoundId: str = Field(..., min_length=1)


class RetryCollectionPayload(StrictWireModel):
    requestId: str = Field(..., min_length=1)
    childRunId: str | None


class CollectionChildRunPayload(StrictWireModel):
    requestId: str = Field(..., min_length=1)
    childRunId: str = Field(..., min_length=1)


class HumanAdjudicationPayload(StrictWireModel):
    hypothesisRoundId: str = Field(..., min_length=1)


class OpenNextReviewPayload(StrictWireModel):
    previousMeetingRoundId: str = Field(..., min_length=1)
    roundBudget: int = Field(..., ge=1, le=5)


class CreateFormalRunPayload(QuestionActionPayload):
    hypothesisRoundId: str = Field(..., min_length=1)


class RunActionPayload(StrictWireModel):
    runId: str = Field(..., min_length=1)


class RetryFormalNodePayload(RunActionPayload):
    nodeId: str = Field(..., min_length=1)


class RetryProgramHandoffPayload(RunActionPayload):
    deliveryArtifactRef: str | None


class RecordProgramReviewPayload(QuestionActionPayload):
    outputRunId: str = Field(..., min_length=1)


class CreateFormalRevisionPayload(RunActionPayload):
    outputRecordId: str = Field(..., min_length=1)


ActionPayload = (
    QuestionActionPayload
    | RetryGenerationPayload
    | RecordSelectionPayload
    | RetryReviewDispatchPayload
    | MeetingActionPayload
    | RetryCollectionPayload
    | CollectionChildRunPayload
    | OpenNextReviewPayload
    | HumanAdjudicationPayload
    | CreateFormalRunPayload
    | RunActionPayload
    | RetryFormalNodePayload
    | RetryProgramHandoffPayload
    | RecordProgramReviewPayload
    | CreateFormalRevisionPayload
)

_ACTION_PAYLOAD_TYPES: dict[str, type[StrictWireModel]] = {
    "open_generation": QuestionActionPayload,
    "retry_generation": RetryGenerationPayload,
    "record_selection": RecordSelectionPayload,
    "retry_review_dispatch": RetryReviewDispatchPayload,
    "reopen_review": MeetingActionPayload,
    "resume_discussion": MeetingActionPayload,
    "stop_discussion": MeetingActionPayload,
    "regenerate_summary": MeetingActionPayload,
    "approve_summary": MeetingActionPayload,
    "retry_collection": RetryCollectionPayload,
    "continue_collection": CollectionChildRunPayload,
    "stop_collection": CollectionChildRunPayload,
    "handoff_collection": CollectionChildRunPayload,
    "open_next_review": OpenNextReviewPayload,
    "human_adjudication": HumanAdjudicationPayload,
    "create_formal_run": CreateFormalRunPayload,
    "retry_formal_node": RetryFormalNodePayload,
    "reconcile_formal_run": RunActionPayload,
    "cancel_run": RunActionPayload,
    "archive_run": RunActionPayload,
    "retry_program_handoff": RetryProgramHandoffPayload,
    "record_program_review": RecordProgramReviewPayload,
    "create_formal_revision": CreateFormalRevisionPayload,
}


class CommandAction(ActionCommon):
    kind: Literal["command"]
    command: ActionCommand
    payload: ActionPayload
    inputSchemaRef: str | None
    idempotencyKey: str = Field(..., min_length=1)
    expectedStateVersion: str = Field(..., pattern=r"^hf2-action:")
    requiresConfirmation: bool
    confirmationText: str | None

    @model_validator(mode="before")
    @classmethod
    def _parse_payload_for_command(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        command = value.get("command")
        expected_type = _ACTION_PAYLOAD_TYPES.get(command)
        if expected_type is None:
            return value
        return {
            **value,
            "payload": expected_type.model_validate(value.get("payload")),
        }

    @model_validator(mode="after")
    def _validate_payload_for_command(self) -> CommandAction:
        expected_type = _ACTION_PAYLOAD_TYPES[self.command]
        if type(self.payload) is not expected_type:
            raise ValueError(
                f"payload for {self.command} must be {expected_type.__name__}"
            )
        if self.requiresConfirmation and not (self.confirmationText or "").strip():
            raise ValueError("confirmationText is required when confirmation is required")
        return self


class WorkflowNavigationAnchor(StrictWireModel):
    status: Literal["ready", "degraded"]
    degradedReason: str | None
    roomId: str | None
    meetingRoundId: str | None
    questionId: str = Field(..., min_length=1)
    selectionId: str | None
    candidateId: str | None
    deepLink: str | None
    returnTo: str = Field(..., min_length=1)
    returnLabel: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_navigation_readiness(self) -> WorkflowNavigationAnchor:
        if self.status == "ready" and not (self.deepLink or "").strip():
            raise ValueError("ready navigation requires deepLink")
        if self.status == "degraded" and not (self.degradedReason or "").strip():
            raise ValueError("degraded navigation requires degradedReason")
        return self


class NavigationAction(ActionCommon):
    kind: Literal["navigation"]
    navigation: WorkflowNavigationAnchor


AllowedAction = Annotated[CommandAction | NavigationAction, Field(discriminator="kind")]


class RecordSelectionInput(StrictWireModel):
    candidateIds: list[str] = Field(..., min_length=1, max_length=16)


class ApproveSummaryInput(StrictWireModel):
    decision: Literal["accepted", "rejected", "revised"]


class HumanAdjudicationInput(StrictWireModel):
    decision: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)


class ProgramReviewDecisions(StrictWireModel):
    H1_problem_understanding: Literal["approved", "revision_requested", "rejected"]
    H2_hypothesis_selection: Literal["approved", "revision_requested", "rejected"]
    H3_research_plan: Literal["approved", "revision_requested", "rejected"]
    H4_external_output: Literal["approved", "revision_requested", "rejected"]


class RecordProgramReviewInput(StrictWireModel):
    reviewer: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    decisions: ProgramReviewDecisions


ActionInput = (
    RecordSelectionInput
    | ApproveSummaryInput
    | HumanAdjudicationInput
    | RecordProgramReviewInput
)


class HypothesisFirstCommandRequest(StrictWireModel):
    actionId: str = Field(..., min_length=1)
    idempotencyKey: str = Field(..., min_length=1)
    expectedStateVersion: str = Field(..., pattern=r"^hf2-action:")
    payload: ActionPayload
    input: ActionInput | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_empty_input(cls, value: Any) -> Any:
        # Clients that build requests generically send ``input: {}`` for
        # actions that take no declaration input.  Every ActionInput variant
        # has required fields, so an empty object can never validate; treat it
        # exactly like an omitted field instead of a 422 (SCI-096 UX finding).
        if (
            isinstance(value, dict)
            and isinstance(value.get("input"), dict)
            and not value["input"]
        ):
            return {**value, "input": None}
        return value

    @model_validator(mode="before")
    @classmethod
    def _parse_payload_from_action_id(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        action_id = str(value.get("actionId") or "")
        command = next(
            (
                candidate
                for candidate in _ACTION_PAYLOAD_TYPES
                if action_id == candidate.replace("_", "-")
                or action_id.startswith(candidate.replace("_", "-") + ":")
            ),
            None,
        )
        if command is None:
            return value
        return {
            **value,
            "payload": _ACTION_PAYLOAD_TYPES[command].model_validate(
                value.get("payload")
            ),
        }


class ReviewCandidateState(PhaseState):
    candidateId: str = Field(..., min_length=1)
    candidateOrder: int = Field(..., ge=0)
    selectionId: str = Field(..., min_length=1)
    roundIndex: int = Field(..., ge=0)
    meetingRoundId: str | None
    discussionAnchor: WorkflowNavigationAnchor | None
    discussion: PhaseState
    summarization: PhaseState
    approval: PhaseState


class CollectionSourceState(PhaseState):
    sourceId: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    itemCount: int = Field(..., ge=0)
    error: WorkflowProblem | None


class CollectionChildRunState(PhaseState):
    runId: str | None


class CollectionHandoffState(PhaseState):
    handoffId: str | None
    targetRoundIndex: int | None = Field(default=None, ge=0)


class CollectionRequestState(PhaseState):
    requestId: str = Field(..., min_length=1)
    queryCount: int = Field(..., ge=0)
    childRun: CollectionChildRunState
    sources: list[CollectionSourceState]
    handoff: CollectionHandoffState
    # Real cross-run handoff status derived by the projection from its own
    # child-run / handoff facts (superset of KnowledgeHandoffState with the
    # recovery states the "重试资料交接" action acts on).
    handoffStatus: Literal["accepted", "pending", "failed", "needs_context"]


class StateAggregate(StrictWireModel):
    total: int = Field(..., ge=0)
    completed: int = Field(..., ge=0)
    pending: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    blocked: int = Field(..., ge=0)


def _aggregate_for_states(states: list[PhaseState]) -> StateAggregate:
    counts = {"completed": 0, "pending": 0, "failed": 0, "blocked": 0}
    for state in states:
        if state.actionability == "blocked":
            counts["blocked"] += 1
        elif state.lifecycle == "failed":
            counts["failed"] += 1
        elif state.lifecycle == "completed":
            counts["completed"] += 1
        else:
            counts["pending"] += 1
    return StateAggregate(total=len(states), **counts)


class GenerationState(PhaseState):
    generationMeetingId: str | None
    candidateCount: int = Field(..., ge=0)
    candidateIds: list[str]

    @model_validator(mode="after")
    def _validate_candidates(self) -> GenerationState:
        if self.candidateCount != len(self.candidateIds):
            raise ValueError("candidateCount must equal candidateIds length")
        if len(set(self.candidateIds)) != len(self.candidateIds):
            raise ValueError("candidateIds must be unique")
        return self


class SelectionState(PhaseState):
    selectionId: str | None
    selectedCandidateIds: list[str]


class ReviewState(PhaseState):
    activeRoundIndex: int | None = Field(default=None, ge=0)
    aggregate: StateAggregate
    candidates: list[ReviewCandidateState]

    @model_validator(mode="after")
    def _validate_aggregate(self) -> ReviewState:
        expected = _aggregate_for_states(self.candidates)
        if self.aggregate != expected:
            raise ValueError("review aggregate does not match candidate states")
        identities = [
            (item.selectionId, item.roundIndex, item.candidateId)
            for item in self.candidates
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("review candidate identities must be unique")
        return self


class CollectionState(PhaseState):
    aggregate: StateAggregate
    requests: list[CollectionRequestState]

    @model_validator(mode="after")
    def _validate_aggregate(self) -> CollectionState:
        if self.aggregate != _aggregate_for_states(self.requests):
            raise ValueError("collection aggregate does not match request states")
        return self


class ConvergenceState(PhaseState):
    latestHypothesisRoundId: str | None
    accepted: bool
    roundIndex: int = Field(..., ge=0)
    roundBudget: int = Field(..., ge=1)
    # R2.2 claim belief gate verdict for the recommended candidate; None
    # while the chain is not structurally converged.  Mirrors the v1 chain
    # state's claimBeliefGate so UIs can present the gate on either surface.
    claimBeliefGate: dict[str, Any] | None = None


class FormalRuntimeState(PhaseState):
    runId: str | None
    runVersion: int | None = Field(default=None, ge=0)
    runStatus: Literal[
        "queued",
        "running",
        "waiting_human",
        "blocked",
        "reconciliation_required",
        "succeeded",
        "failed",
        "cancelled",
        "archived",
    ] | None
    completionKind: str | None
    lineageDisposition: Literal[
        "current", "branched_parent", "historical", "conflicted"
    ] | None
    isCurrentRevision: bool
    parentRunId: str | None
    childRunIds: list[str]
    currentNodeIds: list[str]

    @model_validator(mode="after")
    def _validate_branched_parent(self) -> FormalRuntimeState:
        if self.lineageDisposition == "branched_parent":
            if self.lifecycle != "completed" or self.outcome != "succeeded":
                raise ValueError(
                    "branched parent preserves completed+succeeded run authority"
                )
            if self.isCurrentRevision or not self.childRunIds:
                raise ValueError("branched parent requires a non-current run with children")
        return self


class ProgramHumanGateState(StrictWireModel):
    decisions: dict[ProgramHumanGateKey, ProgramHumanGateDecision]
    reviewer: str | None
    rationale: str | None
    decidedAt: str | None

    @model_validator(mode="after")
    def _validate_exact_gates(self) -> ProgramHumanGateState:
        if set(self.decisions) != _PROGRAM_GATE_KEYS:
            raise ValueError("program human gate keys must be the exact H1-H4 set")
        return self


class ProgramDeliveryState(PhaseState):
    deliveryStatus: Literal[
        "not_started", "queued", "running", "blocked", "succeeded", "failed"
    ]
    deliveryArtifactRef: str | None
    handoffStatus: Literal[
        "not_started", "needs_context", "registered", "idempotent", "failed"
    ]
    outputRecordId: str | None
    outputRunId: str | None
    humanReviewStatus: Literal[
        "not_started",
        "waiting_human",
        "revision_requested",
        "rejected",
        "approved",
    ]
    humanGates: ProgramHumanGateState
    approvedGateCount: int = Field(..., ge=0, le=4)
    requiredGateCount: Literal[4]

    @model_validator(mode="after")
    def _validate_gate_count(self) -> ProgramDeliveryState:
        approved = sum(
            decision == "approved" for decision in self.humanGates.decisions.values()
        )
        if self.approvedGateCount != approved:
            raise ValueError("approvedGateCount must match H1-H4 decisions")
        return self


class OfficialCatalogScope(StrictWireModel):
    questionInOfficialCatalog: Literal[True]
    catalogId: str = Field(..., min_length=1)
    catalogSha256: str = Field(..., min_length=1)
    workflowRunId: str | None = None


class ResetBoundary(StrictWireModel):
    resetId: str = Field(..., min_length=1)
    resetAt: str | None
    source: Literal["question_reset_audit", "origin"]


RequirementDeliveryClass = Literal[
    "G1_REQUIRED",
    "STAGE1_SCALE_OUT",
    "SUBMISSION_PACKAGE",
    "PHASE2_USER",
]
RequirementCoverageStatus = Literal["evidenced", "not_yet_evidenced"]


class Direction1ARequirementState(StrictWireModel):
    requirementId: str = Field(..., min_length=1)
    requirement: str = Field(..., min_length=1)
    officialDimension: str
    officialScoringPoints: list[str]
    deliveryClass: RequirementDeliveryClass
    coverageStatus: RequirementCoverageStatus
    evidenceRefs: list[str]
    deferredOwner: str


class Direction1ASubmissionState(StrictWireModel):
    source: Literal["competition_alignment", "not_materialized"]
    submissionReady: bool
    g1RequiredUnmet: list[str]
    notYetEvidenced: list[str]
    items: list[Direction1ARequirementState]


class HypothesisFirstStateV2(StrictWireModel):
    schemaVersion: Literal[2]
    contract: Literal["hypothesis-first-state/v2"]
    teamId: str = Field(..., min_length=1)
    questionId: str = Field(..., min_length=1)
    stateVersion: str = Field(..., pattern=r"^hf2-action:")
    representationVersion: str = Field(..., pattern=r"^hf2-repr:")
    computedAt: str = Field(..., min_length=1)
    scope: OfficialCatalogScope
    resetBoundary: ResetBoundary
    isInitial: bool
    awaitingHumanCount: int = Field(..., ge=0)
    currentPhase: HypothesisFirstPhase
    overall: PhaseState
    generation: GenerationState
    selection: SelectionState
    review: ReviewState
    collection: CollectionState
    convergence: ConvergenceState
    formalRuntime: FormalRuntimeState
    programDelivery: ProgramDeliveryState
    direction1ASubmissionReady: bool
    direction1aSubmission: Direction1ASubmissionState
    allowedActions: list[AllowedAction]
    problems: list[WorkflowProblem]
    sourceCursor: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate_snapshot_invariants(self) -> HypothesisFirstStateV2:
        if self.stateVersion == self.representationVersion:
            raise ValueError("stateVersion and representationVersion have distinct roles")
        if self.isInitial:
            if self.currentPhase != "generation":
                raise ValueError("initial state must be in generation phase")
            if self.generation.lifecycle != "not_started":
                raise ValueError("initial generation must be not_started")
        if self.currentPhase == "completed" and (
                self.overall.lifecycle != "completed"
                or self.overall.outcome != "succeeded"
                or self.programDelivery.lifecycle != "completed"
                or self.programDelivery.outcome != "succeeded"
                or self.programDelivery.humanReviewStatus != "approved"
                or self.programDelivery.approvedGateCount != 4
        ):
            raise ValueError(
                "completed workflow requires delivery succeeded and all H1-H4 gates approved"
            )
        for action in self.allowedActions:
            if (
                isinstance(action, CommandAction)
                and action.expectedStateVersion != self.stateVersion
            ):
                raise ValueError(
                    "command expectedStateVersion must equal snapshot stateVersion"
                )
        return self
