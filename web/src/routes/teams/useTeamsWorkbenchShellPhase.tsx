/**
 * R2-r: shell surface bags + research surfaces + page returns.
 */
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
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
import { formatTime } from "./source-collection/presentationModel";
import { EMPTY_SOURCE_COLLECTION_DISPLAY_STATE } from "./source-collection/runModel";
import { researchStageStartFeedbackText as researchStageStartFeedbackTextFn } from "./teamRouteShellModel";
import { buildTeamsShellSurfaceModel } from "./teamsShellSurfaceModel";
import { TeamsLoadingShell } from "./TeamsLoadingShell";
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
  researchPrimaryActionDetail,
  researchPrimaryActionLabel,
  resolveResearchAdvanceAction,
  resolveResearchPrimaryAction,
  resolveResearchStageHandoff,
  resolveResearchStageUnlock,
} from "./researchPrimaryActionModel";
import {
  teamShellNodesFromCanvas,
  teamShellStagesFromBoardColumns,
} from "./teamShellStatusModel";
import { TeamCanvasReadOnlyInspector } from "./TeamCanvasReadOnlyInspector";
import { TeamNodeBindingPanel } from "./TeamNodeBindingPanel";
import {
  canonicalChallengeCupWorkspaceRouteForEffectiveTeam,
  isChallengeCupWorkspaceCanonicalizationEligible,
} from "./researchWorkspaceModel";

