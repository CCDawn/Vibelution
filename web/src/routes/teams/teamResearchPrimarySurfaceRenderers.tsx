/**
 * Research primary surface renderers (launcher / overview / stage standalone).
 * Extracted from TeamsRoute; does not own React state.
 */
import { ResearchBoardKanban } from "./ResearchBoardKanban";
import { ResearchOverviewSurface } from "./ResearchOverviewSurface";
import { ResearchWorkflowErrorSurface } from "./ResearchWorkflowErrorSurface";
import {
  TeamResearchStageLauncherPanel,
  TeamResearchStageStandalonePagePanel,
  TeamWorkflowModelEvidenceStatusPanel,
} from "./teamLazyPanels";
import { workflowIngestionStatusLabel } from "./source-collection/presentationModel";
import { workflowStateLabel } from "./workflowPresentation";
import type { ResearchStageWorkspaceView } from "./researchWorkspaceModel";

/** Loose context bag from TeamsRoute. */
export type ResearchPrimarySurfaceRenderContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createResearchPrimarySurfaceRenderers(ctx: ResearchPrimarySurfaceRenderContext) {
  const {
    lang,
    styles,
    researchWorkspaceView,
    researchWorkflowTeamSelected,
    challengeCupResearchTeamSelected,
    knowledgeExpansionWorkflowTeamSelected,
    selectedTeam,
    selectedTeamMemoryMembers,
    challengeTeamSurface,
    researchTeamDetailDegraded,
    selectedTeamDetailLoading,
    teamDetailQuery,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    sourceCollectionDisplayState,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionAssignment,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionSearchOpenAssignmentCountText,
    selectedTeamExecuteSourceCollectionSearchPending,
    sourceCollectionAcceptedBackgroundActive,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionRunPendingScreeningCount,
    selectedTeamStartSourceCollectionPending,
    sourceCollectionCanStart,
    sourceCollectionSearchActionReadiness,
    sourceCollectionActionInitialDataPending,
    sourceCollectionActionDataError,
    sourceCollectionActionBusyReason,
    sourceCollectionActionNoInputReason,
    sourceCollectionActionLoadingReason,
    sourceCollectionActionErrorReason,
    sourceCollectionActionReadiness,
    executeSourceCollectionSearchMutation,
    startSourceCollectionRunMutation,
    sourceCollectionCollectedCountText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionQueryCountText,
    runKnowledgeCollectionLoopAction,
    sourceCollectionLoopActionDisabled,
    sourceCollectionActionDisabledTitle,
    sourceCollectionLoopActionReadiness,
    sourceCollectionLoopActionLabel,
    sourceCollectionLoopStartsNewRun,
    selectedTeamStartResearchStagePending,
    researchStageCanLaunch,
    launchResearchStage,
    researchStageRoundStatus,
    researchStageRoundStatusQuery,
    researchStagePhases,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    researchStageStartFeedbackText,
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    navigate,
    searchParams,
    renderResearchStageAgentSummary,
    teamWorkflowQuery,
    researchProjectProgressQuery,
    activeSourceCollectionResearchProjectId,
    researchProjectProgress,
    teamWorkflow,
    sourceCollectionRuns,
    researchPrimaryAction,
    researchStageHandoff,
    activeSourceCollectionResearchProject,
    handleResearchPrimaryAction,
    selectedResearchProjectSourceCollectionResetError,
    selectedResearchProjectSourceCollectionResetPending,
    runSourceCollectionProjectReset,
    researchBoardColumns,
    selectResearchWorkspaceView,
    activeWorkflowItemCount,
    teamWorkflowOfficialModelEvidenceStatus,
    teamWorkflowOfficialModelEvidenceStatusQuery,
    teamWorkflowValidationSummary,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    renderResearchStageAgentPanel,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
  } = ctx;

  function renderResearchStageLauncher(presentationMode: "overview" | "interactive" = researchWorkspaceView === "overview" ? "overview" : "interactive") {
    return (
      <TeamResearchStageLauncherPanel
        lang={lang}
        presentationMode={presentationMode}
        team={{
          researchWorkflowSelected: researchWorkflowTeamSelected,
          challengeCupSelected: challengeCupResearchTeamSelected,
          knowledgeExpansionSelected: knowledgeExpansionWorkflowTeamSelected,
          selected: selectedTeam,
          memoryMembers: selectedTeamMemoryMembers,
          challengeSurface: challengeTeamSurface,
          detailDegraded: researchTeamDetailDegraded,
          detailLoading: selectedTeamDetailLoading,
          detailQuery: teamDetailQuery,
        }}
        sourceCollection={{
          draft: sourceCollectionDraft,
          setDraft: setSourceCollectionDraft,
          displayState: sourceCollectionDisplayState,
          selectedRun: selectedSourceCollectionRun,
          selectedRunEffectiveId: selectedSourceCollectionRunEffectiveId,
          selectedAssignment: selectedSourceCollectionAssignment,
          searchOpenAssignmentCount: sourceCollectionSearchOpenAssignmentCount,
          searchOpenAssignmentCountText: sourceCollectionSearchOpenAssignmentCountText,
          executeSearchPending: selectedTeamExecuteSourceCollectionSearchPending,
          acceptedBackgroundActive: sourceCollectionAcceptedBackgroundActive,
          downstreamOpenAssignmentCount: sourceCollectionDownstreamOpenAssignmentCount,
          downstreamOpenAssignmentCountText: sourceCollectionDownstreamOpenAssignmentCountText,
          pendingScreeningCount: sourceCollectionRunPendingScreeningCount,
          startPending: selectedTeamStartSourceCollectionPending,
          canStart: sourceCollectionCanStart,
          searchActionReadiness: sourceCollectionSearchActionReadiness,
          actionInitialDataPending: sourceCollectionActionInitialDataPending,
          actionDataError: sourceCollectionActionDataError,
          actionBusyReason: sourceCollectionActionBusyReason,
          actionNoInputReason: sourceCollectionActionNoInputReason,
          actionLoadingReason: sourceCollectionActionLoadingReason,
          actionErrorReason: sourceCollectionActionErrorReason,
          actionReadiness: sourceCollectionActionReadiness,
          executeSearchMutation: executeSourceCollectionSearchMutation,
          startRunMutation: startSourceCollectionRunMutation,
          collectedCountText: sourceCollectionCollectedCountText,
          displayedCandidateCountText: sourceCollectionDisplayedCandidateCountText,
          queryCountText: sourceCollectionQueryCountText,
          runLoopAction: runKnowledgeCollectionLoopAction,
          loopActionDisabled: sourceCollectionLoopActionDisabled,
          actionDisabledTitle: sourceCollectionActionDisabledTitle,
          loopActionReadiness: sourceCollectionLoopActionReadiness,
          loopActionLabel: sourceCollectionLoopActionLabel,
          loopStartsNewRun: sourceCollectionLoopStartsNewRun,
        }}
        researchStage={{
          startPending: selectedTeamStartResearchStagePending,
          canLaunch: researchStageCanLaunch,
          launch: launchResearchStage,
          roundStatus: researchStageRoundStatus,
          roundStatusQuery: researchStageRoundStatusQuery,
          phases: researchStagePhases,
          startError: selectedTeamStartResearchStageError,
          startResult: selectedTeamStartResearchStageResult,
          startFeedbackText: researchStageStartFeedbackText,
        }}
        experiment={{
          preferredMethod: preferredExperimentMethod,
          setPreferredMethod: setPreferredExperimentMethod,
          planningStatus: experimentPlanningStatus,
          planningStatusQuery: experimentPlanningStatusQuery,
          methodCatalogQuery: experimentMethodCatalogQuery,
        }}
        navigation={{
          navigate,
          searchParams,
        }}
        renderResearchStageAgentSummary={renderResearchStageAgentSummary}
      />
    );
  }

  function renderResearchOverviewSurface() {
    // Progressive fill: mount the stable overview IA immediately.
    // Primary CTA + three-column board keep geometry; only inner slots skeleton
    // until each query settles. Never return null just because workflow is pending.
    const overviewWorkflowPending = teamWorkflowQuery.isPending;
    const overviewProgressPending = researchProjectProgressQuery.isPending
      && Boolean(activeSourceCollectionResearchProjectId);
    const stageLabelSource =
      researchProjectProgress?.currentStage
      || teamWorkflow?.stateMachine.currentStage
      || "";
    const stageMetricReady = Boolean(stageLabelSource) || (!overviewWorkflowPending && !overviewProgressPending);
    const sourcesMetricReady =
      researchProjectProgress != null
      || !overviewProgressPending
      || sourceCollectionRuns.length > 0
      || !overviewWorkflowPending;
    const candidatesMetricReady =
      researchProjectProgress != null
      || teamWorkflow != null
      || (!overviewWorkflowPending && !overviewProgressPending);
    const sourcesValue = researchProjectProgress?.sourceRunCount ?? sourceCollectionRuns.length;
    const candidatesValue =
      researchProjectProgress?.sourceCandidateCount
      ?? teamWorkflow?.candidateStore.candidateCount
      ?? 0;

    return (
      <ResearchOverviewSurface
        lang={lang}
        className={styles.researchOverviewSurface}
        primary={{
          action: researchPrimaryAction,
          handoff: overviewWorkflowPending ? null : researchStageHandoff,
          pending: selectedTeamStartResearchStagePending,
          loading: overviewWorkflowPending,
          projectName: activeSourceCollectionResearchProject?.name || researchProjectProgress?.experimentName || "",
          metrics: [
            {
              key: "stage",
              label: lang === "zh" ? "阶段" : "Stage",
              value: stageMetricReady ? workflowStateLabel(stageLabelSource, lang) : null,
              loading: !stageMetricReady,
            },
            {
              key: "sources",
              label: lang === "zh" ? "资料批次" : "Runs",
              value: sourcesMetricReady ? String(sourcesValue) : null,
              loading: !sourcesMetricReady,
            },
            {
              key: "candidates",
              label: lang === "zh" ? "候选" : "Candidates",
              value: candidatesMetricReady ? String(candidatesValue) : null,
              loading: !candidatesMetricReady,
            },
          ],
          onPrimaryAction: (action) => {
            void handleResearchPrimaryAction(action);
          },
        }}
        errorSlot={
          selectedResearchProjectSourceCollectionResetError ? (
            <ResearchWorkflowErrorSurface
              lang={lang}
              message={selectedResearchProjectSourceCollectionResetError.message}
              pending={selectedResearchProjectSourceCollectionResetPending}
              onRecommendedAction={(action) => {
                if (action !== "reset_progress_cascade" && action !== "reset_source_only") {
                  return;
                }
                runSourceCollectionProjectReset(action === "reset_progress_cascade");
              }}
            />
          ) : undefined
        }
        stages={(
          <ResearchBoardKanban
            lang={lang}
            loading={overviewWorkflowPending}
            columns={researchBoardColumns}
            onOpenCard={(columnId) => {
              if (columnId === "knowledge_collection") {
                selectResearchWorkspaceView("knowledge_collection");
                return;
              }
              if (columnId === "experiment") {
                selectResearchWorkspaceView("experiment");
                return;
              }
              selectResearchWorkspaceView("iteration");
            }}
          />
        )}
        advanced={teamWorkflow ? (
          <>
            <div className={styles.workflowStats}>
              <div>
                <span>{lang === "zh" ? "当前阶段" : "Stage"}</span>
                <strong>{workflowStateLabel(teamWorkflow.stateMachine.currentStage, lang)}</strong>
              </div>
              <div>
                <span>{lang === "zh" ? "候选" : "Candidates"}</span>
                <strong>{teamWorkflow.candidateStore.candidateCount}</strong>
              </div>
              <div>
                <span>{lang === "zh" ? "活跃项" : "Active"}</span>
                <strong>{activeWorkflowItemCount}</strong>
              </div>
            </div>
            <div className={styles.workflowMeta}>
              <span>{teamWorkflow.workflowKind}</span>
              <span className="truncate" title={teamWorkflow.ownerAgentId}>{teamWorkflow.ownerAgentId}</span>
            </div>
            <TeamWorkflowModelEvidenceStatusPanel
              lang={lang}
              status={teamWorkflowOfficialModelEvidenceStatus}
              loading={teamWorkflowOfficialModelEvidenceStatusQuery.isPending}
              errorMessages={teamWorkflowOfficialModelEvidenceStatusQuery.error instanceof Error ? [teamWorkflowOfficialModelEvidenceStatusQuery.error.message] : []}
              statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
            />
            {teamWorkflowValidationSummary && !teamWorkflowValidationSummary.skipped ? (
              <div className={styles.workflowValidation}>
                <span>{lang === "zh" ? "校验" : "Validation"}</span>
                <strong>
                  {teamWorkflowValidationSummary.validCandidateCount}/{teamWorkflowValidationSummary.candidateCount}
                </strong>
                <span>{teamWorkflowValidationSummary.errorCount} errors</span>
                <span>{teamWorkflowValidationSummary.warningCount} warnings</span>
              </div>
            ) : teamWorkflowValidationSummary?.skipped ? (
              <div className={styles.empty}>{lang === "zh" ? "候选校验已延后。" : "Validation deferred."}</div>
            ) : null}
          </>
        ) : undefined}
      />
    );
  }





  function renderResearchStageStandalonePage(
    stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">,
    options?: { embeddedInBoard?: boolean },
  ) {
    const refreshStageWorkspace = () => {
      createExperimentPlanMutation.reset();
      materializeEngineeringProxyHypothesisMutation.reset();
      completeScientificHypothesisFromDesignMutation.reset();
      reviewExperimentHypothesisMutation.reset();
      createExperimentHypothesisRevisionMutation.reset();
      freezeExperimentDesignMutation.reset();
      registerExperimentBaselineArtifactMutation.reset();
      runExperimentSmokeMutation.reset();
      registerExperimentSmokeResultMutation.reset();
      registerExperimentFullRunResultMutation.reset();
      requestExperimentKnowledgeIngestionMutation.reset();
      createResearchLoopMutation.reset();
      recordResearchLoopEvidenceMutation.reset();
      recordResearchLoopDecisionMutation.reset();
      materializeResearchLoopIterationDesignMutation.reset();
      void Promise.all([
        researchStageRoundStatusQuery.refetch(),
        experimentPlanningStatusQuery.refetch(),
        experimentMethodCatalogQuery.refetch(),
        researchLoopTemplatesQuery.refetch(),
        researchLoopStatusQuery.refetch(),
      ]);
    };

    return (
      <TeamResearchStageStandalonePagePanel
        stageView={stageView}
        lang={lang}
        researchStagePhases={researchStagePhases}
        experimentPlanningStatus={experimentPlanningStatus}
        experimentPlanningStatusQuery={experimentPlanningStatusQuery}
        selectedTeam={selectedTeam}
        selectedTeamStartResearchStagePending={selectedTeamStartResearchStagePending}
        linkedChatRoomId={linkedChatRoomId || ""}
        syncTeamChatRoomMutation={syncTeamChatRoomMutation}
        activeTeamMemberCount={activeTeamMemberCount}
        selectedTeamSyncPending={selectedTeamSyncPending}
        researchStageRoundStatusQuery={researchStageRoundStatusQuery}
        refreshStageWorkspace={refreshStageWorkspace}
        renderResearchStageAgentPanel={renderResearchStageAgentPanel}
        launchResearchStage={launchResearchStage}
        selectedTeamStartResearchStageError={selectedTeamStartResearchStageError}
        selectedTeamStartResearchStageResult={selectedTeamStartResearchStageResult}
        researchStageStartFeedbackText={researchStageStartFeedbackText}
        renderExperimentPlanningLedgerPanel={renderExperimentPlanningLedgerPanel}
        renderResearchLoopPanel={renderResearchLoopPanel}
        embeddedInBoard={options?.embeddedInBoard ?? true}
      />
    );
  }


  return {
    renderResearchStageLauncher,
    renderResearchOverviewSurface,
    renderResearchStageStandalonePage,
  };
}
