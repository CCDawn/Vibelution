/**
 * R2-r: shell surface bags + research surfaces + page returns.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ReactNode } from "react";
import { useMemo } from "react";
import { buildTeamsWorkbenchResearchSurfacesFromBag } from "./buildTeamsWorkbenchResearchSurfacesFromBag";
import { renderTeamsWorkbenchCanvasPage } from "./renderTeamsWorkbenchCanvasPage";
import { renderTeamsWorkbenchBoardPage } from "./renderTeamsWorkbenchBoardPage";
import {
  TEAMS_BOARD_INSPECTOR_PANE,
  TEAMS_LAYOUT_ID,
  TEAMS_RAIL_PANE,
  nodeTone,
  roleBadgeTone,
  teamsWorkbenchStyles as styles,
  workflowIngestionToneBound,
  workflowQualityToneBound,
} from "./teamsWorkbenchChrome";
import { buildTeamsShellSurfaceModel } from "./teamsShellSurfaceModel";
import { buildTeamWorkflowCandidatePreviewItems } from "./buildTeamWorkflowCandidatePreviewItems";
import { buildSourceCollectionOverviewBag } from "./buildSourceCollectionOverviewBag";
import {
  renderTeamsShellGate,
  renderTeamsShellRail,
  renderTeamsShellToolbar,
} from "./renderTeamsShellFrame";
import { ResearchStageNav } from "./ResearchStageNav";
import { ResearchProjectSwitcher } from "./research-projects/ResearchProjectSwitcher";
import { buildResearchBoardColumns } from "./researchBoardModel";
import {
  resolveResearchAdvanceAction,
  resolveResearchPrimaryAction,
  resolveResearchStageHandoff,
  resolveResearchStageUnlock,
} from "./researchPrimaryActionModel";
import { TeamCanvasReadOnlyInspector } from "./TeamCanvasReadOnlyInspector";
import { TeamNodeBindingPanel } from "./TeamNodeBindingPanel";

export function useTeamsWorkbenchShellPhase(d: any): ReactNode {
  const {
    effectiveTeamId,
    activeSourceCollectionResearchProjectId,
    researchWorkflowTeamSelected,
    researchProjectProgress,
    researchStagePhases,
    researchWorkspaceView,
    lang,
    selectedTeam,
    researchStageRoundStatus,
    teamWorkflowCandidates,
    teamWorkflowCandidatesQuery,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    teamWorkflowCandidateGraphQuery,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowPaperNoteChunkStatus,
    teamWorkflow,
    experimentPlanningStatusQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    searchParams,
    navigate,
    sourceCollectionStandalone,
    selectResearchWorkspaceView,
    launchResearchStage,
    styles,
    teamWorkflowKnowledgeIngestionStatus,
    teamWorkflowCandidateGraph,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionStageReturnRoute,
    sourceCollectionStagePrimaryAgentBinding,
    openSourceCollectionStageAgentChat,
    workflowIngestionToneBound,
    experimentPlanningStatus,
    renderSourceCollectionStandalonePage,
    selectSourceCollectionStage,
    selectedTeamAssessSourceQualityPending,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamSourceQualityPending,
    selectedTeamStartSourceCollectionError,
    selectedTeamStartSourceCollectionResult,
    sourceCollectionAssignmentRunSummaryText,
    sourceCollectionBoardNextStepLabel,
    sourceCollectionCollectedCountLabel,
    sourceCollectionCollectedCountText,
    sourceCollectionCollectedRunSummaryText,
    sourceCollectionConsoleState,
    sourceCollectionConsoleStatusText,
    sourceCollectionDisplayState,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionFindingStageCompact,
    sourceCollectionPhaseCloseGate,
    sourceCollectionPromptCacheMode,
    sourceCollectionPromptCacheStatus,
    sourceCollectionQueryCountText,
    sourceCollectionRunStatus,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionStandaloneStageModules,
    sourceCollectionStepClassName,
    linkedChatRoomId,
    linkedChatRoomQuery,
    detail,
    teamBusEvents,
    validation,
    selectedTeamSyncPending,
    selectedTeamArchivePending,
    selectedTeamArchiveDisabledReason,
    selectedTeamStartRoundPending,
    selectedTeamStartRoundResult,
    selectedTeamStartRoundError,
    selectedTeamMessagePending,
    selectedTeamMessageResult,
    selectedTeamMessageError,
    saveLabel,
    activeTeamMemberCount,
    conversationProjection,
    linkedRoomDetail,
    latestTeamRound,
    linkedRoomBusy,
    canStartTeamRound,
    communicationEdgeHint,
    communicationEdgeButtonLabel,
    teamWorkflowValidationSummary,
    teamWorkflowCandidateGraphLayout,
    teamWorkflowCoordinationStatus,
    teamWorkflowOfficialModelEvidenceStatus,
    researchProjectProgressQuery,
    researchPrimaryActionInput,
    researchPrimaryAction,
    researchAdvanceAction,
    researchStageHandoff,
    researchStageUnlock,
    teamsQuery,
    projectBusQuery,
    activeAgents,
    teams,
    visibleTeams,
    visibleTeamSummary,
    hasTeams,
    selectedNodeId,
    setSelectedNodeId,
    teamMessage,
    setTeamMessage,
    teamInterrupt,
    setTeamInterrupt,
    teamTaskTopic,
    setTeamTaskTopic,
    showCommunicationEdges,
    setShowCommunicationEdges,
    setResearchCanvasLayoutMode,
    teamShellMode,
    challengeTeamSurface,
    canvasFrameRef,
    teamDetailLoadMode,
    selectedTeamReference,
    teamDetailQuery,
    selectedTeamDetailLoading,
    challengeCupResearchTeamSelected,
    aiSearchScopeTeamSelected,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    activeSourceCollectionResearchProject,
    sourceCollectionRunsQuery,
    sourceCollectionRuns,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSelectedRunTopic,
    sourceCollectionSelectedRunQueryCount,
    sourceCollectionSummaryQuery,
    sourceCollectionAssignmentsQuery,
    researchCanvasReadOnly,
    teamCanvasQuery,
    canvas,
    hasWritableCanvas,
    organizationEdges,
    communicationEdges,
    researchCanvasAutoLayoutActive,
    displayCanvasNodes,
    visibleEdges,
    canvasViewportStyle,
    teamWorkflowQuery,
    researchStageRoundStatusQuery,
    teamWorkflowCoordinationStatusQuery,
    teamWorkflowOfficialModelEvidenceStatusQuery,
    teamWorkflowPaperNoteChunkStatusQuery,
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentMethodCatalogQuery,
    archiveTeamMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    startTeamRoundMutation,
    startSourceCollectionRunMutation,
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
    executeSourceCollectionSearchMutation,
    assessSourceQualityMutation,
    planPaperNoteChunksMutation,
    selectTeamRecord,
    selectTeamShellMode,
    handleResearchPrimaryAction,
    handleResearchAdvanceAction,
    addNode,
    startNodeDrag,
    moveNodeDrag,
    finishNodeDrag,
    nodeTone,
    roleBadgeTone,
    TEAMS_BOARD_INSPECTOR_PANE,
    TEAMS_RAIL_PANE,
    scComposition,
    workflowQualityToneBound,
    TEAMS_LAYOUT_ID
  } = d;


  const activeWorkflowItemCount = teamWorkflow?.activeWorkflowItems.length ?? 0;
  /** Shell mode owns left/right IA: board = full team workbench, canvas = org graph. */
  const researchCanvasVisible = teamShellMode === "canvas";
  // Board/Canvas page recipes own split geometry; rail + inspector widths persist via layoutId.
  const teamsRailResize = useMemo(
    () => ({
      sidebar: {
        id: TEAMS_RAIL_PANE.id,
        defaultWidth: TEAMS_RAIL_PANE.defaultWidth,
        minWidth: TEAMS_RAIL_PANE.minWidth,
        maxWidth: TEAMS_RAIL_PANE.maxWidth,
      },
      aside: {
        id: TEAMS_BOARD_INSPECTOR_PANE.id,
        defaultWidth: TEAMS_BOARD_INSPECTOR_PANE.defaultWidth,
        minWidth: TEAMS_BOARD_INSPECTOR_PANE.minWidth,
        maxWidth: TEAMS_BOARD_INSPECTOR_PANE.maxWidth,
      },
    }),
    [],
  );
  const shellSurface = buildTeamsShellSurfaceModel({
    lang,
    hasTeams,
    teamsPending: teamsQuery.isPending,
    teamsError: teamsQuery.isError,
    teamsData: teamsQuery.data,
    teamsErrorMessage: teamsQuery.error instanceof Error ? teamsQuery.error.message : "",
    effectiveTeamId,
    selectedTeamReference,
    selectedTeam,
    selectedTeamDetailLoading,
    selectedTeamDetailUnavailableBase: Boolean(
      effectiveTeamId && selectedTeamReference && !teamDetailQuery.data && teamDetailQuery.isError,
    ),
    researchWorkflowTeamSelected,
    researchCanvasVisible,
    researchCanvasReadOnly,
    teamDetailErrorMessage: teamDetailQuery.error instanceof Error ? teamDetailQuery.error.message : "",
    visibleTeamSummary,
    styles,
  });
  const {
    teamListInitialLoading,
    teamListUnavailable,
    showTeamInitialLoadingSurface,
    showTeamUnavailableSurface,
    selectedTeamDetailUnavailable,
    researchTeamDetailDegraded,
    showTeamLoadingSurface,
    showTeamDetailUnavailableSurface,
    teamInitialLoadingTitle,
    teamInitialLoadingMessage,
    teamUnavailableTitle,
    teamUnavailableMessage,
    teamUnavailableDetail,
    teamWorkspaceLoadingTitle,
    teamWorkspaceLoadingMessage,
    teamWorkspaceUnavailableTitle,
    teamWorkspaceUnavailableMessage,
    teamWorkspaceUnavailableDetail,
    teamContextMeta,
    teamSummaryUnavailableText,
    teamListMetricLoadingLabel,
    teamSummaryStatusItems,
    showNodeBindingPanel,
  } = shellSurface;

  const researchBoardColumns = useMemo(
    () => buildResearchBoardColumns({
      lang,
      phases: researchPrimaryActionInput.phases,
      sourceRunCount: researchPrimaryActionInput.sourceRunCount,
      sourceCandidateCount: researchPrimaryActionInput.sourceCandidateCount ?? 0,
      experimentDesignFrozen: researchPrimaryActionInput.experimentDesignFrozen,
      frozenDesignLabel: experimentPlanningStatus?.lifecycleProjection?.stage2?.activeDesignPlanId
        || (researchPrimaryActionInput.experimentDesignFrozen
          ? (lang === "zh" ? "冻结设计" : "Frozen design")
          : ""),
      bestCandidateId: experimentPlanningStatus?.lifecycleProjection?.stage3?.bestCandidateId || "",
      latestDiagnostic: experimentPlanningStatus?.lifecycleProjection?.stage3?.latestDiagnosticStatus?.status || "",
      sourceRunLabel: selectedSourceCollectionRun?.runId
        ? String(selectedSourceCollectionRun.runId).slice(0, 18)
        : "",
      knowledgeStatusLabel: sourceCollectionDisplayState.statusText || "",
    }),
    [
      experimentPlanningStatus?.lifecycleProjection?.stage2?.activeDesignPlanId,
      experimentPlanningStatus?.lifecycleProjection?.stage3?.bestCandidateId,
      experimentPlanningStatus?.lifecycleProjection?.stage3?.latestDiagnosticStatus?.status,
      lang,
      researchPrimaryActionInput,
      selectedSourceCollectionRun?.runId,
      sourceCollectionDisplayState.statusText,
    ],
  );
  // Overview IA lives in ResearchOverviewSurface; workflow panel still hosts stage-specific modules.
  const showWorkflowPanel =
    !aiSearchScopeTeamSelected
    && (!researchWorkflowTeamSelected || (!researchCanvasVisible && researchWorkspaceView !== "discussion" && researchWorkspaceView !== "overview"));
  const showAiSearchScopePanel = aiSearchScopeTeamSelected;
  const showTeamCommunicationPanel = !researchWorkflowTeamSelected || (!researchCanvasVisible && researchWorkspaceView === "discussion");
  const showResearchOverview = researchWorkflowTeamSelected && researchWorkspaceView === "overview";
  const showResearchStageWorkspace =
    researchWorkflowTeamSelected
    && !researchCanvasVisible
    && (researchWorkspaceView === "experiment" || researchWorkspaceView === "iteration");
  const showResearchSourceCollection = researchWorkflowTeamSelected && researchWorkspaceView === "source_collection";
  const showResearchCoordination = researchWorkflowTeamSelected && researchWorkspaceView === "coordination";
  const showResearchIngestion = researchWorkflowTeamSelected && researchWorkspaceView === "ingestion";
  const showResearchGraph = researchWorkflowTeamSelected && researchWorkspaceView === "graph";
  const showResearchCandidates = researchWorkflowTeamSelected && researchWorkspaceView === "candidates";
  const boardPrimaryMode =
    !researchWorkflowTeamSelected || researchCanvasVisible
      ? "hidden" as const
      : researchWorkspaceView === "overview"
        ? "overview" as const
        : researchWorkspaceView === "experiment" || researchWorkspaceView === "iteration"
          ? "stage" as const
          : "launcher" as const;
  const teamWorkflowCandidatePreviewItems = buildTeamWorkflowCandidatePreviewItems({
    lang,
    teamWorkflowCandidates,
    selectedTeam,
    selectedTeamAssessSourceQualityPending,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamSourceQualityPending,
    assessSourceQualityMutation,
    planPaperNoteChunksMutation,
  });

  const {
    sourceCollectionOverviewSummary,
    sourceCollectionOverviewStatus,
    sourceCollectionOverviewStats,
    sourceCollectionOverviewPlan,
    sourceCollectionOverviewAssignmentEmptyMessage,
    sourceCollectionOverviewBoundaryItems,
    sourceCollectionOverviewErrors,
    sourceCollectionOverviewResult,
  } = buildSourceCollectionOverviewBag({
    lang,
    selectedSourceCollectionRun,
    sourceCollectionRunsQueryPending: sourceCollectionRunsQuery.isPending,
    sourceCollectionCollectedRunSummaryText,
    sourceCollectionAssignmentRunSummaryText,
    sourceCollectionRunStatus,
    sourceCollectionCollectedCountText,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionQueryCountText,
    sourceCollectionPromptCacheStatus,
    sourceCollectionPromptCacheMode,
    selectedTeamStartSourceCollectionResult,
    sourceCollectionAssignmentsQueryPending: sourceCollectionAssignmentsQuery.isPending,
    selectedTeamStartSourceCollectionError,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
  });

  const selectedTeamContextTitle = selectedTeam
    ? [
      selectedTeam.name,
      selectedTeam.purpose || selectedTeam.teamId,
      `${lang === "zh" ? "成员引用" : "Members"} ${selectedTeam.memberCount}`,
      `${lang === "zh" ? "活跃成员" : "Active members"} ${activeTeamMemberCount}`,
      `${lang === "zh" ? "更新" : "Updated"} ${formatTime(selectedTeam.updatedAt, lang)}`,
      `${lang === "zh" ? "成员源" : "Member source"} Agent Center`,
    ].filter(Boolean).join("\n")
    : teamListInitialLoading
      ? (lang === "zh" ? "正在读取团队索引。" : "Loading the team index.")
      : (lang === "zh" ? "仅显示 AI 搜索、知识库扩充和挑战杯科研团队。" : "Only AI search, knowledge expansion, and research teams are shown.");
  const visibleTeamOptions = visibleTeams.length
    ? visibleTeams.map((team) => ({
      id: team.teamId,
      label: team.name,
      description: team.purpose || team.teamId,
    }))
    : [{
      id: "",
      label: lang === "zh" ? "正在读取团队" : "Loading teams",
    }];

  // P5/F1: SC full-page workbench via domain controller (no team rail).
  if (sourceCollectionStandalone) {
    return renderSourceCollectionStandalonePage({
      researchStageUnlock,
      selectResearchWorkspaceView,
      linkedChatRoomId: linkedChatRoomId || undefined,
      syncTeamChatRoomMutation,
      selectedTeamSyncPending,
      activeTeamMemberCount,
      sourceCollectionRunsQuery,
      styles,
      sourceCollectionStepClassName,
      sourceCollectionConsoleState,
      sourceCollectionConsoleStatusText,
      researchWorkflowTeamSelected,
      showTeamDetailUnavailableSurface,
      showTeamLoadingSurface,
      teamWorkspaceLoadingTitle,
      teamWorkspaceLoadingMessage,
      teamWorkspaceUnavailableTitle,
      teamWorkspaceUnavailableDetail,
      teamWorkspaceUnavailableMessage,
      teamDetailQuery,
      sourceCollectionSelectedRunTopic,
      selectedSourceCollectionRun,
      sourceCollectionSelectedRunQueryCount,
      sourceCollectionBoardNextStepLabel,
      sourceCollectionCollectedCountLabel,
      sourceCollectionPhaseCloseGate,
      sourceCollectionSummaryQuery,
      selectSourceCollectionStage,
      sourceCollectionStandaloneStageModules,
      sourceCollectionFindingStageCompact,
    });
  }

  const teamShellRail = renderTeamsShellRail({
    lang,
    visibleTeams,
    effectiveTeamId,
    onSelectTeam: selectTeamRecord,
  });

  const teamShellToolbar = renderTeamsShellToolbar({
    lang,
    teamName: selectedTeam?.name ?? "",
    purpose: selectedTeam?.purpose ?? "",
    teamShellMode,
    onModeChange: selectTeamShellMode,
    onRefreshTeams: () => void teamsQuery.refetch(),
    styles,
  });

  const shellGate = renderTeamsShellGate({
    lang,
    styles,
    visibleTeams,
    effectiveTeamId,
    onSelectTeam: selectTeamRecord,
    teamName: selectedTeam?.name ?? "",
    purpose: selectedTeam?.purpose ?? "",
    teamShellMode,
    onModeChange: selectTeamShellMode,
    onRefreshTeams: () => void teamsQuery.refetch(),
    showGate: showTeamInitialLoadingSurface || showTeamUnavailableSurface || showTeamDetailUnavailableSurface,
    ariaLabel: selectedTeamContextTitle,
    meta: teamContextMeta,
    gateMode: showTeamInitialLoadingSurface
      ? "initial-loading"
      : showTeamUnavailableSurface
        ? "unavailable"
        : "detail-unavailable",
    initialTitle: teamInitialLoadingTitle,
    initialMessage: teamInitialLoadingMessage,
    listMetricLoadingLabel: teamListMetricLoadingLabel,
    unavailableTitle: teamUnavailableTitle,
    unavailableMessage: teamUnavailableMessage,
    unavailableDetail: teamUnavailableDetail,
    listUnavailable: teamListUnavailable,
    summaryUnavailableText: teamSummaryUnavailableText,
    activeTeamCount: visibleTeamSummary.activeTeamCount,
    memberCount: visibleTeamSummary.memberCount,
    teamsFetching: teamsQuery.isFetching,
    detailTitle: teamWorkspaceUnavailableTitle,
    detailMessage: teamWorkspaceUnavailableMessage,
    detailDetail: teamWorkspaceUnavailableDetail,
    teamNameForDetail: selectedTeamReference?.name,
    teamId: effectiveTeamId,
    detailLoadMode: teamDetailLoadMode,
    detailFetching: teamDetailQuery.isFetching,
    onRefreshDetail: () => void teamDetailQuery.refetch(),
  });
  if (shellGate) {
    return shellGate;
  }

  const researchSurfaces = buildTeamsWorkbenchResearchSurfacesFromBag({
    ...d,
    scComposition,
    styles,
    activeWorkflowItemCount,
    researchBoardColumns,
    researchStageStartFeedbackText,
    teamWorkflowCandidatePreviewItems,
    teamWorkflowCandidateGraphLayout,
    sourceCollectionOverviewAssignmentEmptyMessage,
    sourceCollectionOverviewBoundaryItems,
    sourceCollectionOverviewErrors,
    sourceCollectionOverviewPlan,
    sourceCollectionOverviewResult,
    sourceCollectionOverviewStats,
    sourceCollectionOverviewStatus,
    sourceCollectionOverviewSummary,
    showAiSearchScopePanel,
    showResearchCandidates,
    showResearchCoordination,
    showResearchGraph,
    showResearchIngestion,
    showResearchSourceCollection,
    showTeamCommunicationPanel,
    showWorkflowPanel,
    workflowIngestionToneBound,
  });

  const {
    renderAiSearchSourceScopePanel,
    renderExperimentPlanningLedgerPanel,
    renderKnowledgeCollectionCompletionFlowPanel,
    renderResearchCanvasReadOnlyPanel,
    renderResearchLoopPanel,
    renderResearchOverviewSurface,
    renderResearchStageAgentPanel,
    renderResearchStageAgentSummary,
    renderResearchStageLauncher,
    renderResearchStageStandalonePage,
    renderResearchWorkflowModules,
    renderResearchWorkflowPanel,
    renderTeamCommunicationPanel,
    renderTeamMemoryIndex,
    renderTeamNodeBindingPanel,
    renderTeamsInspectorSharedPanels,
    researchWorkflowStatusText,
  } = researchSurfaces;

  if (researchCanvasVisible) {
    return renderTeamsWorkbenchCanvasPage({
      lang,
      styles,
      teamsRailResize,
      selectedTeamContextTitle,
      teamShellRail,
      teamShellToolbar,
      researchWorkflowTeamSelected,
      researchCanvasReadOnly,
      validationValid: !(validation && !validation.valid),
      inspectorBody: renderTeamsInspectorSharedPanels(),
      selectedTeam,
      selectedTeamReferenceName: selectedTeamReference?.name,
      effectiveTeamId,
      teamDetailLoadMode,
      canvas,
      displayCanvasNodes,
      visibleEdges,
      selectedNodeId,
      activeAgents,
      researchCanvasAutoLayoutActive,
      showCommunicationEdges,
      organizationEdgeCount: organizationEdges.length,
      communicationEdgeCount: communicationEdges.length,
      communicationEdgeHint,
      communicationEdgeButtonLabel,
      saveLabel,
      hasWritableCanvas,
      linkedChatRoomId: linkedChatRoomId || "",
      activeTeamMemberCount,
      teamSyncPending: selectedTeamSyncPending,
      teamArchivePending: selectedTeamArchivePending,
      teamArchiveDisabledReason: selectedTeamArchiveDisabledReason || "",
      conversationStatus: conversationProjection?.status,
      conversationMissingAgentCount: conversationProjection?.missingAgentCount,
      showTeamLoadingSurface,
      teamWorkspaceLoadingTitle,
      teamWorkspaceLoadingMessage,
      teamDetailPending: teamDetailQuery.isPending,
      teamCanvasPending: teamCanvasQuery.isPending,
      teamDetailError: teamDetailQuery.isError,
      teamCanvasError: teamCanvasQuery.isError,
      canvasViewportStyle,
      canvasFrameRef,
      nodeToneClass: nodeTone,
      roleBadgeToneClass: roleBadgeTone,
      completionFlowSlot: renderKnowledgeCollectionCompletionFlowPanel(),
      onSelectNode: setSelectedNodeId,
      onLayoutModeChange: setResearchCanvasLayoutMode,
      onToggleCommunicationEdges: () => setShowCommunicationEdges((current) => !current),
      onAddNode: addNode,
      onArchiveTeam: () => selectedTeam?.teamId && archiveTeamMutation.mutate(selectedTeam.teamId),
      onSyncRoom: () => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId),
      onNodePointerDown: startNodeDrag,
      onNodePointerMove: moveNodeDrag,
      onNodePointerUp: finishNodeDrag,
      onNodePointerCancel: finishNodeDrag,
    });
  }

  // Right inspector column: stage tools / workflow (not stacked under primary → empty floor).
  // Hide on pure overview so the kanban can use full main width; show for stage/launcher/KC.
  const showBoardInspectorAside =
    researchWorkflowTeamSelected
    && !researchCanvasVisible
    && researchWorkspaceView !== "overview";

  if (
    researchWorkflowTeamSelected
    && (researchWorkspaceView === "experiment" || researchWorkspaceView === "iteration")
  ) {
    return renderResearchStageStandalonePage(
      researchWorkspaceView === "iteration" ? "iteration" : "experiment",
      { embeddedInBoard: false },
    );
  }

  return renderTeamsWorkbenchBoardPage({
    lang,
    styles,
    teamsRailResize,
    selectedTeamContextTitle,
    teamShellRail,
    teamShellToolbar,
    boardPrimaryMode,
    workflowPending: teamWorkflowQuery.isPending,
    workflowReady: Boolean(teamWorkflow),
    challengeCupResearchTeamSelected,
    overviewSlot: renderResearchOverviewSurface(),
    stageSlot: showResearchStageWorkspace
      ? renderResearchStageStandalonePage(
          researchWorkspaceView === "iteration" ? "iteration" : "experiment",
          { embeddedInBoard: true },
        )
      : null,
    launcherSlot: renderResearchStageLauncher("interactive"),
    showBoardInspectorAside,
    inspectorBody: (
      <>
        {selectedTeam && !challengeCupResearchTeamSelected ? renderTeamMemoryIndex() : null}
        {renderTeamsInspectorSharedPanels()}
      </>
    ),
  });
}
