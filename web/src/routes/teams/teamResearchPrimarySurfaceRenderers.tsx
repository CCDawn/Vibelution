/**
 * Research primary surface renderers (launcher / overview / stage standalone).
 * Extracted from TeamsRoute; does not own React state.
 */
import type { ReactNode } from "react";
import { ResearchOverviewSurface } from "./ResearchOverviewSurface";
import { ResearchStageNav } from "./ResearchStageNav";
import { ResearchWorkflowErrorSurface } from "./ResearchWorkflowErrorSurface";
import {
  TeamResearchStageLauncherPanel,
} from "./teamLazyPanels";
import { createExperimentController } from "./createExperimentController";
import { workflowStateLabel } from "./workflowPresentation";
import type { ResearchStageWorkspaceView } from "./researchWorkspaceModel";
import { ResearchProcessWorkspace } from "./research-workflow/ResearchProcessWorkspace";
import { TeamSourceCollectionSearchBriefPanel } from "./teamLazyPanels";

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
    researchAdvanceAction,
    researchStageHandoff,
    researchStageUnlock,
    researchAdvanceNotice,
    activeSourceCollectionResearchProject,
    handleResearchPrimaryAction,
    handleResearchAdvanceAction,
    selectedResearchProjectSourceCollectionResetError,
    selectedResearchProjectSourceCollectionResetPending,
    runSourceCollectionProjectReset,
    selectResearchWorkspaceView,
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
    renderChallengeCupStageAgentConfiguration,
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
        renderChallengeCupStageAgentConfiguration={renderChallengeCupStageAgentConfiguration}
      />
    );
  }

  function renderResearchProcessWorkflowSurface() {
    const knowledgeDrawer =
      ctx.renderSourceCollectionModeFields && ctx.setSourceCollectionDraft ? (
        <TeamSourceCollectionSearchBriefPanel
          lang={lang}
          draft={sourceCollectionDraft}
          modeFields={ctx.renderSourceCollectionModeFields()}
          hasExistingRun={Boolean(selectedSourceCollectionRun)}
          onDraftChange={(patch) =>
            setSourceCollectionDraft((current: Record<string, unknown>) => ({ ...current, ...patch }))
          }
        />
      ) : null;
    return (
      <ResearchProcessWorkspace
        teamId={String(selectedTeam?.teamId || selectedTeam?.id || ctx.effectiveTeamId || "")}
        experimentPanel={renderExperimentPlanningLedgerPanel ? renderExperimentPlanningLedgerPanel() : undefined}
        knowledgePanel={knowledgeDrawer ?? undefined}
      />
    );
  }

  function renderResearchOverviewSurface(options?: {
    trailingActions?: ReactNode;
    sideSlot?: ReactNode;
  }) {
    // Challenge Cup / research workflow team: canonical single-canvas workspace.
    if (
      researchWorkspaceView === "workflow"
      || (challengeCupResearchTeamSelected && researchWorkspaceView === "overview")
    ) {
      return renderResearchProcessWorkflowSurface();
    }
    // Progressive fill: mount the stable overview IA immediately.
    // Primary CTA keeps fixed geometry; metrics skeleton in place until queries settle.
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
        stageNav={(
          <ResearchStageNav
            lang={lang}
            current="overview"
            unlock={researchStageUnlock || {
              knowledge_collection: false,
              experiment: false,
              iteration: false,
            }}
            onSelect={(view) => selectResearchWorkspaceView(view)}
          />
        )}
        primary={{
          action: researchPrimaryAction,
          advanceAction: overviewWorkflowPending ? null : researchAdvanceAction,
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
          onAdvanceAction: (action) => {
            void handleResearchAdvanceAction(action);
          },
        }}
        notice={researchAdvanceNotice || undefined}
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
        trailingActions={options?.trailingActions}
        sideSlot={options?.sideSlot}
      />
    );
  }






  // P5/F4: experiment domain controller owns stage chrome + refresh (once per factory).
  const experimentController = createExperimentController({
    lang,
    selectedTeam,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    experimentPlanningStatusQuery,
    experimentPlanningStatus,
    researchStageUnlock,
    selectResearchWorkspaceView,
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
    experimentMethodCatalogQuery,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
  });

  function renderResearchStageStandalonePage(
    stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">,
    options?: { embeddedInBoard?: boolean },
  ) {
    return experimentController.renderStandalonePage(stageView, options);
  }


  return {
    renderResearchStageLauncher,
    renderResearchOverviewSurface,
    renderResearchStageStandalonePage,
  };
}
