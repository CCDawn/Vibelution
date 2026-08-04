/**
 * Source-collection inject renderers extracted from TeamsRoute.
 * Route owns state/mutations; this factory only mounts already-extracted inject panels.
 */
import type { MouseEvent as ReactMouseEvent } from "react";

import { TeamSourceCollectionModeFields } from "./TeamSourceCollectionModeFields";
import { TeamSourceCollectionManualWritebackInject } from "./TeamSourceCollectionManualWritebackInject";
import { TeamSourceCollectionControlsInject } from "./TeamSourceCollectionControlsInject";
import { TeamSourceCollectionActiveStageInject } from "./TeamSourceCollectionActiveStageInject";
import { TeamSourceCollectionStorageActionsInject } from "./TeamSourceCollectionStorageActionsInject";
import { TeamSourceCollectionSearchBriefShell } from "./TeamSourceCollectionSearchBriefShell";
import { TeamSourceCollectionRunSwitcherInject } from "./TeamSourceCollectionRunSwitcherInject";
import { TeamSourceCollectionScreeningInject } from "./TeamSourceCollectionScreeningInject";
import { TeamSourceCollectionGraphInject } from "./TeamSourceCollectionGraphInject";
import { TeamSourceCollectionMemoryInject } from "./TeamSourceCollectionMemoryInject";
import { TeamSourceCollectionSelectedSourceInject } from "./TeamSourceCollectionSelectedSourceInject";
import { TeamSourceCollectionConversationInject } from "./TeamSourceCollectionConversationInject";
import { TeamSourceCollectionFilterBarInject } from "./TeamSourceCollectionFilterBarInject";
import { TeamSourceCollectionPaginationInject } from "./TeamSourceCollectionPaginationInject";
import { TeamSourceCollectionStageAgentsInject } from "./TeamSourceCollectionStageAgentsInject";
import {
  buildSourceCollectionControlsFeedbackBag,
  buildSourceCollectionControlsMetricsBag,
} from "./source-collection/controlsFeedbackBag";
import {
  SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS,
  sourceCollectionFreshProjectDraft,
} from "./source-collection/presentationModel";
import {
  sourceCollectionSourceTypeLabel,
  type SourceCollectionSourceFilter,
} from "./source-collection/evidenceModel";
import {
  SOURCE_COLLECTION_STAGE_CHAT_LABELS,
  candidatePaperNoteChunkPlanSummary,
  sourceCandidateHasCompletedExtraction,
} from "./teamRouteShellModel";
import { sourceCollectionPageSlice } from "./teamSourceCollectionShellModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";