// Foundation bag boundary: the 328-field workbench bag stays any until Phase 9+ foundation typing.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
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
    selectedTeamStopRoundPending,
    selectedTeamStopRoundError,
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
    stopTeamRoundMutation,
    startSourceCollectionRunMutation,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    resumeExperimentHypothesisMutation,
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

  useEffect(() => {
    if (!challengeCupResearchTeamSelected || !effectiveTeamId) {
      return;
    }
    if (!isChallengeCupWorkspaceCanonicalizationEligible(searchParams.get("researchView"))) {
      return;
    }
    const canonicalHref = canonicalChallengeCupWorkspaceRouteForEffectiveTeam(effectiveTeamId, searchParams);
    const currentHref = `/teams?${searchParams.toString()}`;
    if (canonicalHref !== currentHref) {
      navigate(canonicalHref, { replace: true });
    }
  }, [challengeCupResearchTeamSelected, effectiveTeamId, navigate, searchParams]);

  const resolvedSourceCollectionDisplayState =
    sourceCollectionDisplayState ?? EMPTY_SOURCE_COLLECTION_DISPLAY_STATE;

  const activeWorkflowItemCount = teamWorkflow?.activeWorkflowItems.length ?? 0;
  /** Shell mode owns left/right IA: board = full team workbench, canvas = org graph. */
  const researchCanvasVisible = teamShellMode === "canvas" && !researchWorkflowTeamSelected;
  // The Challenge Cup workflow owns its process rail and split geometry inside
  // ResearchProcessWorkspace; the generic team shell must not mount a second rail.
  const suppressOuterTeamShellChrome =
    challengeCupResearchTeamSelected
    && (researchWorkspaceView === "workflow" || researchWorkspaceView === "overview");
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
      knowledgeStatusLabel: resolvedSourceCollectionDisplayState.statusText || "",
    }),
    [
      experimentPlanningStatus?.lifecycleProjection?.stage2?.activeDesignPlanId,
      experimentPlanningStatus?.lifecycleProjection?.stage3?.bestCandidateId,
      experimentPlanningStatus?.lifecycleProjection?.stage3?.latestDiagnosticStatus?.status,
      lang,
      researchPrimaryActionInput,
      selectedSourceCollectionRun?.runId,
      resolvedSourceCollectionDisplayState.statusText,
    ],
  );

  // Team data resolves asynchronously, so every hook must run before a render
  // can leave through the loading gate, canvas, or standalone workspace.
  const [boardInspectorNarrow, setBoardInspectorNarrow] = useState(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? false
      : !window.matchMedia("(min-width: 900px)").matches,
  );
  const [boardInspectorOverlayOpen, setBoardInspectorOverlayOpen] = useState(false);
  const toggleBoardInspectorOverlay = () => setBoardInspectorOverlayOpen((current) => !current);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(min-width: 900px)");
    const syncNarrow = (event: MediaQueryListEvent) => {
      setBoardInspectorNarrow(!event.matches);
      if (event.matches) {
        setBoardInspectorOverlayOpen(false);
      }
    };
    media.addEventListener("change", syncNarrow);
    return () => media.removeEventListener("change", syncNarrow);
  }, []);

  useEffect(() => {
    if (!boardInspectorNarrow || !boardInspectorOverlayOpen) {
      return;
    }
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setBoardInspectorOverlayOpen(false);
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [boardInspectorNarrow, boardInspectorOverlayOpen]);

  // Overview IA lives in ResearchOverviewSurface; workflow panel still hosts stage-specific modules.
  const isProcessWorkflowView =
    researchWorkspaceView === "workflow" || researchWorkspaceView === "overview";
  // Challenge Cup / research process: single canvas workspace owns the primary surface.
  const showWorkflowPanel =
    !aiSearchScopeTeamSelected
    && (!researchWorkflowTeamSelected
      || (!researchCanvasVisible
        && researchWorkspaceView !== "discussion"
        && !isProcessWorkflowView));
  const showAiSearchScopePanel = aiSearchScopeTeamSelected;
  const showTeamCommunicationPanel = !researchWorkflowTeamSelected || (!researchCanvasVisible && researchWorkspaceView === "discussion");
  const showResearchOverview = researchWorkflowTeamSelected && isProcessWorkflowView;
  // Stage pages collapsed into process workflow; no independent experiment/iteration shells.
  const showResearchStageWorkspace = false;
  const showResearchSourceCollection = false;
  const showResearchCoordination = researchWorkflowTeamSelected && researchWorkspaceView === "coordination";
  const showResearchIngestion = false;
  const showResearchGraph = false;
  const showResearchCandidates = false;
  const boardPrimaryMode =
    !researchWorkflowTeamSelected || researchCanvasVisible
      ? "hidden" as const
      : challengeCupResearchTeamSelected || isProcessWorkflowView
        || researchWorkspaceView === "experiment" || researchWorkspaceView === "iteration"
        ? "overview" as const
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

  if (showTeamInitialLoadingSurface) {
    return <TeamsLoadingShell lang={lang} />;
  }

  const statusStages = researchWorkflowTeamSelected
    ? teamShellStagesFromBoardColumns(researchBoardColumns, lang)
    : [];
  const statusNodes = researchCanvasVisible
    ? teamShellNodesFromCanvas(displayCanvasNodes ?? [], lang)
    : [];
  const statusNextTitle = researchWorkflowTeamSelected && researchPrimaryAction
    ? researchPrimaryActionLabel(researchPrimaryAction, lang)
    : (selectedTeam?.purpose || (lang === "zh" ? "组织画布" : "Organization canvas"));
  const statusNextBody = researchWorkflowTeamSelected && researchPrimaryAction
    ? researchPrimaryActionDetail(researchPrimaryAction, lang)
    : (lang === "zh"
      ? "点节点看执行者。切团队用顶栏，不要在左栏找名单。"
      : "Select a node to inspect the assignee. Switch teams in the toolbar.");
  const statusCta = researchWorkflowTeamSelected && researchPrimaryAction
    ? researchPrimaryActionLabel(researchPrimaryAction, lang)
    : undefined;

  const teamShellRail = renderTeamsShellRail({
    lang,
    statusNextTitle,
    statusNextBody,
    statusCta,
    statusCtaDisabled: Boolean(researchPrimaryAction?.blocked),
    onStatusCta: researchPrimaryAction
      ? () => {
        void handleResearchPrimaryAction(researchPrimaryAction);
      }
      : undefined,
    statusStages,
    statusNodes,
    selectedNodeId,
    onSelectNode: setSelectedNodeId,
  });

  const teamShellToolbar = renderTeamsShellToolbar({
    lang,
    teamName: selectedTeam?.name ?? "",
    purpose: selectedTeam?.purpose ?? "",
    teamShellMode,
    onModeChange: selectTeamShellMode,
    onRefreshTeams: () => void teamsQuery.refetch(),
    teamsFetching: teamsQuery.isFetching && Boolean(teamsQuery.data),
    styles,
    visibleTeams,
    effectiveTeamId,
    onSelectTeam: selectTeamRecord,
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
    statusNextTitle,
    statusNextBody,
    statusCta,
    statusCtaDisabled: Boolean(researchPrimaryAction?.blocked),
    onStatusCta: undefined,
    statusStages,
    statusNodes,
    selectedNodeId,
    onSelectNode: setSelectedNodeId,
    showGate: showTeamUnavailableSurface || showTeamDetailUnavailableSurface,
    ariaLabel: selectedTeamContextTitle,
    meta: teamContextMeta,
    gateMode: showTeamUnavailableSurface ? "unavailable" : "detail-unavailable",
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

  const researchStageStartFeedbackText =
    typeof d.researchStageStartFeedbackText === "function"
      ? d.researchStageStartFeedbackText
      : researchStageStartFeedbackTextFn;

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
    // Next-step / stage index live in the left status rail; inspector stays for node details.
    const researchFlowSlot = null;
    return renderTeamsWorkbenchCanvasPage({
      lang,
      styles,
      teamsRailResize,
      selectedTeamContextTitle,
      teamShellRail,
      teamShellToolbar,
      researchWorkflowTeamSelected,
      researchCanvasReadOnly,
      researchFlowSlot,
      hideCanvasToolbar: false,
      hideInspector: false,
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
      onToggleCommunicationEdges: () => setShowCommunicationEdges((current: boolean) => !current),
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
  // Hide on process workflow / overview so ResearchProcessWorkspace (VCanvasWorkbenchPage)
  // owns the full main column + its own node inspector — avoids double aside + dead space.
  const showBoardInspectorAside =
    researchWorkflowTeamSelected
    && !researchCanvasVisible
    && !isProcessWorkflowView
    && !boardInspectorNarrow;

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
    stageSlot: null,
    launcherSlot: renderResearchStageLauncher("interactive"),
    showBoardInspectorAside,
    suppressOuterShellChrome: suppressOuterTeamShellChrome,
    narrowInspector: boardInspectorNarrow,
    inspectorOverlayOpen: boardInspectorOverlayOpen,
    onToggleInspectorOverlay: toggleBoardInspectorOverlay,
    inspectorBody: (
      <>
        {selectedTeam && !challengeCupResearchTeamSelected ? renderTeamMemoryIndex() : null}
        {renderTeamsInspectorSharedPanels()}
      </>
    ),
  });
}
