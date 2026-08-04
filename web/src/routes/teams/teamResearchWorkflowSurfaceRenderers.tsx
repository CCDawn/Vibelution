/**
 * Research workflow / communication surface renderers extracted from TeamsRoute.
 * Route owns state/mutations; this factory mounts already-extracted panels.
 */
import { TeamCommunicationPanel } from "./TeamCommunicationPanel";
import { TeamResearchWorkflowPanelHost } from "./TeamResearchWorkflowPanelHost";
import { TeamResearchWorkflowStageModules } from "./TeamResearchWorkflowStageModules";

/** Loose context bag from TeamsRoute. */
export type ResearchWorkflowSurfaceRenderContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createResearchWorkflowSurfaceRenderers(ctx: ResearchWorkflowSurfaceRenderContext) {
  const {
    lang,
    researchWorkflowTeamSelected,
    teamWorkflow,
    teamWorkflowQuery,
    showResearchSourceCollection,
    showResearchCoordination,
    showResearchIngestion,
    showResearchGraph,
    showResearchCandidates,
    sourceCollectionOverviewSummary,
    sourceCollectionOverviewStatus,
    workflowIngestionToneBound,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    renderSourceCollectionModeFields,
    sourceCollectionCanStart,
    selectedTeamStartSourceCollectionPending,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionFindingRunOptions,
    sourceCollectionOverviewStats,
    sourceCollectionFindingAssignments,
    sourceCollectionOverviewAssignmentEmptyMessage,
    sourceCollectionFindingQueries,
    sourceCollectionPhaseCloseGate,
    sourceCollectionSummaryQuery,
    selectSourceCollectionStage,
    renderSourceCollectionStorageActions,
    sourceCollectionOverviewPlan,
    renderSourceCollectionManualWritebackPanel,
    sourceCollectionOverviewBoundaryItems,
    sourceCollectionOverviewErrors,
    sourceCollectionOverviewResult,
    selectedTeam,
    startSourceCollectionRunMutation,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    teamWorkflowCoordinationStatus,
    teamWorkflowCoordinationStatusQuery,
    teamWorkflowKnowledgeIngestionStatus,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowCandidateGraph,
    teamWorkflowCandidateGraphLayout,
    teamWorkflowCandidateGraphQuery,
    selectedTeamBuildCandidateGraphError,
    sourceCollectionGraphActionLabel,
    sourceCollectionGraphActionDisabled,
    sourceCollectionActionDisabledTitle,
    sourceCollectionGraphActionReadiness,
    runSourceCollectionGraphAction,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    selectedTeamSourceQualityError,
    teamWorkflowPaperNoteChunkStatus,
    teamWorkflowPaperNoteChunkStatusQuery,
    selectedTeamPlanPaperNoteChunksError,
    teamWorkflowCandidatePreviewItems,
    sourceCollectionScreeningDisabled,
    sourceCollectionScreeningActionReadiness,
    teamWorkflowCandidates,
    openSourceCollectionCandidatePanel,
    openSourceCollectionScreeningPanel,
    showWorkflowPanel,
    teamWorkflowCandidatesQuery,
    showTeamCommunicationPanel,
    linkedChatRoomId,
    linkedRoomDetail,
    linkedRoomBusy,
    linkedChatRoomQuery,
    latestTeamRound,
    teamTaskTopic,
    setTeamTaskTopic,
    canStartTeamRound,
    selectedTeamStartRoundPending,
    selectedTeamStartRoundResult,
    selectedTeamStartRoundError,
    startTeamRoundMutation,
    teamMessage,
    setTeamMessage,
    teamInterrupt,
    setTeamInterrupt,
    activeTeamMemberCount,
    selectedTeamMessagePending,
    selectedTeamMessageResult,
    selectedTeamMessageError,
    sendTeamMessageMutation,
    teamBusEvents,
    projectBusQuery,
    revokeTeamMessageMutation,
    researchCanvasReadOnly,
    renderResearchCanvasReadOnlyPanel,
    renderTeamNodeBindingPanel,
    showAiSearchScopePanel,
    renderAiSearchSourceScopePanel,
  } = ctx;

  function researchWorkflowStatusText() {
    if (!researchWorkflowTeamSelected) {
      return lang === "zh" ? "非科研团队" : "not research";
    }
    if (teamWorkflow?.status) {
      return teamWorkflow.status;
    }
    if (teamWorkflowQuery.isPending) {
      return lang === "zh" ? "读取中" : "loading";
    }
    return lang === "zh" ? "待初始化" : "not initialized";
  }

  function renderResearchWorkflowModules() {
    return (
      <TeamResearchWorkflowStageModules
        lang={lang}
        visibility={{
          sourceCollection: showResearchSourceCollection,
          coordination: showResearchCoordination,
          ingestion: showResearchIngestion,
          graph: showResearchGraph,
          candidates: showResearchCandidates,
        }}
        sourceCollection={{
          summary: sourceCollectionOverviewSummary,
          statusLabel: sourceCollectionOverviewStatus || "",
          statusClassName: workflowIngestionToneBound(sourceCollectionOverviewStatus),
          draft: sourceCollectionDraft,
          modeFields: renderSourceCollectionModeFields(),
          canStart: sourceCollectionCanStart,
          startPending: selectedTeamStartSourceCollectionPending,
          selectedRunId: selectedSourceCollectionRunEffectiveId,
          runs: sourceCollectionFindingRunOptions,
          stats: sourceCollectionOverviewStats,
          assignments: sourceCollectionFindingAssignments,
          assignmentEmptyMessage: sourceCollectionOverviewAssignmentEmptyMessage,
          queries: sourceCollectionFindingQueries,
          phaseCloseGate: sourceCollectionPhaseCloseGate,
          phaseCloseGateLoading: Boolean(
            selectedSourceCollectionRunEffectiveId
            && sourceCollectionSummaryQuery.isPending
            && !sourceCollectionSummaryQuery.data,
          ),
          onOpenStage: selectSourceCollectionStage,
          storageActions: renderSourceCollectionStorageActions(),
          plan: sourceCollectionOverviewPlan,
          manualWriteback: renderSourceCollectionManualWritebackPanel({
            title: lang === "zh" ? "手工回写一条搜集结果" : "Manual result writeback",
            description: lang === "zh" ? "写 DataRecord 后自动导入 source_manifest 候选" : "Writes DataRecord, then imports source_manifest candidate",
            wrapInDetails: false,
          }),
          boundaryItems: sourceCollectionOverviewBoundaryItems,
          errorMessages: sourceCollectionOverviewErrors,
          result: sourceCollectionOverviewResult,
          onDraftChange: (patch) => setSourceCollectionDraft((current: Record<string, unknown>) => ({ ...current, ...patch })),
          onStart: () => {
            if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
              return;
            }
            startSourceCollectionRunMutation.mutate({
              teamId: selectedTeam.teamId,
              draft: sourceCollectionDraft,
            });
          },
          onRunChange: setSelectedSourceCollectionRunId,
          onAssignmentSelect: (assignmentId: string) => setSourceCollectionOutputDraft((current: Record<string, unknown>) => ({ ...current, assignmentId })),
        }}
        coordination={{
          status: teamWorkflowCoordinationStatus,
          loading: teamWorkflowCoordinationStatusQuery.isPending,
          errorMessages: teamWorkflowCoordinationStatusQuery.error instanceof Error
            ? [teamWorkflowCoordinationStatusQuery.error.message]
            : [],
        }}
        ingestion={{
          status: teamWorkflowKnowledgeIngestionStatus,
          loading: teamWorkflowKnowledgeIngestionStatusQuery.isPending,
          errorMessages: teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error
            ? [teamWorkflowKnowledgeIngestionStatusQuery.error.message]
            : [],
        }}
        graph={{
          graph: teamWorkflowCandidateGraph,
          layout: teamWorkflowCandidateGraphLayout,
          loading: teamWorkflowCandidateGraphQuery.isPending,
          errorMessages: [
            ...(teamWorkflowCandidateGraphQuery.error instanceof Error
              ? [teamWorkflowCandidateGraphQuery.error.message]
              : []),
            ...(selectedTeamBuildCandidateGraphError
              ? [selectedTeamBuildCandidateGraphError.message]
              : []),
          ],
          actionLabel: sourceCollectionGraphActionLabel,
          actionDisabled: sourceCollectionGraphActionDisabled,
          actionTitle: sourceCollectionActionDisabledTitle(
            sourceCollectionGraphActionReadiness,
            sourceCollectionGraphActionLabel,
          ),
          onAction: runSourceCollectionGraphAction,
        }}
        candidates={{
          sourceQualityStatus: teamWorkflowSourceQualityStatus,
          sourceQualityLoading: teamWorkflowSourceQualityStatusQuery.isPending,
          sourceQualityErrors: [
            ...(teamWorkflowSourceQualityStatusQuery.error instanceof Error
              ? [teamWorkflowSourceQualityStatusQuery.error.message]
              : []),
            ...(selectedTeamSourceQualityError ? [selectedTeamSourceQualityError.message] : []),
          ],
          paperNoteChunkStatus: teamWorkflowPaperNoteChunkStatus,
          paperNoteChunkLoading: teamWorkflowPaperNoteChunkStatusQuery.isPending,
          paperNoteChunkErrors: [
            ...(teamWorkflowPaperNoteChunkStatusQuery.error instanceof Error
              ? [teamWorkflowPaperNoteChunkStatusQuery.error.message]
              : []),
            ...(selectedTeamPlanPaperNoteChunksError
              ? [selectedTeamPlanPaperNoteChunksError.message]
              : []),
          ],
          previewItems: teamWorkflowCandidatePreviewItems,
          canOpenLibrary: Boolean(selectedTeam?.teamId),
          reviewDisabled: sourceCollectionScreeningDisabled,
          reviewTitle: sourceCollectionActionDisabledTitle(
            sourceCollectionScreeningActionReadiness,
            lang === "zh" ? "进入资料提炼复核" : "Open review",
          ) || "",
          candidateCount: teamWorkflowCandidates.length,
          onOpenLibrary: openSourceCollectionCandidatePanel,
          onOpenReview: openSourceCollectionScreeningPanel,
        }}
      />
    );
  }

  function renderResearchWorkflowPanel() {
    if (!showWorkflowPanel) {
      return null;
    }
    return (
      <TeamResearchWorkflowPanelHost
        lang={lang}
        researchWorkflowTeamSelected={researchWorkflowTeamSelected}
        statusText={researchWorkflowStatusText()}
        workflowPending={teamWorkflowQuery.isPending}
        workflowReady={Boolean(teamWorkflow)}
        workflowErrorMessage={
          teamWorkflowQuery.error instanceof Error ? teamWorkflowQuery.error.message : null
        }
        candidatesErrorMessage={
          teamWorkflowCandidatesQuery.error instanceof Error
            ? teamWorkflowCandidatesQuery.error.message
            : null
        }
      >
        {renderResearchWorkflowModules()}
      </TeamResearchWorkflowPanelHost>
    );
  }

  function renderTeamCommunicationPanel() {
    if (!showTeamCommunicationPanel) {
      return null;
    }
    return (
      <TeamCommunicationPanel
        lang={lang}
        selectedTeam={selectedTeam}
        linkedChatRoomId={linkedChatRoomId}
        linkedRoomDetail={linkedRoomDetail}
        linkedRoomBusy={linkedRoomBusy}
        linkedChatRoomPending={linkedChatRoomQuery.isPending}
        linkedChatRoomError={linkedChatRoomQuery.error instanceof Error ? linkedChatRoomQuery.error : null}
        latestTeamRound={latestTeamRound}
        teamTaskTopic={teamTaskTopic}
        onTeamTaskTopicChange={setTeamTaskTopic}
        canStartTeamRound={canStartTeamRound}
        startRoundPending={selectedTeamStartRoundPending}
        startRoundResult={selectedTeamStartRoundResult}
        startRoundError={selectedTeamStartRoundError}
        onStartTeamRound={(payload) => startTeamRoundMutation.mutate(payload)}
        teamMessage={teamMessage}
        onTeamMessageChange={setTeamMessage}
        teamInterrupt={teamInterrupt}
        onTeamInterruptChange={setTeamInterrupt}
        activeTeamMemberCount={activeTeamMemberCount}
        messagePending={selectedTeamMessagePending}
        messageResult={selectedTeamMessageResult}
        messageError={selectedTeamMessageError}
        onSendTeamMessage={(payload) => sendTeamMessageMutation.mutate(payload)}
        teamBusEvents={teamBusEvents}
        projectBusPending={projectBusQuery.isPending}
        revokePendingEventId={
          revokeTeamMessageMutation.isPending
            ? (revokeTeamMessageMutation.variables?.eventId || null)
            : null
        }
        revokeError={revokeTeamMessageMutation.error instanceof Error ? revokeTeamMessageMutation.error : null}
        onRevokeTeamMessage={(payload) => revokeTeamMessageMutation.mutate(payload)}
      />
    );
  }


  function renderTeamsInspectorSharedPanels() {
    return (
      <>
        {researchCanvasReadOnly ? renderResearchCanvasReadOnlyPanel() : null}
        {renderTeamNodeBindingPanel()}
        {showAiSearchScopePanel ? renderAiSearchSourceScopePanel() : null}
        {renderResearchWorkflowPanel()}
        {renderTeamCommunicationPanel()}
      </>
    );
  }



  return {
    researchWorkflowStatusText,
    renderResearchWorkflowModules,
    renderResearchWorkflowPanel,
    renderTeamCommunicationPanel,
    renderTeamsInspectorSharedPanels,
  };
}