/** Loose context bag from TeamsRoute; keep typing light to avoid dual ownership of route state. */
export type SourceCollectionInjectRenderContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createSourceCollectionInjectRenderers(ctx: SourceCollectionInjectRenderContext) {
  const {
    lang,
    sourceCollectionStageAgentBindings,
    agentSummaryQuery,
    selectedTeam,
    selectedTeamReturnRoute,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    sourceCollectionLoadingText,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    sourceCollectionRuns,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionHistoricalRunWithRecords,
    sourceCollectionShowingHistoricalRunByDefault,
    sourceCollectionRecordsDataLoading,
    sourceCollectionRunStatus,
    setSelectedSourceCollectionRunId,
    sourceCollectionFilteredRecords,
    sourceCollectionRecords,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionStageModules,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    sourceCollectionCollectedCountLabel,
    selectedSourceCollectionStorageArtifacts,
    sourceCollectionBoardNextStepLabel,
    sourceCollectionActionDisabledTitle,
    sourceCollectionRecordFilterCounts,
    sourceCollectionCollectedCountText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionRecordMissingSourceCount,
    sourceCollectionCandidatesByRecordId,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    selectedSourceCollectionStorageOpenPending,
    selectedSourceCollectionStorageOpenResult,
    selectedSourceCollectionStorageOpenError,
    openSourceCollectionStorageTarget,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionCandidateStorageArtifacts,
    workflowQualityToneBound,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionCountText,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionDataSyncText,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionScreeningStepState,
    sourceCollectionDisplayedCandidateFilterCounts,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    runSourceCollectionScreeningAction,
    sourceCollectionScreeningDisabled,
    selectedTeamSourceQualityPending,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionScreeningButtonText,
    sourceCollectionScreeningButtonTitle,
    sourceCollectionScreeningStatusText,
    sourceCollectionQualityBatchFeedback,
    sourceCollectionExtractionNeedsAgentMaterial,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionProjectedApprovedCount,
    openSourceCollectionScreeningPanel,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    workflowIngestionToneBound,
    selectedTeamSourceQualityError,
    selectedTeamAssessSourceQualityPending,
    assessSourceQualityMutation,
    selectedTeamPlanPaperNoteChunksPending,
    planPaperNoteChunksMutation,
    sourceCollectionGraphProjection,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    teamWorkflowCandidateGraph,
    teamWorkflowCandidatesById,
    sourceCollectionGraphStepState,
    teamWorkflowCandidateGraphQuery,
    selectedTeamBuildCandidateGraphError,
    teamWorkflowKnowledgeIngestionStatus,
    sourceCollectionMemoryStepState,
    sourceCollectionCandidateFilterCounts,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionApprovedCount,
    teamWorkflowKnowledgeIngestionStatusQuery,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionDraftHydratedRunIdRef,
    sourceCollectionDraftHydratedSearchPlanRef,
    activeSourceCollectionResearchProject,
    sourceCollectionFreshProjectDraftIdRef,
    sourceCollectionResetResearchProjectId,
    resetResearchProjectSourceCollectionMutation,
    sourceCollectionResetAvailable,
    selectedResearchProjectSourceCollectionResetPending,
    selectedResearchProjectSourceCollectionResetError,
    sourceCollectionCanStart,
    selectedTeamStartSourceCollectionPending,
    startSourceCollectionRunMutation,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    sourceCollectionAssignments,
    selectedSourceCollectionAssignment,
    canRecordSourceCollectionOutput,
    selectedTeamRecordSourceCollectionOutputPending,
    sourceCollectionOutputHasRecord,
    recordSourceCollectionOutputMutation,
    sourceCollectionControlPanelRef,
    sourceCollectionStageFocusLabel,
    sourceCollectionFindingRunOptions,
    sourceCollectionFindingAssignments,
    sourceCollectionFindingQueries,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamStartSourceCollectionError,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamStartSourceCollectionStageTaskError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamRecordSourceCollectionOutputResult,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    sourceCollectionPrecheckCandidateCount,
    sourceCollectionStageAgentChatState,
    repairChallengeCupTeamAgentsMutation,
    sourceCollectionStagePrimaryAgentBinding,
    openSourceCollectionStageAgentChat,
    startSourceCollectionStageSessionTask,
    sourceCollectionFindingStageCompact,
    sourceCollectionCandidateProjection,
    sourceCollectionRunApprovedCount,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionExcludedRecoveryState,
    runSourceCollectionCandidateExtractionAction,
    sourceCollectionCandidateExtractionActionReadiness,
    sourceCollectionExtractionCanProceedAfterExclusions,
    sourceCollectionUnverifiableCandidateIds,
    excludeUnverifiableSourceCollectionCandidates,
    selectSourceCollectionStage,
  } = ctx;

  function renderSourceCollectionStageAgents(stageId: SourceCollectionStageModuleId) {
    return (
      <TeamSourceCollectionStageAgentsInject
        lang={lang}
        stageId={stageId}
        bindings={sourceCollectionStageAgentBindings(stageId)}
        agentSummaryPending={agentSummaryQuery.isPending}
        agentSummaryFetching={agentSummaryQuery.isFetching}
        agentSummaryError={agentSummaryQuery.isError}
        teamId={selectedTeam?.teamId}
        returnTo={selectedTeamReturnRoute}
      />
    );
  }

  function renderSourceCollectionFilterBar(
    counts: Record<SourceCollectionSourceFilter, number>,
    label: string,
    loading = false,
  ) {
    return (
      <TeamSourceCollectionFilterBarInject
        lang={lang}
        counts={counts}
        label={label}
        selected={sourceCollectionSourceFilter}
        loading={loading}
        loadingAllText={sourceCollectionLoadingText}
        onSelect={setSourceCollectionSourceFilter}
      />
    );
  }

  function sourceCollectionPageItems<T>(stageId: SourceCollectionStageModuleId, items: T[]) {
    return sourceCollectionPageSlice(items, sourceCollectionResultPageByStage[stageId] ?? 1);
  }

  function setSourceCollectionResultPage(stageId: SourceCollectionStageModuleId, page: number) {
    setSourceCollectionResultPageByStage((current) => ({
      ...current,
      [stageId]: Math.max(1, page),
    }));
  }

  function stopSourceCollectionPaginationEvent(event: ReactMouseEvent<HTMLDivElement>) {
    event.stopPropagation();
  }

  function renderSourceCollectionPagination(stageId: SourceCollectionStageModuleId, total: number) {
    return (
      <TeamSourceCollectionPaginationInject
        lang={lang}
        stageId={stageId}
        total={total}
        page={sourceCollectionResultPageByStage[stageId] ?? 1}
        onPageChange={setSourceCollectionResultPage}
        onContain={stopSourceCollectionPaginationEvent}
      />
    );
  }


  function renderSourceCollectionRunSwitcher() {
    return (
      <TeamSourceCollectionRunSwitcherInject
        lang={lang}
        runs={sourceCollectionRuns}
        selectedRun={selectedSourceCollectionRun}
        selectedRunId={selectedSourceCollectionRunEffectiveId}
        historicalRunWithRecords={sourceCollectionHistoricalRunWithRecords}
        showingHistoricalRunByDefault={sourceCollectionShowingHistoricalRunByDefault}
        recordsLoading={sourceCollectionRecordsDataLoading}
        loadingText={sourceCollectionLoadingText}
        runStatusLabelSource={sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status}
        onRunChange={setSelectedSourceCollectionRunId}
      />
    );
  }

  function renderSourceCollectionConversation() {
    return (
      <TeamSourceCollectionConversationInject
        lang={lang}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionFilteredRecords={sourceCollectionFilteredRecords}
        sourceCollectionRecordsDataLoading={sourceCollectionRecordsDataLoading}
        sourceCollectionRecords={sourceCollectionRecords}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionHistoricalRunWithRecords={sourceCollectionHistoricalRunWithRecords}
        sourceCollectionLoadingText={sourceCollectionLoadingText}
        sourceCollectionRawRecordCount={sourceCollectionRawRecordCount}
        sourceCollectionRecordClickableSourceCount={sourceCollectionRecordClickableSourceCount}
        sourceCollectionRecordLocalFileCount={sourceCollectionRecordLocalFileCount}
        sourceCollectionStageModules={sourceCollectionStageModules}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        sourceCollectionDraft={sourceCollectionDraft}
        sourceCollectionCollectedCountLabel={sourceCollectionCollectedCountLabel}
        selectedSourceCollectionStorageArtifacts={selectedSourceCollectionStorageArtifacts}
        sourceCollectionBoardNextStepLabel={sourceCollectionBoardNextStepLabel}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        setSourceCollectionSourceFilter={setSourceCollectionSourceFilter}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionRecordFilterCounts={sourceCollectionRecordFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionCollectedCountText={sourceCollectionCollectedCountText}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionPendingCandidateImportCount={sourceCollectionPendingCandidateImportCount}
        sourceCollectionRecordMissingSourceCount={sourceCollectionRecordMissingSourceCount}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        sourceCollectionCandidatesByRecordId={sourceCollectionCandidatesByRecordId}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
        setSelectedSourceCollectionRunId={setSelectedSourceCollectionRunId}
      />
    );
  }

  function renderSourceCollectionStorageActions() {
    return (
      <TeamSourceCollectionStorageActionsInject
        lang={lang}
        artifacts={selectedSourceCollectionStorageArtifacts}
        runId={selectedSourceCollectionRunEffectiveId}
        pending={selectedSourceCollectionStorageOpenPending}
        openedPath={(selectedSourceCollectionStorageOpenResult as any)?.openedPath ?? ""}
        errorMessage={(selectedSourceCollectionStorageOpenError as any)?.message ?? ""}
        onOpenTarget={(target) => openSourceCollectionStorageTarget(target)}
      />
    );
  }

  function renderSourceCollectionSelectedSourcePanel() {
    return (
      <TeamSourceCollectionSelectedSourceInject
        lang={lang}
        selectedSourceCollectionCandidate={selectedSourceCollectionCandidate}
        selectedSourceCollectionCandidateTrace={selectedSourceCollectionCandidateTrace}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        selectedSourceCollectionCandidateStorageArtifacts={selectedSourceCollectionCandidateStorageArtifacts}
        workflowQualityTone={workflowQualityToneBound}
        selectedSourceCollectionStorageOpenPending={selectedSourceCollectionStorageOpenPending}
        openSourceCollectionStorageTarget={openSourceCollectionStorageTarget}
      />
    );
  }

  function renderSourceCollectionScreeningPanel() {
    return (
      <TeamSourceCollectionScreeningInject
        lang={lang}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionCountText={sourceCollectionCountText}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionDataSyncText={sourceCollectionDataSyncText}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionExtractionDefaultPanelId={sourceCollectionExtractionDefaultPanelId}
        sourceCollectionScreeningStepState={sourceCollectionScreeningStepState}
        sourceCollectionDisplayedCandidateFilterCounts={sourceCollectionDisplayedCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionProjectedAssessedCountText={sourceCollectionProjectedAssessedCountText}
        sourceCollectionProjectedApprovedCountText={sourceCollectionProjectedApprovedCountText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
        sourceCollectionEvidenceReadyCandidateCount={sourceCollectionEvidenceReadyCandidateCount}
        sourceCollectionMissingEvidenceAnchorCount={sourceCollectionMissingEvidenceAnchorCount}
        runSourceCollectionScreeningAction={runSourceCollectionScreeningAction}
        sourceCollectionScreeningDisabled={sourceCollectionScreeningDisabled}
        selectedTeamSourceQualityPending={selectedTeamSourceQualityPending}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionScreeningActionReadiness={sourceCollectionScreeningActionReadiness}
        sourceCollectionScreeningButtonText={sourceCollectionScreeningButtonText}
        sourceCollectionScreeningButtonTitle={sourceCollectionScreeningButtonTitle}
        sourceCollectionScreeningStatusText={sourceCollectionScreeningStatusText}
        sourceCollectionQualityBatchFeedback={sourceCollectionQualityBatchFeedback}
        needsAgentMaterial={sourceCollectionExtractionNeedsAgentMaterial}
        pendingScreeningCount={sourceCollectionRunPendingScreeningCount}
        projectedApprovedCount={sourceCollectionProjectedApprovedCount}
        openSourceCollectionScreeningPanel={openSourceCollectionScreeningPanel}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        teamWorkflowSourceQualityStatus={teamWorkflowSourceQualityStatus}
        teamWorkflowSourceQualityStatusQuery={teamWorkflowSourceQualityStatusQuery}
        workflowIngestionTone={workflowIngestionToneBound}
        selectedTeamSourceQualityError={selectedTeamSourceQualityError}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
        selectedTeam={selectedTeam}
        selectedTeamAssessSourceQualityPending={selectedTeamAssessSourceQualityPending}
        assessSourceQualityMutation={assessSourceQualityMutation}
        selectedTeamPlanPaperNoteChunksPending={selectedTeamPlanPaperNoteChunksPending}
        planPaperNoteChunksMutation={planPaperNoteChunksMutation}
        sourceCandidateHasCompletedExtraction={sourceCandidateHasCompletedExtraction}
        candidatePaperNoteChunkPlanSummary={candidatePaperNoteChunkPlanSummary}
      />
    );
  }

  function renderSourceCollectionGraphPanel() {
    return (
      <TeamSourceCollectionGraphInject
        lang={lang}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        sourceCollectionGraphProjection={sourceCollectionGraphProjection}
        sourceCollectionProjectedGraphNodeCount={sourceCollectionProjectedGraphNodeCount}
        sourceCollectionProjectedGraphEdgeCount={sourceCollectionProjectedGraphEdgeCount}
        teamWorkflowCandidateGraph={teamWorkflowCandidateGraph}
        teamWorkflowCandidatesById={teamWorkflowCandidatesById}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionGraphStepState={sourceCollectionGraphStepState}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionPageItems={sourceCollectionPageItems}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        teamWorkflowCandidateGraphQuery={teamWorkflowCandidateGraphQuery}
        selectedTeamBuildCandidateGraphError={selectedTeamBuildCandidateGraphError}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

  function renderSourceCollectionMemoryPanel() {
    return (
      <TeamSourceCollectionMemoryInject
        lang={lang}
        teamWorkflowKnowledgeIngestionStatus={teamWorkflowKnowledgeIngestionStatus}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        teamWorkflowCandidatesById={teamWorkflowCandidatesById}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionMemoryStepState={sourceCollectionMemoryStepState}
        sourceCollectionCandidateFilterCounts={sourceCollectionCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        knowledgePendingReviewCount={knowledgePendingReviewCount}
        formalKnowledgeItemCount={formalKnowledgeItemCount}
        sourceCollectionApprovedCount={sourceCollectionApprovedCount}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        workflowIngestionTone={workflowIngestionToneBound}
        teamWorkflowKnowledgeIngestionStatusQuery={teamWorkflowKnowledgeIngestionStatusQuery}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

  function renderSourceCollectionModeFields() {
    return (
      <TeamSourceCollectionModeFields
        lang={lang}
        knowledgeExpansionWorkflowTeamSelected={knowledgeExpansionWorkflowTeamSelected}
        draft={sourceCollectionDraft}
        localScanDefaultRoots={SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS}
        onDraftChange={(patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch }))}
      />
    );
  }

  function handleSourceCollectionProjectResetSuccess() {
    sourceCollectionDraftHydratedRunIdRef.current = "";
    sourceCollectionDraftHydratedSearchPlanRef.current = "";
    setSelectedSourceCollectionRunId("");
    if (activeSourceCollectionResearchProject) {
      sourceCollectionFreshProjectDraftIdRef.current = activeSourceCollectionResearchProject.projectId;
      setSourceCollectionDraft(sourceCollectionFreshProjectDraft(activeSourceCollectionResearchProject));
    } else {
      sourceCollectionFreshProjectDraftIdRef.current = "";
    }
  }

  function runSourceCollectionProjectReset(includeDownstream: boolean) {
    if (!selectedTeam?.teamId || !sourceCollectionResetResearchProjectId) {
      return;
    }
    resetResearchProjectSourceCollectionMutation.mutate(
      {
        teamId: selectedTeam.teamId,
        researchProjectId: sourceCollectionResetResearchProjectId,
        includeDownstream,
      },
      {
        onSuccess: handleSourceCollectionProjectResetSuccess,
      },
    );
  }

  function renderSourceCollectionSearchBrief() {
    return (
      <TeamSourceCollectionSearchBriefShell
        lang={lang}
        resetAvailable={sourceCollectionResetAvailable}
        runCount={sourceCollectionRuns.length}
        resetPending={selectedResearchProjectSourceCollectionResetPending}
        resetIncludeDownstream={Boolean(
          resetResearchProjectSourceCollectionMutation.variables?.includeDownstream,
        )}
        resetError={
          selectedResearchProjectSourceCollectionResetError instanceof Error
            ? selectedResearchProjectSourceCollectionResetError
            : null
        }
        onReset={({ includeDownstream }) => runSourceCollectionProjectReset(includeDownstream)}
        draft={sourceCollectionDraft}
        modeFields={renderSourceCollectionModeFields()}
        hasExistingRun={Boolean(selectedSourceCollectionRun)}
        canStart={sourceCollectionCanStart}
        startPending={selectedTeamStartSourceCollectionPending}
        teamId={selectedTeam?.teamId}
        onDraftChange={(patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch }))}
        onStart={({ teamId, draft }) => {
          startSourceCollectionRunMutation.mutate({ teamId, draft });
        }}
      />
    );
  }

  function renderSourceCollectionManualWritebackPanel(options?: {
    title?: string;
    description?: string;
    wrapInDetails?: boolean;
  }) {
    return (
      <TeamSourceCollectionManualWritebackInject
        lang={lang}
        draft={sourceCollectionOutputDraft}
        assignments={sourceCollectionAssignments}
        selectedAssignmentId={selectedSourceCollectionAssignment?.assignmentId}
        canSubmit={canRecordSourceCollectionOutput}
        pending={selectedTeamRecordSourceCollectionOutputPending}
        teamId={selectedTeam?.teamId}
        runId={selectedSourceCollectionRunEffectiveId}
        hasRecord={sourceCollectionOutputHasRecord}
        onDraftChange={(patch) => setSourceCollectionOutputDraft((current) => ({ ...current, ...patch }))}
        onSubmitRecord={({ teamId, runId, draft }) => {
          recordSourceCollectionOutputMutation.mutate({ teamId, runId, draft });
        }}
        sourceTypeLabel={(sourceType) => sourceCollectionSourceTypeLabel(sourceType, lang)}
        title={options?.title}
        description={options?.description}
        wrapInDetails={options?.wrapInDetails}
      />
    );
  }

  function buildSourceCollectionControlsFeedbackProps() {
    return buildSourceCollectionControlsFeedbackBag({
      selectedTeamKnowledgeCollectionIngestResult,
      selectedTeamKnowledgeCollectionIngestError,
      selectedTeamStartSourceCollectionError,
      selectedTeamRecordSourceCollectionOutputError,
      selectedTeamExecuteSourceCollectionSearchError,
      selectedTeamStartSourceCollectionStageTaskError,
      selectedTeamExecuteSourceCollectionSearchResult,
      selectedTeamRecordSourceCollectionOutputResult,
    });
  }

  function buildSourceCollectionControlsMetricsProps() {
    return buildSourceCollectionControlsMetricsBag({
      sourceCollectionDisplayedCandidateCountText,
      sourceCollectionProjectedAssessedCountText,
      sourceCollectionProjectedApprovedCountText,
      sourceCollectionRunPendingScreeningCountText,
      candidateGraphNodeCount,
      candidateGraphEdgeCount,
      sourceCollectionPrecheckCandidateCount,
      knowledgePendingReviewCount,
      formalKnowledgeItemCount,
    });
  }

  function renderSourceCollectionControlsPanel() {
    return (
      <TeamSourceCollectionControlsInject
        lang={lang}
        sourceCollectionControlPanelRef={sourceCollectionControlPanelRef}
        sourceCollectionStageModules={sourceCollectionStageModules}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionStageFocusLabel={sourceCollectionStageFocusLabel}
        workflowIngestionTone={workflowIngestionToneBound}
        sourceCollectionRunStatus={sourceCollectionRunStatus}
        renderSourceCollectionSelectedSourcePanel={renderSourceCollectionSelectedSourcePanel}
        sourceCollectionDraft={sourceCollectionDraft}
        renderSourceCollectionModeFields={renderSourceCollectionModeFields}
        sourceCollectionCanStart={sourceCollectionCanStart}
        selectedTeamStartSourceCollectionPending={selectedTeamStartSourceCollectionPending}
        setSourceCollectionDraft={setSourceCollectionDraft}
        selectedTeam={selectedTeam}
        startSourceCollectionRunMutation={startSourceCollectionRunMutation}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        sourceCollectionFindingRunOptions={sourceCollectionFindingRunOptions}
        sourceCollectionFindingAssignments={sourceCollectionFindingAssignments}
        sourceCollectionFindingQueries={sourceCollectionFindingQueries}
        renderSourceCollectionStorageActions={renderSourceCollectionStorageActions}
        setSelectedSourceCollectionRunId={setSelectedSourceCollectionRunId}
        setSourceCollectionOutputDraft={setSourceCollectionOutputDraft}
        renderSourceCollectionManualWritebackPanel={renderSourceCollectionManualWritebackPanel}
        {...buildSourceCollectionControlsMetricsProps()}
        {...buildSourceCollectionControlsFeedbackProps()}
        renderSourceCollectionStageAgents={renderSourceCollectionStageAgents}
      />
    );
  }

  function buildActiveStageExtractionRecoveryBag() {
    return {
      candidateProjection: sourceCollectionCandidateProjection,
      sourceCollectionRawRecordCount,
      sourceCollectionRunApprovedCount,
      sourceCollectionDisplayedCandidateCount,
      sourceCollectionPrimaryDataLoading,
      sourceCollectionLoadingText,
      sourceCollectionCandidateStepState,
      sourceCollectionExtractionExcludedRecoveryState,
      runSourceCollectionCandidateExtractionAction,
      sourceCollectionCandidateExtractionActionReadiness,
      runSourceCollectionScreeningAction,
      sourceCollectionScreeningActionReadiness,
      sourceCollectionScreeningButtonText,
      sourceCollectionScreeningButtonTitle,
      sourceCollectionRunPendingScreeningCountText,
      sourceCollectionQualityBatchFeedback,
      needsAgentMaterial: sourceCollectionExtractionNeedsAgentMaterial,
      pendingScreeningCount: sourceCollectionRunPendingScreeningCount,
      pendingImportCount: sourceCollectionPendingCandidateImportCount,
      canProceedAfterExclusions: sourceCollectionExtractionCanProceedAfterExclusions,
      qualityReviewPending: selectedTeamSourceQualityPending,
      advanceToRelations: () => selectSourceCollectionStage("relations"),
      unverifiableCandidateCount: sourceCollectionUnverifiableCandidateIds.length,
      excludeUnverifiableCandidates: excludeUnverifiableSourceCollectionCandidates,
      excludeUnverifiableCandidatesPending: selectedTeamSourceQualityPending,
    };
  }

  function renderSourceCollectionActiveStagePanel() {
    return (
      <TeamSourceCollectionActiveStageInject
        lang={lang}
        sourceCollectionStageModules={sourceCollectionStageModules}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionStageAgentChatState={sourceCollectionStageAgentChatState}
        repairChallengeCupTeamAgentsMutation={repairChallengeCupTeamAgentsMutation}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        sourceCollectionStagePrimaryAgentBinding={sourceCollectionStagePrimaryAgentBinding}
        stageChatLabels={SOURCE_COLLECTION_STAGE_CHAT_LABELS}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        startSourceCollectionStageSessionTask={startSourceCollectionStageSessionTask}
        sourceCollectionRunAvailable={Boolean(selectedSourceCollectionRunEffectiveId)}
        sourceCollectionFindingStageCompact={sourceCollectionFindingStageCompact}
        selectedTeamStartSourceCollectionStageTaskError={selectedTeamStartSourceCollectionStageTaskError}
        renderSourceCollectionConversation={renderSourceCollectionConversation}
        renderSourceCollectionScreeningPanel={renderSourceCollectionScreeningPanel}
        renderSourceCollectionGraphPanel={renderSourceCollectionGraphPanel}
        renderSourceCollectionMemoryPanel={renderSourceCollectionMemoryPanel}
        extractionRecovery={buildActiveStageExtractionRecoveryBag()}
      />
    );
  }




  return {
    renderSourceCollectionStageAgents,
    renderSourceCollectionFilterBar,
    sourceCollectionPageItems,
    setSourceCollectionResultPage,
    stopSourceCollectionPaginationEvent,
    renderSourceCollectionPagination,
    renderSourceCollectionRunSwitcher,
    renderSourceCollectionConversation,
    renderSourceCollectionStorageActions,
    renderSourceCollectionSelectedSourcePanel,
    renderSourceCollectionScreeningPanel,
    renderSourceCollectionGraphPanel,
    renderSourceCollectionMemoryPanel,
    renderSourceCollectionModeFields,
    handleSourceCollectionProjectResetSuccess,
    runSourceCollectionProjectReset,
    renderSourceCollectionSearchBrief,
    renderSourceCollectionManualWritebackPanel,
    buildSourceCollectionControlsFeedbackProps,
    buildSourceCollectionControlsMetricsProps,
    renderSourceCollectionControlsPanel,
    buildActiveStageExtractionRecoveryBag,
    renderSourceCollectionActiveStagePanel,
  };
}
