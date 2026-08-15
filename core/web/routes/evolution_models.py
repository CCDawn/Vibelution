"""Public contracts for evolution JSON routes.

Known identity and dashboard envelope fields stay explicit for OpenAPI.
Nested run, proposal, review, and workbench payloads still evolve, so extras
pass through. Nullable nested objects use `dict | None` rather than empty-dict
defaults. Routes must use response_model_exclude_unset=True. SSE endpoints use
response_class=StreamingResponse and must not declare response_model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SupervisedRunStartPayload(BaseModel):
    sourceKind: str = ""
    datasetName: str = ""
    datasetLimit: int | None = None
    bundleName: str = ""
    keepWorktree: bool = False
    mentalModelMode: str = "follow"


class SupervisedRunActionPayload(BaseModel):
    action: str = ""


class ProposalBulkDeletePayload(BaseModel):
    sessionIds: list[str] = Field(default_factory=list)


class SupervisedWorktreeRunStartPayload(BaseModel):
    sourceKind: str = "bundle"
    datasetName: str = ""
    datasetLimit: int | None = None
    bundleName: str = ""
    keepWorktree: bool = True
    mode: str = "auto"
    approvalMode: str = "human"
    executionMode: str = "simulation"
    confirmRealLlmCost: bool = False
    mentalModelMode: str = "follow"
    uiRoute: str = "/evolution"
    clientAction: str = "start_supervised_worktree_run"


class SelfEvolutionWorktreeRunStartPayload(BaseModel):
    goal: str = ""
    sourceKind: str = "bundle"
    datasetName: str = ""
    datasetLimit: int | None = None
    bundleName: str = ""
    mode: str = "manual"
    executionMode: str = "simulation"
    confirmRealLlmCost: bool = False
    uiRoute: str = "/evolution?track=self"


class SelfObservationRunStartPayload(BaseModel):
    goal: str = ""
    durationSeconds: int = 300
    inputMode: str = "prompt"
    uiRoute: str = "/evolution?track=self"


class SelfObservationRunActionPayload(BaseModel):
    action: str = ""


class SelfEvolutionAutonomousRunStartPayload(BaseModel):
    goal: str = ""
    maxIterations: int = 1


class SelfEvolutionAutonomousRunActionPayload(BaseModel):
    action: str = ""
    comment: str = ""


class SupervisedWorktreeRunActionPayload(BaseModel):
    action: str = ""
    force: bool = False
    reviewerNote: str = ""


class ProposalUpdatePayload(BaseModel):
    improvementType: str | None = None
    expectedEffect: str | None = None
    summary: str | None = None
    candidatePrompt: str | None = None
    baselinePrompt: str | None = None
    editNote: str | None = None


class SelfEvolutionHistoryDeletePayload(BaseModel):
    txnIds: list[str] = Field(default_factory=list)


class ChatReviewActionPayload(BaseModel):
    decision: str = ""
    reasonCode: str = ""
    errorType: str = ""
    correctPrinciple: str = ""
    idealBehavior: str = ""
    reviewerNote: str = ""


class ChatReviewBulkDeletePayload(BaseModel):
    candidateIds: list[str] = Field(default_factory=list)
    reviewerNote: str = ""


class EvolutionJsonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvolutionOverviewResponse(EvolutionJsonResponse):
    currentStatus: dict[str, Any] | None = None
    workbench: dict[str, Any] | None = None
    recentRuns: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    goal: str | None = None


class EvolutionWorkspaceSnapshotResponse(EvolutionJsonResponse):
    overview: dict[str, Any] | None = None
    runs: list[dict[str, Any]] | None = None
    library: dict[str, Any] | None = None
    workbench: dict[str, Any] | None = None
    activeRun: dict[str, Any] | None = None
    latestRun: dict[str, Any] | None = None
    latestClosedLoopRecord: dict[str, Any] | None = None
    currentAgentBindings: dict[str, Any] | None = None
    currentAgentBindingSource: str | None = None
    currentAgentBindingStatus: str | None = None
    currentAgentBindingIssues: list[Any] | None = None
    worktreeActiveRun: dict[str, Any] | None = None
    worktreeRuns: list[dict[str, Any]] | None = None
    evolutionRuntime: dict[str, Any] | None = None
    selfOverview: dict[str, Any] | None = None
    selfWorktreeActiveRun: dict[str, Any] | None = None
    selfWorktreeRuns: list[dict[str, Any]] | None = None
    selfObservationActiveRun: dict[str, Any] | None = None
    selfAutonomousActiveRun: dict[str, Any] | None = None
    selfAutonomousLatestRun: dict[str, Any] | None = None
    selfTransactions: list[dict[str, Any]] | None = None


class EvolutionSelfWorkspaceSnapshotResponse(EvolutionJsonResponse):
    overview: dict[str, Any] | None = None
    transactions: list[dict[str, Any]] | None = None
    worktreeActiveRun: dict[str, Any] | None = None
    observationActiveRun: dict[str, Any] | None = None
    autonomousActiveRun: dict[str, Any] | None = None
    autonomousLatestRun: dict[str, Any] | None = None


class EvolutionLibraryResponse(EvolutionJsonResponse):
    items: list[dict[str, Any]] | None = None
    pending: list[dict[str, Any]] | None = None


class EvolutionProposalResponse(EvolutionJsonResponse):
    sessionId: str | None = None
    sourceRun: str | None = None
    canEdit: bool | None = None
    canDelete: bool | None = None
    availableActions: list[Any] | None = None
    review: dict[str, Any] | None = None


class EvolutionRunResponse(EvolutionJsonResponse):
    runId: str | None = None
    id: str | None = None
    status: str | None = None


class EvolutionCommandStatusResponse(EvolutionJsonResponse):
    commandId: str | None = None
    status: str | None = None


class EvolutionChatReviewQueueResponse(EvolutionJsonResponse):
    enabled: bool | None = None
    pendingCount: int | None = None
    counts: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] | None = None


class EvolutionChatReviewCandidateResponse(EvolutionJsonResponse):
    candidateId: str | None = None
    id: str | None = None
    status: str | None = None


class EvolutionDeletedResponse(EvolutionJsonResponse):
    deleted: bool | None = None
    deletedCount: int | None = None
    sessionIds: list[str] | None = None
    candidateIds: list[str] | None = None
    txnIds: list[str] | None = None
