/**
 * R2-c: Teams workbench model — queries, mutations, SC/research composition, early returns.
 * `TeamsRouteWorkbench` is a thin route entry that calls this hook.
 */

import {
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { createExperimentWorkspaceActions } from "./experimentWorkspaceActions";
import { useTeamsSecondaryDataQueries } from "./useTeamsSecondaryDataQueries";
import { useTeamsMutationBundle } from "./useTeamsMutationBundle";
import { useTeamsScComposition } from "./useTeamsScComposition";
import { useTeamsWorkbenchScLayer } from "./useTeamsWorkbenchScLayer";
import { buildResearchStageAgentBindingsByStage } from "./researchStageAgentBindings";
import { createTeamsResearchNavigation } from "./createTeamsResearchNavigation";
import { createResearchStageLaunchHandlers } from "./createResearchStageLaunchHandlers";
import { createSourceCollectionStageAgentHelpers } from "./createSourceCollectionStageAgentHelpers";
import { buildExperimentWorkspacePendingFlags } from "./buildExperimentWorkspacePendingFlags";
import { useSourceCollectionWorkspace } from "./useSourceCollectionWorkspace";
import { useResearchExperimentWorkspace } from "./useResearchExperimentWorkspace";
import {
  useTeamsCanvasProjection,
  useTeamsShellCanvasWorkspace,
} from "./useTeamsShellCanvasWorkspace";
import { useTeamsCatalogQueries } from "./useTeamsCatalogQueries";
import { useTeamsSelectedTeamDetail } from "./useTeamsSelectedTeamDetail";
import { resolveTeamWorkflowResourceDemand } from "./teamWorkflowResourceDemand";
import {
  TEAMS_BOARD_INSPECTOR_PANE,
  TEAMS_LAYOUT_ID,
  TEAMS_RAIL_PANE,
  nodeTone,
  roleBadgeTone,
  teamsWorkbenchStyles as styles,
  workflowIngestionToneBound,
  workflowQualityToneBound,
  type TeamsRouteProps,
} from "./teamsWorkbenchChrome";
export type { TeamsRouteProps } from "./teamsWorkbenchChrome";
import {
  formatTime,
} from "./source-collection/presentationModel";
import { createTeamCanvasNodeEditing } from "./useTeamCanvasNodeEditing";
import {
  parseResearchWorkspaceView,
  teamWorkspaceRoute,
} from "./researchWorkspaceModel";
import {
  resolveResearchAdvanceAction,
  resolveResearchPrimaryAction,
  resolveResearchStageHandoff,
  resolveResearchStageUnlock,
} from "./researchPrimaryActionModel";
import { buildResearchBoardColumns } from "./researchBoardModel";
import { TeamCanvasReadOnlyInspector } from "./TeamCanvasReadOnlyInspector";
import { TeamNodeBindingPanel } from "./TeamNodeBindingPanel";
import {
  renderTeamsShellGate,
  renderTeamsShellRail,
  renderTeamsShellToolbar,
} from "./renderTeamsShellFrame";
import { buildTeamsShellSurfaceModel } from "./teamsShellSurfaceModel";
import { buildTeamWorkflowCandidatePreviewItems } from "./buildTeamWorkflowCandidatePreviewItems";
import { buildSourceCollectionOverviewBag } from "./buildSourceCollectionOverviewBag";
import { ResearchStageNav } from "./ResearchStageNav";
import {
  parseTeamShellMode,
} from "./teamShellModel";
import { ResearchProjectSwitcher } from "./research-projects/ResearchProjectSwitcher";
import { getTeamResearchProjectProgress } from "../../api/researchProjectAgentTasks";
import {
  systemManagedTeamArchiveReason,
} from "./teamKindModel";
import { fetchJson } from "../../api/client";
import {
  projectAgentBusEventsForTeam,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import {
  ChatRoomDetail,
  Team,
} from "../../api/types";
import { useShellI18n } from "../../i18n/useShellI18n";
import { usePageVisibility } from "../../app/pollingPolicy";
import {
  agentCenterMemoryRoute,
  teamMemoryRoute,
} from "../agentCenterRoutes";
import { agentDisplayInfo } from "../agentDisplay";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { TeamMemoryIndexMember } from "../TeamMemoryIndexPanel";
import {
  useResearchWorkflowResources,
} from "./useResearchWorkflowResources";
import {
  sourceCollectionStageTaskClickKey,
} from "./teamWorkflowQueryKeys";
import {
  resolveLinkedChatRoomQueryEnabled,
  resolveResearchSecondaryStatusQueryEnabled,
} from "./teamDetailLoadPolicy";
import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentManagementRoute,
  researchStageAgentModelLabel,
  sourceCollectionAgentIdsFromTeam,
  sourceCollectionOwnerAgentIdFromTeam,
  teamChatRoomRoute,
} from "./researchStageAgentPresentation";
import {
  isRecord,
  linkedRoomRefetchInterval,
} from "./workflowPresentation";
import {
  latestChatRoomRound,
  latestWorkflowCandidate,
  parseSourceCollectionStageModuleId,
  researchStageStartFeedbackText,
  workflowCandidateGraphFromCandidate,
} from "./teamRouteShellModel";
import { workflowGraphLayout } from "../TeamWorkflowGraphLayout";
import {
  RESEARCH_TEAM_ID,
} from "../TeamsRoute.canvasData";
import {
  ChallengeCupOperationsWorkspace,
} from "./challenge-cup/ChallengeCupOperationsWorkspace";
export function useTeamsWorkbenchFoundation({
  forcedTeamId = "",
  forcedResearchWorkspaceView,
  sourceCollectionStandalone: sourceCollectionStandaloneProp = false,
}: TeamsRouteProps = {}): Record<string, any> {
  const { lang } = useShellI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedResearchViewParam = searchParams.get("researchView");
  const requestedResearchWorkspaceView = parseResearchWorkspaceView(searchParams.get("researchView"));
  const requestedSourceCollectionStage = parseSourceCollectionStageModuleId(searchParams.get("collectionStage"));
  const sourceCollectionStandalone =
    sourceCollectionStandaloneProp || requestedResearchWorkspaceView === "knowledge_collection" || requestedResearchViewParam === "source_collection";
  const pageVisible = usePageVisibility();
  const requestedTeamShellMode = parseTeamShellMode(searchParams.get("teamMode"));
  const [aiSearchRunTopic, setAiSearchRunTopic] = useState("AI 最新动态");
  const [researchAdvanceNotice, setResearchAdvanceNotice] = useState("");
  /** Product outcome for stage advance button: must never stay silent on failure. */
  const [sourceCollectionStageAdvanceFailure, setSourceCollectionStageAdvanceFailure] = useState("");
  // Shell/canvas state: useTeamsShellCanvasWorkspace (Phase 3).
  // Experiment/research-loop drafts: useResearchExperimentWorkspace (Phase 2).
  // Catalog list/bootstrap: useTeamsCatalogQueries (R2-d).
  const sourceCollectionControlPanelRef = useRef<HTMLElement | null>(null);
  // Late-bound: mutations hook is declared above scroll helper; keep stable identity via ref.
  const scrollSourceCollectionPanelIntoViewRef = useRef<(panelId: string) => void>(() => {});

  const requestedTeamId = searchParams.get("team") ?? "";
  const requestedAgentId = searchParams.get("agent") ?? "";
  const {
    teamsQuery,
    agentSummaryQuery,
    projectBusQuery,
    activeAgents,
    activeAgentsById,
    teams,
    visibleTeams,
    visibleTeamIds,
    visibleTeamSummary,
    hasTeams,
    agentTeamMembership,
    requestedAgentTeamId,
    requestedVisibleTeamId,
    requestedVisibleAgentTeamId,
    fallbackVisibleTeamId,
  } = useTeamsCatalogQueries({
    pageVisible,
    requestedTeamId,
    requestedAgentId,
  });
  const {
    selectedTeamId,
    setSelectedTeamId,
    selectedNodeId,
    setSelectedNodeId,
    nodeDraft,
    setNodeDraft,
    teamMessage,
    setTeamMessage,
    teamInterrupt,
    setTeamInterrupt,
    teamTaskTopic,
    setTeamTaskTopic,
    showCommunicationEdges,
    setShowCommunicationEdges,
    researchCanvasLayoutMode,
    setResearchCanvasLayoutMode,
    researchWorkspaceView,
    setResearchWorkspaceView,
    teamShellMode,
    setTeamShellMode,
    challengeTeamSurface,
    setChallengeTeamSurface,
    nodePositionDrafts,
    setNodePositionDrafts,
    canvasFrameSize,
    setCanvasFrameSize,
    lockedCanvasViewportStyle,
    setLockedCanvasViewportStyle,
    canvasFrameRef,
    dragStateRef,
    dragFrameRef,
  } = useTeamsShellCanvasWorkspace({
    forcedResearchWorkspaceView,
    requestedResearchWorkspaceView,
    requestedTeamShellMode,
    requestedVisibleTeamId,
    requestedVisibleAgentTeamId,
    visibleTeamIds,
    fallbackVisibleTeamId,
  });
  const {
    selectedVisibleTeamId,
    effectiveTeamId,
    teamDetailLoadMode,
    selectedTeamReference,
    teamDetailQuery,
    selectedTeam,
    selectedTeamDetailLoading,
    knowledgeExpansionWorkflowTeamSelected,
    researchWorkflowTeamSelected,
    challengeCupResearchTeamSelected,
    researchStageProjectAgentTasks,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
  } = useTeamsSelectedTeamDetail({
    forcedTeamId,
    selectedTeamId,
    requestedTeamId,
    requestedAgentTeamId,
    visibleTeamIds,
    fallbackVisibleTeamId,
    visibleTeams,
    sourceCollectionStandalone,
    researchWorkspaceView,
  });

  const sourceCollectionWorkspace = useSourceCollectionWorkspace({
    effectiveTeamId,
    pageVisible,
    researchWorkflowTeamSelected,
    sourceCollectionWorkspaceSelected,
    initialStageId: requestedSourceCollectionStage ?? null,
  });
  const {
    sourceCollectionDraft,
    setSourceCollectionDraft,
    selectedSourceCollectionRunId,
    setSelectedSourceCollectionRunId,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    selectedSourceCollectionStageId,
    setSelectedSourceCollectionStageId,
    sourceCollectionStageSyncUntilMs,
    setSourceCollectionStageSyncUntilMs,
    sourceCollectionPendingStageTaskIds,
    setSourceCollectionPendingStageTaskIds,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionFocusedPanelId,
    setSourceCollectionFocusedPanelId,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    sourceCollectionDraftHydratedRunIdRef,
    sourceCollectionDraftHydratedSearchPlanRef,
    sourceCollectionFreshProjectDraftIdRef,
    sourceCollectionResearchProjectsQuery,
    activeSourceCollectionResearchProjectId,
    activeSourceCollectionResearchProject,
    sourceCollectionRunsQuery,
    sourceCollectionRuns,
    sourceCollectionLatestRun,
    sourceCollectionHistoricalRunWithRecords,
    selectedSourceCollectionRun,
    sourceCollectionLatestRunIsEmpty,
    sourceCollectionShowingHistoricalRunByDefault,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSelectedRunTopic,
    sourceCollectionSelectedRunGoal,
    sourceCollectionSelectedRunQueryCount,
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionPendingStageTaskIdList,
    sourceCollectionStageWritebackAwaitingTask,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
  } = sourceCollectionWorkspace;
  const {
    aiSearchRunsQuery,
  } = useTeamsSecondaryDataQueries({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
    researchWorkspaceView,
  });
  const {
    researchCanvasReadOnly,
    teamCanvasQueryEnabled,
    teamCanvasQuery,
    durableCanvas,
    canvas,
    hasWritableCanvas,
    canvasNodes,
    organizationEdges,
    communicationEdges,
    autoLayoutCanvasNodes,
    researchCanvasAutoLayoutActive,
    displayCanvasNodes,
    selectedNode,
    visibleCommunicationEdges,
    visibleEdges,
    autoCanvasViewportStyle,
    canvasViewportStyle,
    canvasScale,
  } = useTeamsCanvasProjection({
    effectiveTeamId,
    selectedTeam,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    teamShellMode,
    sourceCollectionStandalone,
    selectedNodeId,
    nodePositionDrafts,
    showCommunicationEdges,
    researchCanvasLayoutMode,
    canvasFrameSize,
    lockedCanvasViewportStyle,
    setNodeDraft,
    setNodePositionDrafts,
    setLockedCanvasViewportStyle,
    dragStateRef,
    dragFrameRef,
  });
  const {
    sourceCollectionNeedsCandidateList,
    teamWorkflowCandidateListEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    teamWorkflowSourceQualityEnabled,
    researchStageRoundStatusEnabled,
  } = resolveTeamWorkflowResourceDemand({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionWorkspaceSelected,
    selectedSourceCollectionStageId,
  });

  // Research workspace view URL sync lives in useTeamsShellCanvasWorkspace.
  const {
    workflow: teamWorkflowQuery,
    stageRound: researchStageRoundStatusQuery,
    candidates: teamWorkflowCandidatesQuery,
    candidateGraph: teamWorkflowCandidateGraphQuery,
    coordination: teamWorkflowCoordinationStatusQuery,
    knowledgeIngestion: teamWorkflowKnowledgeIngestionStatusQuery,
    modelEvidence: teamWorkflowOfficialModelEvidenceStatusQuery,
    sourceQuality: teamWorkflowSourceQualityStatusQuery,
    paperNoteChunks: teamWorkflowPaperNoteChunkStatusQuery,
  } = useResearchWorkflowResources({
    teamId: effectiveTeamId,
    demand: {
      workflow: Boolean(effectiveTeamId && researchWorkflowTeamSelected),
      stageRound: researchStageRoundStatusEnabled,
      candidates: teamWorkflowCandidateListEnabled,
      candidateGraph: teamWorkflowGraphEnabled,
      coordination: Boolean(effectiveTeamId && researchWorkflowTeamSelected && researchWorkspaceView === "coordination"),
      knowledgeIngestion: teamWorkflowKnowledgeIngestionEnabled,
      modelEvidence: Boolean(effectiveTeamId && researchWorkflowTeamSelected && researchWorkspaceView === "overview"),
      sourceQuality: teamWorkflowSourceQualityEnabled,
      paperNoteChunks: Boolean(effectiveTeamId && researchWorkflowTeamSelected && researchWorkspaceView === "overview"),
    },
    pageVisible,
    stageWritebackSync: {
      active: sourceCollectionStageWritebackSyncActive,
      pendingTaskIds: sourceCollectionPendingStageTaskIdList,
    },
  });

  const researchSecondaryStatusQueryEnabled = resolveResearchSecondaryStatusQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
    challengeProgramProgressVisible: challengeCupResearchTeamSelected && (challengeTeamSurface === "progress" || researchWorkspaceView === "overview"),
  });
  const {
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
  } = useResearchExperimentWorkspace({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
    researchSecondaryStatusQueryEnabled,
  });
  useEffect(() => {
    setPreferredExperimentMethod("");
  }, [effectiveTeamId, setPreferredExperimentMethod]);
  const linkedChatRoomId = selectedTeam?.linkedChatRoomId ?? "";
  const linkedRoomStatusForPolling = String(selectedTeam?.linkedChatRoom?.status || "").toLowerCase();
  const linkedChatRoomQueryEnabled = resolveLinkedChatRoomQueryEnabled({
    linkedChatRoomId,
    teamDetailReady: Boolean(teamDetailQuery.data),
    researchWorkflowTeamSelected,
    researchCanvasVisible: researchCanvasReadOnly,
    researchWorkspaceView,
  });
  const linkedChatRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(linkedChatRoomId || "none"),
    queryFn: ({ signal }) => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(linkedChatRoomId)}`, { signal }),
    enabled: linkedChatRoomQueryEnabled,
    refetchInterval: (query) => {
      const detail = query.state.data as ChatRoomDetail | undefined;
      return linkedRoomRefetchInterval(pageVisible, detail?.status || linkedRoomStatusForPolling);
    },
  });
  const sourceCollectionAgentIds = useMemo(() => sourceCollectionAgentIdsFromTeam(selectedTeam, canvas), [canvas, selectedTeam]);
  const sourceCollectionOwnerAgentId = useMemo(() => sourceCollectionOwnerAgentIdFromTeam(selectedTeam, canvas), [canvas, selectedTeam]);
  const sourceCollectionFinderAgentId = sourceCollectionAgentIds.source_finder || "Source Finder Agent";
  const sourceCollectionExtractorAgentId = sourceCollectionAgentIds.source_extractor || "Source Extractor Agent";
  const sourceCollectionRelationMapperAgentId = sourceCollectionAgentIds.source_relation_mapper || "Source Relation Mapper Agent";
  const sourceCollectionIngestorAgentId = sourceCollectionAgentIds.source_ingestor || "Source Ingestor Agent";
  const researchStageAgentBindingsByStage = useMemo(
    () => buildResearchStageAgentBindingsByStage({
      canvas,
      selectedTeam,
      activeAgentsById,
      knowledgeExpansionWorkflowTeamSelected,
    }),
    [activeAgentsById, canvas, knowledgeExpansionWorkflowTeamSelected, selectedTeam]
  );
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, selectedTeam?.teamId),
    [projectBusQuery.data, selectedTeam?.teamId]
  );

  // Shell team pick / canvas frame / node-draft sync live in useTeamsShellCanvasWorkspace + useTeamsCanvasProjection.
  // SC stage URL sync + pagination reset live in useSourceCollectionWorkspace.
  // Mutation hooks: useTeamsMutationBundle (R2-g).

  const mutationBundle = useTeamsMutationBundle({
    selectedTeamId,
    setSelectedTeamId,
    setSelectedNodeId,
    setSearchParams,
    setTeamMessage,
    setTeamTaskTopic,
    chatWorkspaceCache,
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionOwnerAgentId,
    sourceCollectionAgentIds,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionIngestorAgentId,
    activeSourceCollectionResearchProjectId,
    sourceCollectionStandalone,
    sourceCollectionDraft,
    setSelectedSourceCollectionRunId,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    setSourceCollectionOutputDraft,
    setResearchWorkspaceView,
    navigate,
    latestExperimentStageRoundId: experimentPlanningStatusQuery.data?.latestExperimentRound?.stageRoundId || "",
    setExperimentSmokeResultDraft,
    setExperimentFullRunResultDraft,
    setExperimentKnowledgeIngestionDraft,
    setResearchLoopEvidenceDraft,
    setResearchLoopDecisionDraft,
    scrollSourceCollectionPanelIntoViewRef,
  });
  const {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
    resetResearchProjectSourceCollectionMutation,
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
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
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
    canvasSavePendingForTeam,
    saveCanvas,
  } = mutationBundle;

  const {
    selectResearchWorkspaceView,
    selectTeamRecord,
    selectTeamShellMode,
  } = createTeamsResearchNavigation({
    searchParams,
    setSearchParams,
    effectiveTeamId,
    teamShellMode,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    setTeamShellMode,
    setResearchWorkspaceView,
    setSelectedTeamId,
    setSelectedNodeId,
  });

  // Late-bound guards: SC composition both consumes launch handlers and produces these flags.
  let selectedTeamStartResearchStagePending = false;
  let researchStageCanLaunch = true;
  const {
    launchResearchStage,
    handleResearchPrimaryAction,
    handleResearchAdvanceAction,
  } = createResearchStageLaunchHandlers({
    lang,
    selectedTeam,
    sourceCollectionDraft,
    getSelectedTeamStartResearchStagePending: () => selectedTeamStartResearchStagePending,
    getResearchStageCanLaunch: () => researchStageCanLaunch,
    challengeCupResearchTeamSelected,
    researchStageProjectAgentTasks,
    startResearchStageRoundMutation,
    navigate,
    selectResearchWorkspaceView,
    setResearchAdvanceNotice,
  });

  const experimentWorkspacePendingFlags = buildExperimentWorkspacePendingFlags({
    teamId: effectiveTeamId,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    registerExperimentSmokeResultMutation,
    runExperimentSmokeMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
  });

  const {
    createExperimentPlanFromWorkspace,
    materializeEngineeringProxyHypothesisFromWorkspace,
    completeScientificHypothesisFromWorkspace,
    reviewExperimentHypothesisFromWorkspace,
    createExperimentHypothesisRevisionFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
  } = createExperimentWorkspaceActions({
    // Keep actions on the route-stable ID while richer Team detail refreshes.
    // Otherwise an enabled control can silently return without a mutation.
    teamId: effectiveTeamId,
    ...experimentWorkspacePendingFlags,
    researchStagePhases: researchStageRoundStatusQuery.data?.phases ?? [],
    experimentPlanningStatus: experimentPlanningStatusQuery.data ?? null,
    sourceCollectionDraftTitle: sourceCollectionDraft.title,
    sourceCollectionDraftGoal: sourceCollectionDraft.goal,
    experimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    experimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    selectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    researchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    researchLoopTemplatesPayload: researchLoopTemplatesQuery.data ?? null,
    researchLoopStatus: researchLoopStatusQuery.data ?? null,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    registerExperimentBaselineArtifactMutation,
    freezeExperimentDesignMutation,
    registerExperimentSmokeResultMutation,
    runExperimentSmokeMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
  });

  const {
    sourceCollectionStageAgentBindings,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageAgentChatState,
    sourceCollectionStageReturnRoute,
    sourceCollectionStageChatReturnLabel,
    repairSelectedWorkflowTeamAgentsIfNeeded,
    openSourceCollectionStageAgentChat,
  } = createSourceCollectionStageAgentHelpers({
    lang,
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    researchStageAgentBindingsByStage,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSummaryQuery,
    agentSummaryQuery,
    seedSourceCollectionAgentSessionContextMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    repairChallengeCupTeamAgentsMutation,
    navigate,
  });

  const {
    addNode,
    applyNodeDraft,
    unbindSelectedNode,
    deleteSelectedNode,
    connectFromLead,
    startNodeDrag,
    moveNodeDrag,
    finishNodeDrag,
  } = createTeamCanvasNodeEditing({
    lang,
    durableCanvas,
    researchCanvasReadOnly,
    selectedNode,
    selectedTeamId: selectedTeam?.teamId,
    nodeDraft,
    activeAgents,
    agentTeamMembership,
    canvasScale,
    canvasViewportStyle,
    dragStateRef,
    dragFrameRef,
    setSelectedNodeId,
    setNodePositionDrafts,
    setLockedCanvasViewportStyle,
    canvasSavePendingForTeam,
    saveCanvas,
  });

  const validation = canvas?.validation;
  const selectedTeamSaveCanvasPending = canvasSavePendingForTeam(selectedTeam?.teamId);
  const selectedTeamSaveCanvasSuccess = saveCanvasMutation.isSuccess && saveCanvasMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamSyncPending = syncTeamChatRoomMutation.isPending && syncTeamChatRoomMutation.variables === selectedTeam?.teamId;
  const selectedTeamArchivePending = archiveTeamMutation.isPending && archiveTeamMutation.variables === selectedTeam?.teamId;
  const selectedTeamArchiveDisabledReason = systemManagedTeamArchiveReason(selectedTeam, lang);
  const selectedTeamReturnRoute = selectedTeam?.teamId ? teamWorkspaceRoute(selectedTeam.teamId) : "/teams";
  const selectedTeamMemoryActorId =
    (sourceCollectionIngestorAgentId && activeAgentsById.has(sourceCollectionIngestorAgentId) ? sourceCollectionIngestorAgentId : "")
    || selectedTeam?.members.find((member) => member.agentId && activeAgentsById.has(member.agentId))?.agentId
    || activeAgents[0]?.agentId
    || "";
  const selectedTeamKnowledgeRoute = selectedTeam?.teamId
    ? teamMemoryRoute({
        teamId: selectedTeam.teamId,
        agentId: selectedTeamMemoryActorId,
        view: "knowledge",
        returnLabel: "teams",
        returnTo: selectedTeamReturnRoute,
      })
    : "/memory/knowledge";
  const selectedTeamGraphRoute = selectedTeam?.teamId
    ? teamMemoryRoute({
        teamId: selectedTeam.teamId,
        agentId: selectedTeamMemoryActorId,
        nodeId: `team:${selectedTeam.teamId}`,
        view: "graph",
        returnLabel: "teams",
        returnTo: selectedTeamReturnRoute,
      })
    : "/memory/graph";
  const selectedTeamMemoryMembers: TeamMemoryIndexMember[] = (selectedTeam?.members ?? [])
    .filter((member) => Boolean(member.agentId))
    .map((member) => {
      const agentId = String(member.agentId || "").trim();
      const agent = activeAgentsById.get(agentId);
      const display = agentDisplayInfo(agent, lang, {
        name: member.agentName || member.agentCode || agentId,
      });
      const roleLabel = member.role || agent?.roleKey || agent?.primaryMode || "-";
      const memoryIndexAgentHydrationPending = Boolean(
        !agent && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching)
      );
      const memoryIndexAgentLoadFailed = Boolean(!agent && agentSummaryQuery.isError);
      const statusTitle = agent
        ? researchStageAgentModelLabel(agent, lang)
        : memoryIndexAgentHydrationPending
          ? (lang === "zh" ? "成员 Agent 正在从目录加载。" : "Member Agent is loading from the directory.")
          : memoryIndexAgentLoadFailed
            ? (lang === "zh" ? "无法读取 Agent 目录；请稍后刷新。" : "The Agent directory could not be read. Refresh later.")
            : (lang === "zh"
              ? "该成员保留了 Agent ID，但目录中未找到对应实例。"
              : "This member retains an Agent ID that is not present in the directory.");
      const statusLabel = agent
        ? researchStageAgentConfigStatusLabel(agent, lang)
        : memoryIndexAgentHydrationPending
          ? (lang === "zh" ? "正在读取 Agent 目录" : "Loading Agent directory")
          : memoryIndexAgentLoadFailed
            ? (lang === "zh" ? "Agent 目录加载失败" : "Agent directory load failed")
            : (lang === "zh" ? "Agent 引用失效" : "Agent reference missing");
      const statusTone = agent
        ? researchStageAgentConfigTone(agent)
        : memoryIndexAgentHydrationPending
          ? "warning"
          : "blocked";
      return {
    id: `team-memory-${selectedTeam?.teamId || "team"}-${agentId}`,
    agentName: display.name || member.agentName || member.agentCode || agentId,
    agentCode: member.agentCode || agent?.agentCode || agentId,
    roleLabel,
    roleTitle: [roleLabel, member.purpose, ...(member.responsibilities ?? [])].filter(Boolean).join(" · "),
    statusLabel,
    statusTitle,
    statusTone,
    memoryRoute: agentCenterMemoryRoute({
        agentId,
        teamId: selectedTeam?.teamId,
        view: "agents",
        returnLabel: "teams",
        returnTo: selectedTeamReturnRoute,
      }),
      configRoute: researchStageAgentManagementRoute(agentId),
      };
    });
  const selectedTeamStartRoundPending = startTeamRoundMutation.isPending && startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartRoundResult =
    startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId ? startTeamRoundMutation.data : undefined;
  const selectedTeamStartRoundError =
    startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId && startTeamRoundMutation.error instanceof Error
    ? startTeamRoundMutation.error
    : null;
  const selectedTeamMessagePending = sendTeamMessageMutation.isPending && sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamMessageResult =
    sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId ? sendTeamMessageMutation.data : undefined;
  const selectedTeamMessageError =
    sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId && sendTeamMessageMutation.error instanceof Error
    ? sendTeamMessageMutation.error
    : null;
  const saveLabel = selectedTeamSaveCanvasPending ? (lang === "zh" ? "保存中" : "Saving") : selectedTeamSaveCanvasSuccess ? (lang === "zh" ? "已保存" : "Saved") : "";
  const activeTeamMemberCount = selectedTeam?.members.filter((member) => member.agentStatus === "active").length ?? 0;
  const conversationProjection = selectedTeam?.conversation ?? null;
  const linkedRoomDetail = linkedChatRoomQuery.data ?? null;
  const latestTeamRound = latestChatRoomRound(linkedRoomDetail);
  const linkedRoomStatus = String(linkedRoomDetail?.status || selectedTeam?.linkedChatRoom?.status || "").toLowerCase();
  const linkedRoomBusy = linkedRoomStatus === "running" || linkedRoomStatus === "stopping";
  const canStartTeamRound = Boolean(selectedTeam?.teamId && linkedChatRoomId && activeTeamMemberCount > 0 && teamTaskTopic.trim() && !linkedRoomBusy);
  const visibleCommunicationEdgeCount = visibleCommunicationEdges.length;
  const communicationEdgeHint = communicationEdges.length === 0
    ? (lang === "zh" ? "没有可展开的信息线" : "No information lines to expand")
    : showCommunicationEdges
    ? selectedNodeId
    ? (lang === "zh" ? `信息线已展开：选中节点 ${visibleCommunicationEdgeCount} 条` : `Information lines expanded: ${visibleCommunicationEdgeCount} for selected node`)
    : (lang === "zh" ? `信息线已展开：全部 ${visibleCommunicationEdgeCount} 条` : `Information lines expanded: ${visibleCommunicationEdgeCount} total`)
    : (lang === "zh" ? `信息线已收起（${communicationEdges.length} 条，可展开）` : `Information lines hidden (${communicationEdges.length} available)`);
  const communicationEdgeButtonLabel = communicationEdges.length === 0
    ? (lang === "zh" ? "暂无信息线" : "No info lines")
    : showCommunicationEdges
    ? (lang === "zh" ? "收起信息线" : "Hide info lines")
    : (lang === "zh" ? `展开信息线 ${communicationEdges.length}` : `Show info ${communicationEdges.length}`);
  const teamWorkflow = teamWorkflowQuery.data ?? null;
  const teamWorkflowCandidates = teamWorkflowCandidatesQuery.data?.candidates ?? [];
  const teamWorkflowValidationSummary = teamWorkflowCandidatesQuery.data?.validationSummary ?? null;
  const teamWorkflowCandidateGraphRecord = latestWorkflowCandidate(teamWorkflowCandidateGraphQuery.data?.candidates ?? []);
  const teamWorkflowCandidateGraph = workflowCandidateGraphFromCandidate(teamWorkflowCandidateGraphRecord);
  const teamWorkflowCandidateGraphLayout = teamWorkflowCandidateGraph ? workflowGraphLayout(teamWorkflowCandidateGraph) : null;
  const latestKnowledgeStewardPackCandidate = latestWorkflowCandidate(
    teamWorkflowCandidates.filter((candidate) => {
      const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
      return (
        candidate.currentWorkflowNode === "steward_ingestion"
        || String(metadata.taskType || "") === "steward_pack_draft"
      );
    }),
  );
  const teamWorkflowCoordinationStatus = teamWorkflowCoordinationStatusQuery.data ?? null;
  const teamWorkflowKnowledgeIngestionStatus = teamWorkflowKnowledgeIngestionStatusQuery.data ?? null;
  const teamWorkflowOfficialModelEvidenceStatus = teamWorkflowOfficialModelEvidenceStatusQuery.data ?? null;
  const teamWorkflowSourceQualityStatus = teamWorkflowSourceQualityStatusQuery.data ?? null;
  const teamWorkflowPaperNoteChunkStatus = teamWorkflowPaperNoteChunkStatusQuery.data ?? null;
  const researchStageRoundStatus = researchStageRoundStatusQuery.data ?? null;
  const researchStagePhases = researchStageRoundStatus?.phases ?? [];
  const researchProjectProgressQuery = useQuery({
    queryKey: [
    "teams",
    effectiveTeamId,
    "workflow-orchestration",
    "research-projects",
    activeSourceCollectionResearchProjectId || "none",
    "progress"
    ],
    queryFn: () => getTeamResearchProjectProgress(effectiveTeamId,
    activeSourceCollectionResearchProjectId
    ),
    enabled: Boolean(researchWorkflowTeamSelected
    && researchWorkspaceView === "overview"
    && effectiveTeamId
    && activeSourceCollectionResearchProjectId
    ),
    staleTime: 5_000,
    });
  const researchProjectProgress = researchProjectProgressQuery.data ?? null;
  const researchPrimaryActionInput = useMemo(() => ({
    hasActiveProject: Boolean(activeSourceCollectionResearchProjectId),
    sourceRunCount: researchProjectProgress?.sourceRunCount
    ?? sourceCollectionRuns.length,
    sourceCandidateCount: researchProjectProgress?.sourceCandidateCount
    ?? teamWorkflow?.candidateStore?.candidateCount
    ?? 0,
    phases: (researchProjectProgress?.phases as typeof researchStagePhases | undefined)
    ?? researchStagePhases,
    experimentDesignFrozen: Boolean(researchProjectProgress
    && researchProjectProgress.frozenExperimentPlanCount > 0
    ),
    // Overview infers active stage from progress; in-stage URLs pin continue target.,
    currentView: (researchWorkspaceView === "knowledge_collection"
    || researchWorkspaceView === "experiment"
    || researchWorkspaceView === "iteration"
    )
    ? researchWorkspaceView
    : null,
    }), [activeSourceCollectionResearchProjectId,
    researchProjectProgress,
    researchStagePhases,
    researchWorkspaceView,
    sourceCollectionRuns.length,
    teamWorkflow?.candidateStore?.candidateCount
    ]);
  const researchPrimaryAction = useMemo(
    () => resolveResearchPrimaryAction(researchPrimaryActionInput),
    [researchPrimaryActionInput]
  );
  const researchAdvanceAction = useMemo(
    () => resolveResearchAdvanceAction(researchPrimaryActionInput),
    [researchPrimaryActionInput]
  );
  const researchStageHandoff = useMemo(
    () => resolveResearchStageHandoff(researchPrimaryActionInput),
    [researchPrimaryActionInput]
  );
  const researchStageUnlock = useMemo(
    () => resolveResearchStageUnlock(researchPrimaryActionInput),
    [researchPrimaryActionInput]
  );
    // Runtime summary optional.
  const scLayer = useTeamsWorkbenchScLayer({
    sourceCollectionWorkspace,
    mutationBundle,
    lang,
    selectedTeam,
    effectiveTeamId,
    researchWorkflowTeamSelected,
    pageVisible,
    researchStagePhases,
    researchStageRoundStatus,
    researchStageProjectAgentTasks,
    teamWorkflowCandidates,
    teamWorkflowCandidatesQuery,
    teamWorkflowCandidateListEnabled,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    teamWorkflowCandidateGraphQuery,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowPaperNoteChunkStatus,
    teamWorkflow,
    sourceCollectionWorkspaceSelected,
    teamWorkflowSourceQualityEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    sourceCollectionNeedsCandidateList,
    experimentPlanningStatusQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    aiSearchRunsQuery,
    aiSearchRunTopic,
    queryClient,
    requestedSourceCollectionStage,
    searchParams,
    setSearchParams,
    navigate,
    scrollSourceCollectionPanelIntoViewRef,
    sourceCollectionControlPanelRef,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionOwnerAgentId,
    sourceCollectionIngestorAgentId,
    sourceCollectionStandalone,
    selectResearchWorkspaceView,
    launchResearchStage,
    styles,
    setSourceCollectionStageAdvanceFailure,
    teamWorkflowKnowledgeIngestionStatus,
    teamWorkflowCandidateGraph,
    repairSelectedWorkflowTeamAgentsIfNeeded,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionStageReturnRoute,
    sourceCollectionStageChatReturnLabel,
    sourceCollectionStageTaskClickKey,
    sourceCollectionStageAgentChatState,
    sourceCollectionStagePrimaryAgentBinding,
    openSourceCollectionStageAgentChat,
    agentSummaryQuery,
    selectedTeamReturnRoute,
    workflowQualityToneBound,
    workflowIngestionToneBound,
    sourceCollectionStageAgentBindings,
    sourceCollectionStageAdvanceFailure,
  });
  const {
    scComposition,
    experimentPlanningStatus,
    researchStageCanLaunchFromSc,
    renderSourceCollectionStandalonePage,
    selectSourceCollectionStage,
    selectedTeamAssessSourceQualityPending,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamSourceQualityPending,
    selectedTeamStartResearchStagePendingFromSc,
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
  } = scLayer;
  // Late-bind launch guards (createResearchStageLaunchHandlers getters).
  selectedTeamStartResearchStagePending = selectedTeamStartResearchStagePendingFromSc;
  researchStageCanLaunch = researchStageCanLaunchFromSc;


  return {
    queryClient,
    chatWorkspaceCache,
    navigate,
    searchParams,
    setSearchParams,
    requestedResearchViewParam,
    requestedResearchWorkspaceView,
    requestedSourceCollectionStage,
    sourceCollectionStandalone,
    pageVisible,
    requestedTeamShellMode,
    sourceCollectionControlPanelRef,
    scrollSourceCollectionPanelIntoViewRef,
    requestedTeamId,
    requestedAgentId,
    sourceCollectionWorkspace,
    researchSecondaryStatusQueryEnabled,
    linkedChatRoomId,
    linkedRoomStatusForPolling,
    linkedChatRoomQueryEnabled,
    linkedChatRoomQuery,
    detail: linkedRoomDetail,
    selectedTeamMemoryMembers,
    sourceCollectionAgentIds,
    sourceCollectionOwnerAgentId,
    sourceCollectionFinderAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionIngestorAgentId,
    researchStageAgentBindingsByStage,
    teamBusEvents,
    mutationBundle,
    experimentWorkspacePendingFlags,
    validation,
    selectedTeamSaveCanvasPending,
    selectedTeamSaveCanvasSuccess,
    selectedTeamSyncPending,
    selectedTeamArchivePending,
    selectedTeamArchiveDisabledReason,
    selectedTeamReturnRoute,
    selectedTeamMemoryActorId,
    selectedTeamKnowledgeRoute,
    selectedTeamGraphRoute,
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
    linkedRoomStatus,
    linkedRoomBusy,
    canStartTeamRound,
    visibleCommunicationEdgeCount,
    communicationEdgeHint,
    communicationEdgeButtonLabel,
    teamWorkflow,
    teamWorkflowCandidates,
    teamWorkflowValidationSummary,
    teamWorkflowCandidateGraphRecord,
    teamWorkflowCandidateGraph,
    teamWorkflowCandidateGraphLayout,
    latestKnowledgeStewardPackCandidate,
    teamWorkflowCoordinationStatus,
    teamWorkflowKnowledgeIngestionStatus,
    teamWorkflowOfficialModelEvidenceStatus,
    teamWorkflowSourceQualityStatus,
    teamWorkflowPaperNoteChunkStatus,
    researchStageRoundStatus,
    researchStagePhases,
    researchProjectProgressQuery,
    researchProjectProgress,
    researchPrimaryActionInput,
    researchPrimaryAction,
    researchAdvanceAction,
    researchStageHandoff,
    researchStageUnlock,
    lang,
    teamsQuery,
    agentSummaryQuery,
    projectBusQuery,
    activeAgents,
    activeAgentsById,
    teams,
    visibleTeams,
    visibleTeamIds,
    visibleTeamSummary,
    hasTeams,
    agentTeamMembership,
    requestedAgentTeamId,
    requestedVisibleTeamId,
    requestedVisibleAgentTeamId,
    fallbackVisibleTeamId,
    selectedTeamId,
    setSelectedTeamId,
    selectedNodeId,
    setSelectedNodeId,
    nodeDraft,
    setNodeDraft,
    teamMessage,
    setTeamMessage,
    teamInterrupt,
    setTeamInterrupt,
    teamTaskTopic,
    setTeamTaskTopic,
    showCommunicationEdges,
    setShowCommunicationEdges,
    researchCanvasLayoutMode,
    setResearchCanvasLayoutMode,
    researchWorkspaceView,
    setResearchWorkspaceView,
    teamShellMode,
    setTeamShellMode,
    challengeTeamSurface,
    setChallengeTeamSurface,
    nodePositionDrafts,
    setNodePositionDrafts,
    canvasFrameSize,
    setCanvasFrameSize,
    lockedCanvasViewportStyle,
    setLockedCanvasViewportStyle,
    canvasFrameRef,
    dragStateRef,
    dragFrameRef,
    selectedVisibleTeamId,
    effectiveTeamId,
    teamDetailLoadMode,
    selectedTeamReference,
    teamDetailQuery,
    selectedTeam,
    selectedTeamDetailLoading,
    knowledgeExpansionWorkflowTeamSelected,
    researchWorkflowTeamSelected,
    challengeCupResearchTeamSelected,
    researchStageProjectAgentTasks,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
    sourceCollectionDraft,
    setSourceCollectionDraft,
    selectedSourceCollectionRunId,
    setSelectedSourceCollectionRunId,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    selectedSourceCollectionStageId,
    setSelectedSourceCollectionStageId,
    sourceCollectionStageSyncUntilMs,
    setSourceCollectionStageSyncUntilMs,
    sourceCollectionPendingStageTaskIds,
    setSourceCollectionPendingStageTaskIds,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionFocusedPanelId,
    setSourceCollectionFocusedPanelId,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    sourceCollectionDraftHydratedRunIdRef,
    sourceCollectionDraftHydratedSearchPlanRef,
    sourceCollectionFreshProjectDraftIdRef,
    sourceCollectionResearchProjectsQuery,
    activeSourceCollectionResearchProjectId,
    activeSourceCollectionResearchProject,
    sourceCollectionRunsQuery,
    sourceCollectionRuns,
    sourceCollectionLatestRun,
    sourceCollectionHistoricalRunWithRecords,
    selectedSourceCollectionRun,
    sourceCollectionLatestRunIsEmpty,
    sourceCollectionShowingHistoricalRunByDefault,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSelectedRunTopic,
    sourceCollectionSelectedRunGoal,
    sourceCollectionSelectedRunQueryCount,
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionPendingStageTaskIdList,
    sourceCollectionStageWritebackAwaitingTask,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
    aiSearchRunsQuery,
    researchCanvasReadOnly,
    teamCanvasQueryEnabled,
    teamCanvasQuery,
    durableCanvas,
    canvas,
    hasWritableCanvas,
    canvasNodes,
    organizationEdges,
    communicationEdges,
    autoLayoutCanvasNodes,
    researchCanvasAutoLayoutActive,
    displayCanvasNodes,
    selectedNode,
    visibleCommunicationEdges,
    visibleEdges,
    autoCanvasViewportStyle,
    canvasViewportStyle,
    canvasScale,
    sourceCollectionNeedsCandidateList,
    teamWorkflowCandidateListEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    teamWorkflowSourceQualityEnabled,
    researchStageRoundStatusEnabled,
    teamWorkflowQuery,
    researchStageRoundStatusQuery,
    teamWorkflowCandidatesQuery,
    teamWorkflowCandidateGraphQuery,
    teamWorkflowCoordinationStatusQuery,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowOfficialModelEvidenceStatusQuery,
    teamWorkflowSourceQualityStatusQuery,
    teamWorkflowPaperNoteChunkStatusQuery,
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
    resetResearchProjectSourceCollectionMutation,
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
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
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
    canvasSavePendingForTeam,
    saveCanvas,
    selectResearchWorkspaceView,
    selectTeamRecord,
    selectTeamShellMode,
    launchResearchStage,
    handleResearchPrimaryAction,
    handleResearchAdvanceAction,
    createExperimentPlanFromWorkspace,
    materializeEngineeringProxyHypothesisFromWorkspace,
    completeScientificHypothesisFromWorkspace,
    reviewExperimentHypothesisFromWorkspace,
    createExperimentHypothesisRevisionFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
    sourceCollectionStageAgentBindings,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageAgentChatState,
    sourceCollectionStageReturnRoute,
    sourceCollectionStageChatReturnLabel,
    repairSelectedWorkflowTeamAgentsIfNeeded,
    openSourceCollectionStageAgentChat,
    addNode,
    applyNodeDraft,
    unbindSelectedNode,
    deleteSelectedNode,
    connectFromLead,
    startNodeDrag,
    moveNodeDrag,
    finishNodeDrag,
    styles,
    nodeTone,
    roleBadgeTone,
    workflowIngestionToneBound,
    workflowQualityToneBound,
    TEAMS_BOARD_INSPECTOR_PANE,
    TEAMS_LAYOUT_ID,
    TEAMS_RAIL_PANE,
    // SC composition layer: standalone page renderer, display state, stage modules, etc.
    // Must be on the bag — shell phase reads these flat (not only via scComposition).
    ...scLayer,
    researchStageStartFeedbackText,
    // Late-bound launch guards win over scLayer aliases.
    selectedTeamStartResearchStagePending: selectedTeamStartResearchStagePendingFromSc,
    researchStageCanLaunch: researchStageCanLaunchFromSc,
  };
}
