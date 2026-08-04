import "../design/route-css/teams.tailwind.css";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, ArrowLeft, Bot, CheckCircle2, Eye, Link2, MessageSquare, Plus, RefreshCw, Save, Search, Settings2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { type PaneSpec } from "../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import {
  ResearchMemoryEvidencePanel,
  TeamAiSearchWorkspacePanel,
  TeamExperimentPlanningLedgerPanel,
  TeamKnowledgeCollectionCompletionFlowPanel,
  TeamMemoryIndexPanel,
  TeamResearchLoopPanel,
  TeamResearchStageAgentPanel,
  TeamResearchStageAgentSummary,
  TeamResearchStageLauncherPanel,
  TeamResearchStageStandalonePagePanel,
  TeamSourceCollectionActiveStagePanel,
  TeamSourceCollectionActiveStageWorkspacePanel,
  TeamSourceCollectionControlsPanel,
  TeamSourceCollectionControlsWorkspacePanel,
  TeamSourceCollectionConversationPanel,
  TeamSourceCollectionFindingDetailsPanel,
  TeamSourceCollectionGraphPanel,
  TeamSourceCollectionManualWritebackPanel,
  TeamSourceCollectionMemoryPanel,
  TeamSourceCollectionPhaseCloseGatePanel,
  TeamSourceCollectionRunSettingsPanel,
  TeamSourceCollectionScreeningPanel,
  TeamSourceCollectionSearchBriefPanel,
  TeamSourceCollectionSourceDetailPanel,
  TeamSourceCollectionStandaloneStagePanel,
  TeamWorkflowGraphView,
  TeamWorkflowModelEvidenceStatusPanel,
  teamsPanelPackLoaders,
} from "./teams/teamLazyPanels";
import { createExperimentWorkspaceActions } from "./teams/experimentWorkspaceActions";
import {
  prefetchTeamsPanelPacks,
  resolveTeamsPanelPrefetchPacks,
} from "./teams/teamPanelPrefetch";
import { useTeamExperimentLoopMutations } from "./teams/useTeamExperimentLoopMutations";
import { useTeamSourceCollectionMutations } from "./teams/useTeamSourceCollectionMutations";
import { useTeamShellMutations } from "./teams/useTeamShellMutations";
import { useTeamWorkflowStartMutations } from "./teams/useTeamWorkflowStartMutations";
import { useSourceCollectionWorkspace } from "./teams/useSourceCollectionWorkspace";
import { useResearchExperimentWorkspace } from "./teams/useResearchExperimentWorkspace";
import {
  useTeamsCanvasProjection,
  useTeamsShellCanvasWorkspace,
  type NodeDragState,
} from "./teams/useTeamsShellCanvasWorkspace";
import {
  type DataProcessingRecordListPayload,
  type SourceCollectionSummaryPayload,
} from "./teams/sourceCollectionRunQueryModel";
import {
  workflowIngestionTone,
  workflowQualityTone,
  type WorkflowToneStyles,
} from "./teams/workflowTone";
import type { ResearchStageRoundStartPayload } from "./teams/workflowStartMutationModel";
import type {
  SourceCollectionOutputDraft,
  TeamWorkflowKnowledgeIngestionPrecheckPayload,
  TeamWorkflowPaperNoteChunkPlanPayload,
  TeamWorkflowSourceCollectionSearchExecutionPayload,
  TeamWorkflowSourceCollectionStorageOpenPayload,
  TeamWorkflowSourceQualityAssessmentPayload,
  TeamWorkflowSourceQualityBatchAssessmentPayload,
  SourceCollectionSearchExecutionEvent,
} from "./teams/sourceCollectionMutationModel";
import {
  AI_SEARCH_RUN_PREVIEW_LIMIT,
} from "./teams/aiSearchPresentation";
import {
  EXPERIMENT_FULL_RUN_RESULT_STATUSES,
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  RESEARCH_LOOP_DECISION_VALUES,
  RESEARCH_LOOP_EVIDENCE_STATUSES,
  experimentMethodCatalogQueryKey,
  experimentPlanningStatusQueryKey,
  researchDiagnosticStatusLabel,
  researchIterationLifecycleStatusLabel,
  researchLoopStatusQueryKey,
  researchLoopTemplatesQueryKey,
  type ExperimentBaselineArtifactDraft,
  type ExperimentBaselineArtifactRecord,
  type ExperimentBaselineArtifactRegisterPayload,
  type ExperimentDesignFreezePayload,
  type EngineeringProxyHypothesisDraft,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultRecord,
  type ExperimentFullRunResultRegisterPayload,
  type ExperimentFullRunResultStatus,
  type ExperimentHypothesisCandidateSummary,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentKnowledgeIngestionRecord,
  type ExperimentPlanChecklistItem,
  type ExperimentPlanCreatePayload,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
  type ExperimentResultKnowledgeIngestionPayload,
  type ExperimentResultPackRecord,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultRecord,
  type ExperimentSmokeResultRegisterPayload,
  type ExperimentSmokeResultStatus,
  type ResearchLoopBoundary,
  type ResearchLoopCreateDraft,
  type ResearchLoopCreatePayload,
  type ResearchLoopDecisionDraft,
  type ResearchLoopDecisionPayload,
  type ResearchLoopDecisionRecord,
  type ResearchLoopDecisionValue,
  type ResearchLoopEvidenceDraft,
  type ResearchLoopEvidencePayload,
  type ResearchLoopEvidenceRecord,
  type ResearchLoopEvidenceStatus,
  type ResearchLoopIterationProposal,
  type ResearchLoopRecord,
  type ResearchLoopStatusPayload,
  type ResearchLoopSummary,
  type ResearchLoopTemplate,
  type ResearchLoopTemplatesPayload,
} from "./teams/experimentLoopModel";
import {
  SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS,
  SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL,
  SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
  SOURCE_COLLECTION_RESULT_PAGE_SIZE,
  SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
  SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES,
  SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS,
  candidateSourceQualityAssessmentSummary,
  compactSourceCollectionQuerySeeds,
  formatTime,
  hasSourceCollectionPromptCachePolicy,
  sourceCollectionAgentRoleLabel,
  sourceCollectionCandidateQualityState,
  sourceCollectionCollectionModeLabel,
  sourceCollectionEvidenceLedgerDetailItems,
  sourceCollectionLanguageLabel,
  sourceCollectionLocalScanScopeForDraft,
  sourceCollectionMaterialGapCount,
  sourceCollectionModeForTeam,
  sourceCollectionPromptCacheModelDisplay,
  sourceCollectionPromptCacheStatusLabel,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusLabel,
  sourceCollectionSimpleRecordStatusLabel,
  sourceCollectionStatusLabel,
  sourceCollectionStorageArtifactsForRun,
  sourceCollectionStorageTargetForRef,
  sourceCollectionFreshProjectDraft,
  splitDraftList,
  workflowIngestionStatusLabel,
  type SourceCollectionDraft,
  type SourceCollectionMode,
  type SourceCollectionStorageArtifacts,
  type SourceCollectionStorageOpenTarget,
} from "./teams/source-collection/presentationModel";
import { TeamSourceCollectionModeFields } from "./teams/TeamSourceCollectionModeFields";
import { TeamSourceCollectionManualWritebackInject } from "./teams/TeamSourceCollectionManualWritebackInject";
import { TeamSourceCollectionControlsInject } from "./teams/TeamSourceCollectionControlsInject";
import { TeamSourceCollectionActiveStageInject } from "./teams/TeamSourceCollectionActiveStageInject";
import { TeamSourceCollectionStorageActionsInject } from "./teams/TeamSourceCollectionStorageActionsInject";
import { TeamSourceCollectionSearchBriefShell } from "./teams/TeamSourceCollectionSearchBriefShell";
import { TeamSourceCollectionRunSwitcherInject } from "./teams/TeamSourceCollectionRunSwitcherInject";
import { TeamSourceCollectionScreeningInject } from "./teams/TeamSourceCollectionScreeningInject";
import { TeamSourceCollectionGraphInject } from "./teams/TeamSourceCollectionGraphInject";
import { TeamSourceCollectionMemoryInject } from "./teams/TeamSourceCollectionMemoryInject";
import { TeamSourceCollectionSelectedSourceInject } from "./teams/TeamSourceCollectionSelectedSourceInject";
import { TeamSourceCollectionConversationInject } from "./teams/TeamSourceCollectionConversationInject";
import { TeamSourceCollectionFilterBarInject } from "./teams/TeamSourceCollectionFilterBarInject";
import { TeamSourceCollectionPaginationInject } from "./teams/TeamSourceCollectionPaginationInject";
import { TeamSourceCollectionStageAgentsInject } from "./teams/TeamSourceCollectionStageAgentsInject";
import { createTeamsWorkspacePanelRenderers } from "./teams/teamsWorkspacePanelRenderers";
import {
  buildSourceCollectionControlsFeedbackBag,
  buildSourceCollectionControlsMetricsBag,
} from "./teams/source-collection/controlsFeedbackBag";

import {
  edgeLine,
  nextNodeId,
  teamCanvasNodeStyle,
} from "./teams/canvasGeometry";
import {
  RESEARCH_WORKSPACE_NAV_ITEMS,
  parseResearchWorkspaceView,
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceAnchorId,
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  teamWorkspaceRoute,
  type ResearchStageWorkspaceView,
  type ResearchWorkspaceView,
} from "./teams/researchWorkspaceModel";
import {
  resolveResearchPrimaryAction,
  resolveResearchStageHandoff,
  type ResearchPrimaryAction,
} from "./teams/researchPrimaryActionModel";
import { ResearchBoardKanban } from "./teams/ResearchBoardKanban";
import { ResearchOverviewSurface } from "./teams/ResearchOverviewSurface";
import { ResearchWorkflowErrorSurface } from "./teams/ResearchWorkflowErrorSurface";
import { buildResearchBoardColumns } from "./teams/researchBoardModel";
import { TeamCanvasReadOnlyInspector } from "./teams/TeamCanvasReadOnlyInspector";
import { TeamNodeBindingPanel } from "./teams/TeamNodeBindingPanel";
import { TeamOrganizationCanvasSurface } from "./teams/TeamOrganizationCanvasSurface";
import { TeamShellRail } from "./teams/TeamShellRail";
import { TeamShellToolbar } from "./teams/TeamShellToolbar";
import { TeamCommunicationPanel } from "./teams/TeamCommunicationPanel";
import { TeamResearchWorkflowPanelHost } from "./teams/TeamResearchWorkflowPanelHost";
import { TeamResearchBoardPrimarySurface } from "./teams/TeamResearchBoardPrimarySurface";
import { TeamResearchWorkflowStageModules } from "./teams/TeamResearchWorkflowStageModules";
import {
  parseTeamShellMode,
  type TeamShellMode,
} from "./teams/teamShellModel";
import { ResearchProjectSwitcher, researchProjectQueryKey } from "./teams/research-projects/ResearchProjectSwitcher";
import { useResearchProjectAgentTasks } from "./teams/research-projects/useResearchProjectAgentTasks";
import { getTeamResearchProjectProgress } from "../api/researchProjectAgentTasks";
import {
  SOURCE_COLLECTION_DEFAULT_ROLES,
  SOURCE_COLLECTION_TEAM_AGENT_ROLES,
  isAiSearchScopeTeam,
  isChallengeCupResearchWorkflowTeam,
  isEvolutionSystemTeam,
  isKnowledgeExpansionWorkflowTeam,
  isResearchWorkflowTeam,
  systemManagedTeamArchiveReason,
} from "./teams/teamKindModel";
import { fetchJson } from "../api/client";
import { getRuntimeSummary } from "../api/launcher";
import {
  PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT,
  listProjectAgentBusTimeline,
  projectAgentBusEventsForTeam,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
import {
  AgentConfigWorkspaceAgent,
  AiSearchRun,
  AiSearchRunListPayload,
  AiSearchRunSummary,
  ChatRoomDetail,
  DataProcessingCollectionAssignmentListPayload,
  DataProcessingCollectionOutputPayload,
  DataProcessingRecord,
  DataProcessingRunListPayload,
  DataProcessingStatus,
  ExperimentContractV2,
  ExperimentContractValidation,
  ExperimentMethodCatalogPayload,
  RuntimeSummary,
  Team,
  TeamCanvasNode,
  TeamListPayload,
  TeamOrganizationCanvas,
  TeamResearchProject,
  TeamResearchProjectListPayload,
  TeamWorkflowCandidate,
  TeamWorkflowCandidateGraphBuildPayload,
  TeamWorkflowCandidateGraphPayload,
  TeamWorkflowKnowledgeCollectionIngestionPayload,
  TeamWorkflowKnowledgeIngestionWorkRun,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowSourceCollectionPromptCachePolicy,
  TeamWorkflowSourceCollectionPromptCachePolicyRef,
  TeamWorkflowSourceCollectionAgentSessionContextPayload,
  TeamWorkflowSourceCollectionExtractionPayload,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowSourceCollectionStageSessionTaskPayload,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
  TeamWorkflowOrchestration,
  WorkRunSnapshot,
} from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import {
  VActionGroup,
  VButton,
  VIconButton,
  VLoadingValue,
  VNativeButton,
  VNativeInput,
  VNativeSelect,
  VNativeTextarea,
  VBoardWorkbenchPage,
  VCanvasWorkbenchPage,
  VDenseOpsPage,
  VSelect,
  VStateSurface,
  VStatusStrip,
  VSurface,
  VTooltip,
} from "../components/vui";
import {
  TeamCandidateCard,
  TeamSourceEmptyState,
  TeamSourceResultItem,
  TeamSourceResultList,
  type TeamSourceEmptyStateFact,
  type TeamSourceResultTone,
} from "../components/vui/product/team-management";
import { agentCenterMemoryRoute, teamMemoryRoute } from "./agentCenterRoutes";
import { agentDisplayInfo } from "./agentDisplay";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import type { TeamMemoryIndexMember } from "./TeamMemoryIndexPanel";
import type {
  TeamSourceCollectionOverviewPlan,
  TeamSourceCollectionOverviewResult,
  TeamSourceCollectionOverviewStat,
} from "./TeamSourceCollectionOverviewPanel";
import type {
  TeamSourceCollectionSourceDetailAction,
  TeamSourceCollectionSourceDetailEvidence,
  TeamSourceCollectionSourceDetailFact,
  TeamSourceCollectionSourceDetailLink,
} from "./TeamSourceCollectionSourceDetailPanel";
import type { TeamSourceCollectionStandaloneStageModule } from "./TeamSourceCollectionStandaloneStagePanel";
import type { TeamWorkflowCandidatePreviewItem } from "./TeamWorkflowCandidatePreviewPanel";
import type { ResearchMemoryContextSummary } from "./teams/ResearchMemoryEvidencePanel";
import {
  deriveSourceCollectionExcludedRecoveryState,
  evidenceLedgerText,
  sourceCollectionCandidateEmptyStateText,
  sourceCollectionCandidateOpenLabel,
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerActionLabel,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionFilterCounts,
  sourceCollectionFilterMatches,
  sourceCollectionRecordProvenance,
  sourceCollectionRecordSourceCategory,
  sourceCollectionSourceTypeLabel,
  type SourceCollectionCandidateProvenance,
  type SourceCollectionEvidenceLedgerSummary,
  type SourceCollectionSourceFilter,
} from "./teams/source-collection/evidenceModel";
import {
  deriveSourceCollectionDisplayState,
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionRunLabel,
  sourceCollectionRunTitleLabel,
  sourceCollectionStableCountText,
  translateResearchPhrase,
  type SourceCollectionStepState,
} from "./teams/source-collection/runModel";
import {
  sourceCollectionBoundCountToCurrentCoverage,
  sourceCollectionCompletionFlowNodeState,
  sourceCollectionNonNegativeCount,
  sourceCollectionPhaseCloseGateForRun,
  selectSourceCollectionStageRound,
  sourceCollectionStageBackendActionReadiness,
  sourceCollectionStageProjectionCount,
  sourceCollectionStageProjectionState,
  sourceCollectionStageRecoveryStatusLabel,
  sourceCollectionStageUserStatusLabel,
  sourceCollectionStageUserSummary,
  type ResearchStagePhaseStatus,
  type ResearchStageRound,
  type ResearchStageRoundStatusPayload,
  type ResearchStageType,
  type SourceCollectionActionReadiness,
  type SourceCollectionPhaseCloseGate,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./teams/source-collection/stageProjection";
import {
  TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT,
  officialModelEvidenceStatusQueryKey,
  paperNoteChunkStatusQueryKey,
  researchStageRoundStatusQueryKey,
  sourceCollectionStageWritebackRefetchInterval,
  sourceQualityStatusQueryKey,
  useResearchWorkflowResources,
  type TeamWorkflowSourceQualityStatus,
} from "./teams/useResearchWorkflowResources";
import {
  KNOWLEDGE_EXPANSION_STAGE_AGENT_ROLES,
  RESEARCH_STAGE_AGENT_ROLES,
  type ResearchStageAgentRoleDefinition,
} from "./teams/researchStageRoles";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionStageTaskClickKey,
  sourceCollectionSummaryQueryKey,
  sourceCollectionSummaryQueryPrefix,
} from "./teams/teamWorkflowQueryKeys";
import {
  isForeignTeamDetailQueryKey,
  resolveLinkedChatRoomQueryEnabled,
  resolveResearchSecondaryStatusQueryEnabled,
  resolveTeamDetailLoadMode,
} from "./teams/teamDetailLoadPolicy";
import {
  normalizeAgentRoleKey,
  researchStageAgentActionableHealthIssues,
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentDirectChatRoute,
  researchStageAgentManagementRoute,
  researchStageAgentModelLabel,
  researchStageSessionChatRoute,
  sourceCollectionAgentIdsFromCanvas,
  sourceCollectionAgentIdsFromTeam,
  sourceCollectionOwnerAgentIdFromCanvas,
  sourceCollectionOwnerAgentIdFromTeam,
  teamCanvasNodeAgentSourceRoute,
  teamChatRoomRoute,
  writableTeamCanvas,
  writableTeamCanvasNode,
} from "./teams/researchStageAgentPresentation";
import {
  LINKED_ROOM_ACTIVE_REFETCH_MS,
  LINKED_ROOM_IDLE_REFETCH_MS,
  TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS,
  TEAM_BOOTSTRAP_BACKGROUND_REFETCH_MS,
  TEAM_BOOTSTRAP_REFETCH_STATUSES,
  chatRoomStatusLabel,
  isRecord,
  linkedRoomRefetchInterval,
  sourceCollectionRunListRefetchInterval,
  sourceCollectionRunRefetchInterval,
  teamConversationStatusLabel,
  workRunNumber,
  workRunString,
  workflowStateLabel,
} from "./teams/workflowPresentation";
import {
  candidatePaperNoteChunkPlanSummary,
  canvasNodeStatusLabel,
  isWorkflowCandidateGraphPayload,
  latestChatRoomRound,
  latestWorkflowCandidate,
  parseSourceCollectionStageModuleId,
  researchStageStartFeedbackText,
  SOURCE_COLLECTION_STAGE_CHAT_LABELS,
  sourceCandidateHasCompletedExtraction,
  teamNodeFunctionLabel,
  workflowCandidateGraphFromCandidate,
} from "./teams/teamRouteShellModel";
import {
  nodeToneClass,
  roleBadgeToneClass,
} from "./teams/teamCanvasNodePresentation";
import {
  SOURCE_COLLECTION_STAGE_AGENT_KEYS,
  resolveSourceCollectionStageAgentChatState,
  selectSourceCollectionStagePrimaryBinding,
  sourceCollectionPageSlice,
  sourceCollectionStageAgentBindingsForStage,
  sourceCollectionStageChatReturnLabel as sourceCollectionStageChatReturnLabelPure,
  sourceCollectionStageDisplayState as sourceCollectionStageDisplayStatePure,
  sourceCollectionStageDisplayStatus as sourceCollectionStageDisplayStatusPure,
  sourceCollectionStageDisplaySummary as sourceCollectionStageDisplaySummaryPure,
  sourceCollectionStageLaunchActive as sourceCollectionStageLaunchActivePure,
  sourceCollectionStageLaunchSummary as sourceCollectionStageLaunchSummaryPure,
  sourceCollectionStageReturnRoute as sourceCollectionStageReturnRoutePure,
  type SourceCollectionStageAgentChatStatus,
} from "./teams/teamSourceCollectionShellModel";

import { workflowGraphLayout } from "./TeamWorkflowGraphLayout";
import {
  AI_SEARCH_TEAM_ID,
  KNOWLEDGE_EXPANSION_TEAM_ID,
  RESEARCH_TEAM_ID,
  TEAM_PICKER_TEAM_IDS,
  TEAM_ORGANIZATION_CANVAS_KIND,
  canvasFromTeam,
  resolveKnownRouteTeamId,
  resolveTeamsRouteEffectiveTeamId,
} from "./TeamsRoute.canvasData";
import {
  ChallengeCupOperationsWorkspace,
  type ChallengeCupWorkspaceAgent,
} from "./teams/challenge-cup/ChallengeCupOperationsWorkspace";
import shellStyles from "./TeamsRoute.styles";
import researchRouteStyles from "./TeamsRoute.research.styles";
import aiSearchRouteStyles from "./TeamsRoute.aiSearch.styles";
import experimentRouteStyles from "./TeamsRoute.experiment.styles";
import workflowRouteStyles from "./TeamsRoute.workflow.styles";

/** Wave 8F: thematic style clusters merged for call-site stability. */
const styles = {
  ...shellStyles,
  ...researchRouteStyles,
  ...aiSearchRouteStyles,
  ...experimentRouteStyles,
  ...workflowRouteStyles,
} as Record<string, string>;

const TEAMS_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.teams;
/** Left team list — VUI split sidebar with persisted width. */
const TEAMS_RAIL_PANE: PaneSpec = {
  id: "rail",
  defaultWidth: 248,
  minWidth: 200,
  maxWidth: 360,
};
type TeamsRouteProps = {
  forcedTeamId?: string;
  forcedResearchWorkspaceView?: ResearchWorkspaceView;
  sourceCollectionStandalone?: boolean;
};

type SourceCollectionStageModule = {
  id: SourceCollectionStageModuleId;
  label: string;
  metric: string;
  summary: string;
  inputLabel: string;
  outputLabel: string;
  nextLabel: string;
  state: SourceCollectionStepState;
  status: string;
  detailLabel: string;
  actionLabel: string;
  actionDisabled: boolean;
  actionTone: "primary" | "secondary";
  actionIcon: "play" | "search" | "check" | "archive" | "refresh";
  projection?: SourceCollectionStageCardProjection | null;
  onAction: () => void;
  onDetail: () => void;
};

type SourceCollectionCompletionFlowNode = NonNullable<TeamWorkflowKnowledgeIngestionWorkRun["flowVisualization"]>["nodes"][number];





const CANVAS_NODE_ROLE_BADGE_STYLES = {
  stale: styles.nodeRoleBadgeStale,
  open: styles.nodeRoleBadgeOpen,
  lead: styles.nodeRoleBadgeLead,
  advisor: styles.nodeRoleBadgeAdvisor,
  steward: styles.nodeRoleBadgeSteward,
  research: styles.nodeRoleBadgeResearch,
  self: styles.nodeRoleBadgeSelf,
  general: styles.nodeRoleBadgeGeneral,
};

const CANVAS_NODE_TONE_STYLES = {
  stale: styles.nodeStale,
  bound: styles.nodeBound,
  open: styles.nodeOpen,
};

function roleBadgeTone(node: TeamCanvasNode, displayTone = "") {
  return roleBadgeToneClass(node, CANVAS_NODE_ROLE_BADGE_STYLES, displayTone);
}

function nodeTone(node: TeamCanvasNode) {
  return nodeToneClass(node, CANVAS_NODE_TONE_STYLES);
}

function workflowQualityToneBound(value: string) {
  return workflowQualityTone(value, styles as WorkflowToneStyles);
}

function workflowIngestionToneBound(value: string) {
  return workflowIngestionTone(value, styles as WorkflowToneStyles);
}

export { linkedRoomRefetchInterval } from "./teams/workflowPresentation";

export function TeamsRoute({
  forcedTeamId = "",
  forcedResearchWorkspaceView,
  sourceCollectionStandalone: sourceCollectionStandaloneProp = false,
}: TeamsRouteProps = {}) {
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
  const stageStandaloneView: ResearchStageWorkspaceView | null =
    requestedResearchWorkspaceView === "experiment" || requestedResearchWorkspaceView === "iteration" ? requestedResearchWorkspaceView : null;
  const pageVisible = usePageVisibility();
  const requestedTeamShellMode = parseTeamShellMode(searchParams.get("teamMode"));
  const [aiSearchRunTopic, setAiSearchRunTopic] = useState("AI 最新动态");
  // Shell/canvas state: useTeamsShellCanvasWorkspace (Phase 3).
  // Experiment/research-loop drafts: useResearchExperimentWorkspace (Phase 2).
  const sourceCollectionControlPanelRef = useRef<HTMLElement | null>(null);
  // Late-bound: mutations hook is declared above scroll helper; keep stable identity via ref.
  const scrollSourceCollectionPanelIntoViewRef = useRef<(panelId: string) => void>(() => {});

  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: ({ signal }) => fetchJson<TeamListPayload>("/api/teams", { signal }),
    refetchInterval: (query) =>
      TEAM_BOOTSTRAP_REFETCH_STATUSES.has(query.state.data?.systemTeamBootstrap?.status ?? "")
        ? resolvePollingInterval(pageVisible, TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS, { backgroundMs: TEAM_BOOTSTRAP_BACKGROUND_REFETCH_MS })
        : false,
  });
  const agentSummaryQuery = useQuery({
    queryKey: queryKeys.agentSummary(false),
    queryFn: ({ signal }) => fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?detail=summary", { signal }),
    staleTime: 10_000,
  });
  const projectBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal }),
  });
  const activeAgents = useMemo(
    () => (agentSummaryQuery.data ?? []).filter((agent) => agent.status !== "archived"),
    [agentSummaryQuery.data],
  );
  const activeAgentsById = useMemo(() => new Map(activeAgents.map((agent) => [agent.agentId, agent])), [activeAgents]);
  const teams = teamsQuery.data?.teams ?? [];
  const visibleTeams = useMemo(() => {
    const teamsById = new Map(teams.filter((team) => !isEvolutionSystemTeam(team)).map((team) => [team.teamId, team]));
    return TEAM_PICKER_TEAM_IDS.map((teamId) => teamsById.get(teamId)).filter((team): team is Team => Boolean(team));
  }, [teams]);
  const visibleTeamIds = useMemo(() => new Set(visibleTeams.map((team) => team.teamId)), [visibleTeams]);
  const visibleTeamSummary = useMemo(() => {
    return visibleTeams.reduce(
      (summary, team) => {
        if (team.status !== "archived") {
          summary.activeTeamCount += 1;
        }
        summary.memberCount += team.memberCount ?? team.members.length;
        summary.staleMemberCount += team.members.filter((member) => member.agentStatus === "stale").length;
        return summary;
      },
      { activeTeamCount: 0, memberCount: 0, staleMemberCount: 0 },
    );
  }, [visibleTeams]);
  const hasTeams = visibleTeams.length > 0;
  const agentTeamMembership = useMemo(() => {
    const membership = new Map<string, { teamId: string; teamName: string }>();
    teams.forEach((team) => {
      if (team.status === "archived") {
        return;
      }
      (team.members ?? []).forEach((member) => {
        if (member.agentId) {
          membership.set(member.agentId, { teamId: team.teamId, teamName: team.name });
        }
      });
    });
    return membership;
  }, [teams]);
  const requestedTeamId = searchParams.get("team") ?? "";
  const requestedAgentId = searchParams.get("agent") ?? "";
  const requestedAgentTeamId = requestedAgentId ? agentTeamMembership.get(requestedAgentId)?.teamId ?? "" : "";
  const requestedVisibleTeamId = resolveKnownRouteTeamId(requestedTeamId, visibleTeamIds);
  const requestedVisibleAgentTeamId = requestedAgentTeamId && visibleTeamIds.has(requestedAgentTeamId) ? requestedAgentTeamId : "";
  // Preview-aligned default: land on challenge-cup research board, not AI-search ops.
  const fallbackVisibleTeamId =
    (visibleTeamIds.has(RESEARCH_TEAM_ID) ? RESEARCH_TEAM_ID : "")
    || visibleTeams[0]?.teamId
    || "";
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
  const selectedVisibleTeamId = selectedTeamId && visibleTeamIds.has(selectedTeamId) ? selectedTeamId : "";
  const effectiveTeamId = resolveTeamsRouteEffectiveTeamId({
    forcedTeamId,
    selectedTeamId: selectedVisibleTeamId,
    requestedTeamId,
    requestedAgentTeamId,
    visibleTeamIds,
    fallbackTeamId: fallbackVisibleTeamId,
  });
  const teamDetailLoadMode = resolveTeamDetailLoadMode({
    sourceCollectionStandalone,
    researchWorkspaceView,
  });
  useEffect(() => {
    const activeId = String(effectiveTeamId || "").trim();
    if (!activeId) {
      return;
    }
    void queryClient.cancelQueries({
      predicate: (query) => isForeignTeamDetailQueryKey(query.queryKey, activeId),
    });
  }, [effectiveTeamId, queryClient]);
  const selectedTeamReference = visibleTeams.find((team) => team.teamId === effectiveTeamId) ?? null;
  const teamDetailQuery = useQuery<Team>({
    queryKey: queryKeys.team(effectiveTeamId, teamDetailLoadMode),
    queryFn: ({ signal }) => fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}?detail=${teamDetailLoadMode}`, { signal }),
    enabled: Boolean(effectiveTeamId),
    staleTime: 10_000,
    placeholderData: () =>
      (selectedTeamReference && selectedTeamReference.teamId === effectiveTeamId ? selectedTeamReference : undefined),
  });
  const selectedTeam = teamDetailQuery.data ?? selectedTeamReference ?? null;
  const selectedTeamDetailLoading = Boolean(
    effectiveTeamId && selectedTeamReference && !teamDetailQuery.data && teamDetailQuery.isPending
  );
  const knowledgeExpansionWorkflowTeamSelected = isKnowledgeExpansionWorkflowTeam(selectedTeam);
  const researchWorkflowTeamSelected = isResearchWorkflowTeam(selectedTeam);
  const challengeCupResearchTeamSelected = isChallengeCupResearchWorkflowTeam(selectedTeam);
  const researchStageProjectAgentTasks = useResearchProjectAgentTasks({
    teamId: selectedTeam?.teamId || RESEARCH_TEAM_ID,
    enabled:
      challengeCupResearchTeamSelected
      && !sourceCollectionStandalone
      && researchWorkspaceView !== "source_collection"
      && researchWorkspaceView !== "knowledge_collection",
  });
  const aiSearchScopeTeamSelected = isAiSearchScopeTeam(selectedTeam);
  const sourceCollectionWorkspaceSelected =
    researchWorkflowTeamSelected && (sourceCollectionStandalone || researchWorkspaceView === "source_collection" || researchWorkspaceView === "knowledge_collection");

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
  } = useSourceCollectionWorkspace({
    effectiveTeamId,
    pageVisible,
    researchWorkflowTeamSelected,
    sourceCollectionWorkspaceSelected,
    initialStageId: requestedSourceCollectionStage ?? null,
  });
  // Path-scoped pack warm-up after team/view switch (not shell mount-all).
  useEffect(() => {
    const packs = resolveTeamsPanelPrefetchPacks({
      researchWorkflowTeamSelected,
      aiSearchScopeTeamSelected,
      sourceCollectionWorkspaceSelected,
      researchWorkspaceView,
    });
    if (packs.length === 0) {
      return;
    }
    prefetchTeamsPanelPacks(packs, teamsPanelPackLoaders);
  }, [
    researchWorkflowTeamSelected,
    aiSearchScopeTeamSelected,
    sourceCollectionWorkspaceSelected,
    researchWorkspaceView,
  ]);
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
  const sourceCollectionNeedsCandidateList = sourceCollectionWorkspaceSelected;
  const teamWorkflowCandidateListEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "overview"
      || researchWorkspaceView === "candidates"
      || sourceCollectionNeedsCandidateList
    ),
  );
  const teamWorkflowGraphEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "graph"
      || (sourceCollectionWorkspaceSelected && (selectedSourceCollectionStageId === "relations" || selectedSourceCollectionStageId === "ingestion"))
    ),
  );
  const teamWorkflowKnowledgeIngestionEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "ingestion"
      || (sourceCollectionWorkspaceSelected && selectedSourceCollectionStageId === "ingestion")
    ),
  );
  const teamWorkflowSourceQualityEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "graph"
      || (sourceCollectionWorkspaceSelected && (selectedSourceCollectionStageId === "extraction" || selectedSourceCollectionStageId === "relations" || selectedSourceCollectionStageId === "ingestion"))
    ),
  );
  const researchStageRoundStatusEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && !sourceCollectionWorkspaceSelected,
  );
  const aiSearchRunsQuery = useQuery({
    queryKey: queryKeys.teamAiSearchRuns(effectiveTeamId || "none", AI_SEARCH_RUN_PREVIEW_LIMIT),
    queryFn: ({ signal }) =>
      fetchJson<AiSearchRunListPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/ai-search-runs?limit=${AI_SEARCH_RUN_PREVIEW_LIMIT}`,
        { signal },
      ),
    enabled: Boolean(effectiveTeamId && aiSearchScopeTeamSelected),
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
  const researchStageAgentBindingsByStage = useMemo(() => {
    const roleBindings = new Map<string, { agentId: string; label: string; source: "canvas" | "member" | "fallback" }>();
    const roleDefinitions = knowledgeExpansionWorkflowTeamSelected ? KNOWLEDGE_EXPANSION_STAGE_AGENT_ROLES : RESEARCH_STAGE_AGENT_ROLES;

    for (const node of canvas?.nodes ?? []) {
      const role = normalizeAgentRoleKey(node.role);
      if (role && node.agentId && !roleBindings.has(role)) {
        roleBindings.set(role, { agentId: node.agentId, label: node.label || node.agentName || node.agentCode || node.agentId, source: "canvas" });
      }
    }

    for (const member of selectedTeam?.members ?? []) {
      const role = normalizeAgentRoleKey(member.role);
      if (role && member.agentId && !roleBindings.has(role)) {
        roleBindings.set(role, { agentId: member.agentId, label: member.agentName || member.agentCode || member.agentId, source: "member" });
      }
    }

    return Object.fromEntries(
      (Object.keys(roleDefinitions) as ResearchStageType[]).map((stageType) => {
        const bindings = roleDefinitions[stageType].map((definition) => {
          const matched = definition.roleKeys
            .map((role) => roleBindings.get(normalizeAgentRoleKey(role)))
            .find(Boolean);
          const fallbackAgentId = definition.fallbackAgentId && activeAgentsById.has(definition.fallbackAgentId)
            ? definition.fallbackAgentId
            : "";
          const agentId = matched?.agentId || fallbackAgentId || "";
          return {
            ...definition,
            agentId,
            agent: agentId ? activeAgentsById.get(agentId) ?? null : null,
            bindingLabel: matched?.label || "",
            bindingSource: matched?.source || (fallbackAgentId ? "fallback" : ""),
          };
        });
        return [stageType, bindings];
      }),
    ) as Record<ResearchStageType, Array<ResearchStageAgentRoleDefinition & {
      agentId: string;
      agent: AgentConfigWorkspaceAgent | null;
      bindingLabel: string;
      bindingSource: string;
    }>>;
  }, [activeAgentsById, canvas, knowledgeExpansionWorkflowTeamSelected, selectedTeam?.members]);
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, selectedTeam?.teamId),
    [projectBusQuery.data, selectedTeam?.teamId],
  );

  // Shell team pick / canvas frame / node-draft sync live in useTeamsShellCanvasWorkspace + useTeamsCanvasProjection.
  // SC stage URL sync + pagination reset live in useSourceCollectionWorkspace.

  const {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
  } = useTeamShellMutations({
    selectedTeamId,
    setSelectedTeamId,
    setSelectedNodeId,
    clearTeamSearchParams: () => setSearchParams({}),
    setTeamMessage,
    setTeamTaskTopic,
    chatWorkspaceCache,
  });

  const {
    resetResearchProjectSourceCollectionMutation,
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
  } = useTeamWorkflowStartMutations({
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionOwnerAgentId,
    sourceCollectionAgentIds,
    activeSourceCollectionResearchProjectId,
    sourceCollectionStandalone,
    chatWorkspaceCache,
    setSelectedSourceCollectionRunId,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    setSourceCollectionOutputDraft,
    setResearchWorkspaceView,
    navigateToSourceCollection: (teamId) => navigate(researchSourceCollectionRoute(teamId)),
  });

  const {
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
  } = useTeamExperimentLoopMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionIngestorAgentId,
    sourceCollectionDraftGoal: sourceCollectionDraft.goal,
    latestExperimentStageRoundId: experimentPlanningStatusQuery.data?.latestExperimentRound?.stageRoundId || "",
    setExperimentSmokeResultDraft,
    setExperimentFullRunResultDraft,
    setExperimentKnowledgeIngestionDraft,
    setResearchLoopEvidenceDraft,
    setResearchLoopDecisionDraft,
  });

  const {
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
  } = useTeamSourceCollectionMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionDraftTopic: sourceCollectionDraft.topic,
    sourceCollectionDraftMaxResultsPerQuery: sourceCollectionDraft.maxResultsPerQuery || 3,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    // Bound later via ref once panel scroll helper is declared below.
    scrollSourceCollectionPanelIntoView: (panelId) => {
      scrollSourceCollectionPanelIntoViewRef.current(panelId);
    },
  });

  const canvasSavePendingForTeam = (teamId: string | undefined | null) =>
    saveCanvasMutation.isPending && Boolean(teamId) && saveCanvasMutation.variables?.teamId === teamId;

  function saveCanvas(nextCanvas: TeamOrganizationCanvas | null) {
    if (!nextCanvas || canvasSavePendingForTeam(nextCanvas.teamId)) {
      return;
    }
    saveCanvasMutation.mutate(writableTeamCanvas(nextCanvas));
  }

  function selectResearchWorkspaceView(view: ResearchWorkspaceView) {
    setResearchWorkspaceView(view);
    if (view === "canvas") {
      window.requestAnimationFrame(() => {
        document.getElementById(researchWorkspaceAnchorId(view))?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    }
  }

  async function handleResearchPrimaryAction(action: ResearchPrimaryAction) {
    if (action.blocked || !selectedTeam?.teamId) {
      return;
    }
    selectResearchWorkspaceView(action.navigateView);
    if (action.launchStageType) {
      await launchResearchStage(action.launchStageType, action.launchMode || "continue_or_start");
    }
  }

  function selectTeamRecord(team: Team) {
    setSelectedTeamId(team.teamId);
    setSelectedNodeId("");
    if (isResearchWorkflowTeam(team)) {
      setResearchWorkspaceView(teamShellMode === "canvas" ? "canvas" : "overview");
    }
    const nextParams = new URLSearchParams();
    nextParams.set("team", team.teamId);
    nextParams.set("teamMode", teamShellMode);
    if (isResearchWorkflowTeam(team)) {
      nextParams.set("researchView", teamShellMode === "canvas" ? "canvas" : "overview");
    }
    setSearchParams(nextParams);
  }

  function selectTeamShellMode(mode: TeamShellMode) {
    setTeamShellMode(mode);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("teamMode", mode);
    if (mode === "canvas") {
      if (researchWorkflowTeamSelected) {
        setResearchWorkspaceView("canvas");
        nextParams.set("researchView", "canvas");
      }
    } else {
      if (researchWorkspaceView === "canvas") {
        setResearchWorkspaceView("overview");
      }
      if (nextParams.get("researchView") === "canvas") {
        nextParams.set("researchView", "overview");
      }
    }
    setSearchParams(nextParams, { replace: true });
  }

  async function launchResearchStage(stageType: ResearchStageType, mode: "continue_or_start" | "new_round" = "continue_or_start") {
    if (!selectedTeam?.teamId || selectedTeamStartResearchStagePending) {
      return;
    }
    if (stageType === "knowledge_collection" && !researchStageCanLaunch) {
      return;
    }
    try {
      await startResearchStageRoundMutation.mutateAsync({
        teamId: selectedTeam.teamId,
        stageType,
        mode,
        draft: sourceCollectionDraft,
      });
      if (stageType !== "knowledge_collection" && challengeCupResearchTeamSelected) {
        const taskKind = stageType === "experiment" ? "experiment_design" : "iteration_decision";
        const agentTask = await researchStageProjectAgentTasks.startTask(taskKind, {
          returnTo: researchWorkspaceStageRoute(selectedTeam.teamId, stageType),
          returnLabel: stageType === "experiment" ? "返回实验设计" : "返回执行与迭代",
        });
        if (agentTask.chatRoute) {
          navigate(agentTask.chatRoute);
        }
      }
    } catch {
      // Both mutations expose their typed error state to the stage panel.
    }
  }

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
    createExperimentPlanPending:
      createExperimentPlanMutation.isPending
      && createExperimentPlanMutation.variables?.teamId === effectiveTeamId,
    materializeEngineeringProxyPending:
      materializeEngineeringProxyHypothesisMutation.isPending
      && materializeEngineeringProxyHypothesisMutation.variables?.teamId === effectiveTeamId,
    completeScientificHypothesisCandidateId:
      completeScientificHypothesisFromDesignMutation.isPending
      && completeScientificHypothesisFromDesignMutation.variables?.teamId === effectiveTeamId
        ? completeScientificHypothesisFromDesignMutation.variables.candidateId
        : "",
    reviewExperimentHypothesisCandidateId:
      reviewExperimentHypothesisMutation.isPending
      && reviewExperimentHypothesisMutation.variables?.teamId === effectiveTeamId
        ? reviewExperimentHypothesisMutation.variables.candidateId
        : "",
    createExperimentHypothesisRevisionCandidateId:
      createExperimentHypothesisRevisionMutation.isPending
      && createExperimentHypothesisRevisionMutation.variables?.teamId === effectiveTeamId
        ? createExperimentHypothesisRevisionMutation.variables.candidateId
        : "",
    freezeExperimentDesignPending:
      freezeExperimentDesignMutation.isPending
      && freezeExperimentDesignMutation.variables?.teamId === effectiveTeamId,
    registerExperimentBaselineArtifactPending:
      registerExperimentBaselineArtifactMutation.isPending
      && registerExperimentBaselineArtifactMutation.variables?.teamId === effectiveTeamId,
    registerExperimentSmokeResultPending:
      registerExperimentSmokeResultMutation.isPending
      && registerExperimentSmokeResultMutation.variables?.teamId === effectiveTeamId,
    runExperimentSmokePending:
      runExperimentSmokeMutation.isPending
      && runExperimentSmokeMutation.variables?.teamId === effectiveTeamId,
    registerExperimentFullRunResultPending:
      registerExperimentFullRunResultMutation.isPending
      && registerExperimentFullRunResultMutation.variables?.teamId === effectiveTeamId,
    requestExperimentKnowledgeIngestionPending:
      requestExperimentKnowledgeIngestionMutation.isPending
      && requestExperimentKnowledgeIngestionMutation.variables?.teamId === effectiveTeamId,
    createResearchLoopPending:
      createResearchLoopMutation.isPending
      && createResearchLoopMutation.variables?.teamId === effectiveTeamId,
    recordResearchLoopEvidencePending:
      recordResearchLoopEvidenceMutation.isPending
      && recordResearchLoopEvidenceMutation.variables?.teamId === effectiveTeamId,
    recordResearchLoopDecisionPending:
      recordResearchLoopDecisionMutation.isPending
      && recordResearchLoopDecisionMutation.variables?.teamId === effectiveTeamId,
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



  function sourceCollectionStageAgentBindings(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageAgentBindingsForStage(
      stageId,
      researchStageAgentBindingsByStage.knowledge_collection ?? [],
    );
  }

  function sourceCollectionStagePrimaryAgentBinding(stageId: SourceCollectionStageModuleId) {
    return selectSourceCollectionStagePrimaryBinding(
      sourceCollectionStageAgentBindings(stageId),
      (agent) => Boolean(researchStageAgentDirectChatRoute(agent)),
    );
  }

  function sourceCollectionStageAgentChatState(stageId: SourceCollectionStageModuleId): {
    binding: ReturnType<typeof sourceCollectionStagePrimaryAgentBinding> | null;
    route: string;
    status: SourceCollectionStageAgentChatStatus;
  } {
    const binding = sourceCollectionStagePrimaryAgentBinding(stageId);
    const returnRoute = sourceCollectionStageReturnRoute(stageId);
    const returnLabel = sourceCollectionStageChatReturnLabel(stageId);
    const currentTaskSessionRoute = researchStageSessionChatRoute(
      sourceCollectionSummaryQuery.data?.latestTasks?.[stageId]?.sessionId,
      returnRoute,
      returnLabel,
    );
    const stageSessionPending = Boolean(
      selectedSourceCollectionRunEffectiveId
      && !sourceCollectionSummaryQuery.data
      && (sourceCollectionSummaryQuery.isPending || sourceCollectionSummaryQuery.isFetching),
    );
    const canCreateProjectSession = Boolean(
      selectedSourceCollectionRunEffectiveId
      && String(binding?.agent?.agentId || binding?.agentId || "").trim(),
    );
    const route = currentTaskSessionRoute;
    return resolveSourceCollectionStageAgentChatState({
      binding,
      route,
      stageSessionPending,
      canCreateProjectSession,
      projectRunAvailable: Boolean(selectedSourceCollectionRunEffectiveId),
      agentSummaryPending: agentSummaryQuery.isPending,
      agentSummaryFetching: agentSummaryQuery.isFetching,
      agentSummaryError: agentSummaryQuery.isError,
    });
  }

  function sourceCollectionStageReturnRoute(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageReturnRoutePure(
      selectedTeam?.teamId || RESEARCH_TEAM_ID,
      stageId,
      researchSourceCollectionRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID),
    );
  }

  function sourceCollectionStageChatReturnLabel(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageChatReturnLabelPure(stageId, lang, SOURCE_COLLECTION_STAGE_CHAT_LABELS);
  }

  function repairSelectedWorkflowTeamAgentsIfNeeded() {
    if (!selectedTeam?.teamId) {
      return;
    }
    if (knowledgeExpansionWorkflowTeamSelected && !repairKnowledgeExpansionTeamAgentsMutation.isPending) {
      repairKnowledgeExpansionTeamAgentsMutation.mutate(selectedTeam.teamId);
      return;
    }
    if (isChallengeCupResearchWorkflowTeam(selectedTeam) && !repairChallengeCupTeamAgentsMutation.isPending) {
      repairChallengeCupTeamAgentsMutation.mutate(selectedTeam.teamId);
    }
  }

  async function openSourceCollectionStageAgentChat(stageId: SourceCollectionStageModuleId) {
    const chatState = sourceCollectionStageAgentChatState(stageId);
    const binding = chatState.binding;
    const teamId = selectedTeam?.teamId || RESEARCH_TEAM_ID;
    const runId = selectedSourceCollectionRunEffectiveId;
    const agentId = String(binding?.agent?.agentId || binding?.agentId || "").trim();
    if (teamId && runId && agentId) {
      try {
        const payload = await seedSourceCollectionAgentSessionContextMutation.mutateAsync({
          teamId,
          runId,
          stageId,
          agentId,
          agentRole: binding?.key || "",
        });
        if (payload.chatRoute) {
          navigate(payload.chatRoute);
        }
      } catch (error) {
        console.warn("Failed to resolve source collection experiment session before navigation.", error);
      }
      return;
    }
    if (chatState.status === "repair") {
      repairSelectedWorkflowTeamAgentsIfNeeded();
    }
  }


  async function startSourceCollectionStageSessionTask(
    stageId: SourceCollectionStageModuleId,
    options: { formalRetry?: boolean } = {},
  ) {
    if (
      !selectedTeam?.teamId
      || startSourceCollectionStageSessionTaskMutation.isPending
      || resetResearchProjectSourceCollectionMutation.isPending
    ) {
      return;
    }
    const actionReadiness = sourceCollectionStageActionReadinessFor(stageId);
    if (actionReadiness.disabled) {
      return;
    }
    openSourceCollectionStage(stageId);
    const chatState = sourceCollectionStageAgentChatState(stageId);
    const binding = chatState.binding;
    const agentId = String(binding?.agent?.agentId || binding?.agentId || "").trim();
    const agentRole = String(binding?.key || "").trim();
    if (!agentId) {
      if (chatState.status === "repair") {
        repairSelectedWorkflowTeamAgentsIfNeeded();
      }
      return;
    }
    let runId = selectedSourceCollectionRunEffectiveId;
    if (!runId && stageId === "finding") {
      if (knowledgeExpansionWorkflowTeamSelected) {
        if (!sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
          return;
        }
        try {
          const runPayload = await startSourceCollectionRunMutation.mutateAsync({
            teamId: selectedTeam.teamId,
            draft: sourceCollectionDraft,
          });
          runId = runPayload.run.runId;
        } catch {
          return;
        }
      } else {
        if (!researchStageCanLaunch || selectedTeamStartResearchStagePending) {
          return;
        }
        let stagePayload: ResearchStageRoundStartPayload;
        try {
          stagePayload = await startResearchStageRoundMutation.mutateAsync({
            teamId: selectedTeam.teamId,
            stageType: "knowledge_collection",
            draft: sourceCollectionDraft,
          });
        } catch {
          return;
        }
        runId = stagePayload.run?.runId || stagePayload.stageRound.sourceRunIds?.[0] || "";
      }
    }
    if (!runId) {
      return;
    }
    try {
      const payload = await startSourceCollectionStageSessionTaskMutation.mutateAsync({
        teamId: selectedTeam.teamId,
        runId,
        stageId,
        agentId,
        agentRole,
        returnTo: sourceCollectionStageReturnRoute(stageId),
        returnLabel: sourceCollectionStageChatReturnLabel(stageId),
        requestedByAgent: sourceCollectionOwnerAgentId,
        idempotencyKey: sourceCollectionStageTaskClickKey(stageId),
        formalRetry: options.formalRetry ?? sourceCollectionStageFormalRetryRequired(stageId),
      });
      if (payload.chatRoute) {
        navigate(payload.chatRoute);
      }
    } catch {
      return;
    }
  }

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

  function openSourceCollectionStage(stageId: SourceCollectionStageModuleId) {
    selectSourceCollectionStage(stageId);
    setSourceCollectionFocusedPanelId("");
  }

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
    if (!teamWorkflow) {
      return null;
    }
    return (
      <ResearchOverviewSurface
        lang={lang}
        className={styles.researchOverviewSurface}
        primary={{
          action: researchPrimaryAction,
          handoff: researchStageHandoff,
          pending: selectedTeamStartResearchStagePending,
          projectName: activeSourceCollectionResearchProject?.name || researchProjectProgress?.experimentName || "",
          metrics: [
            {
              key: "stage",
              label: lang === "zh" ? "阶段" : "Stage",
              value: workflowStateLabel(
                researchProjectProgress?.currentStage || teamWorkflow.stateMachine.currentStage,
                lang,
              ),
            },
            {
              key: "sources",
              label: lang === "zh" ? "资料批次" : "Runs",
              value: String(researchProjectProgress?.sourceRunCount ?? sourceCollectionRuns.length),
            },
            {
              key: "candidates",
              label: lang === "zh" ? "候选" : "Candidates",
              value: String(
                researchProjectProgress?.sourceCandidateCount
                ?? teamWorkflow.candidateStore.candidateCount,
              ),
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
        advanced={(
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
        )}
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
        openedPath={selectedSourceCollectionStorageOpenResult?.openedPath ?? ""}
        errorMessage={selectedSourceCollectionStorageOpenError?.message ?? ""}
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



  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">) {
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
      />
    );
  }

  function addNode() {
    if (!durableCanvas || researchCanvasReadOnly) {
      return;
    }
    const id = nextNodeId(durableCanvas.nodes);
    saveCanvas({
      ...durableCanvas,
      nodes: [
        ...durableCanvas.nodes,
        {
          id,
          label: lang === "zh" ? "新角色" : "New role",
          type: "role",
          status: "unbound",
          x: 140 + durableCanvas.nodes.length * 54,
          y: 150 + durableCanvas.nodes.length * 36,
          agentId: "",
          agentCode: "",
          agentName: "",
          role: "",
          purpose: "",
        },
      ],
    });
    setSelectedNodeId(id);
  }

  function applyNodeDraft() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    const membership = nodeDraft.agentId ? agentTeamMembership.get(nodeDraft.agentId) : undefined;
    if (membership && membership.teamId !== selectedTeam?.teamId) {
      return;
    }
    const agent = activeAgents.find((item) => item.agentId === nodeDraft.agentId);
    saveCanvas({
      ...durableCanvas,
      nodes: durableCanvas.nodes.map((node) =>
        node.id === selectedNode.id
          ? {
              ...node,
              label: nodeDraft.label.trim() || agent?.displayName || node.label,
              role: nodeDraft.role.trim(),
              purpose: nodeDraft.purpose.trim(),
              agentId: nodeDraft.agentId,
              agentCode: agent?.agentCode ?? "",
              agentName: agent?.displayName ?? "",
              type: nodeDraft.agentId ? "agent" : "role",
              status: nodeDraft.agentId ? "bound" : "unbound",
            }
          : node,
      ),
    });
  }

  function unbindSelectedNode() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    saveCanvas({
      ...durableCanvas,
      nodes: durableCanvas.nodes.map((node) =>
        node.id === selectedNode.id
          ? {
              ...node,
              agentId: "",
              agentCode: "",
              agentName: "",
              type: "role",
              status: "unbound",
            }
          : node,
      ),
    });
  }

  function deleteSelectedNode() {
    if (!durableCanvas || !selectedNode || durableCanvas.nodes.length <= 1 || researchCanvasReadOnly) {
      return;
    }
    const deletedNodeId = selectedNode.id;
    const nextNodes = durableCanvas.nodes.filter((node) => node.id !== deletedNodeId);
    saveCanvas({
      ...durableCanvas,
      nodes: nextNodes,
      edges: durableCanvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId),
    });
    setSelectedNodeId(nextNodes[0]?.id ?? "");
  }

  function connectFromLead() {
    if (!durableCanvas || !selectedNode || durableCanvas.nodes.length < 2 || researchCanvasReadOnly) {
      return;
    }
    const source = durableCanvas.nodes[0];
    if (source.id === selectedNode.id || durableCanvas.edges.some((edge) => edge.source === source.id && edge.target === selectedNode.id)) {
      return;
    }
    saveCanvas({
      ...durableCanvas,
      edges: [
        ...durableCanvas.edges,
        {
          id: `${source.id}-${selectedNode.id}`,
          source: source.id,
          target: selectedNode.id,
          label: "",
          type: "reports_to",
        },
      ],
    });
  }

  function startNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: TeamCanvasNode) {
    if (!durableCanvas || canvasSavePendingForTeam(durableCanvas.teamId) || researchCanvasReadOnly) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelectedNodeId(node.id);
    setLockedCanvasViewportStyle(canvasViewportStyle);
    dragStateRef.current = {
      nodeId: node.id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: node.x,
      startY: node.y,
      currentX: node.x,
      currentY: node.y,
      scale: canvasScale,
      moved: false,
    };
  }

  function commitNodeDragPosition(dragState: NodeDragState) {
    setNodePositionDrafts((current) => {
      const currentPosition = current[dragState.nodeId];
      if (currentPosition?.x === dragState.currentX && currentPosition?.y === dragState.currentY) {
        return current;
      }
      return {
        ...current,
        [dragState.nodeId]: { x: dragState.currentX, y: dragState.currentY },
      };
    });
  }

  function requestNodeDragFrame(dragState: NodeDragState) {
    if (dragFrameRef.current) {
      return;
    }
    dragFrameRef.current = window.requestAnimationFrame(() => {
      dragFrameRef.current = 0;
      const activeDrag = dragStateRef.current;
      commitNodeDragPosition(activeDrag ?? dragState);
    });
  }

  function moveNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState) {
      return;
    }
    const deltaX = (event.clientX - dragState.startClientX) / dragState.scale;
    const deltaY = (event.clientY - dragState.startClientY) / dragState.scale;
    const nextX = Math.max(0, Math.round(dragState.startX + deltaX));
    const nextY = Math.max(0, Math.round(dragState.startY + deltaY));
    dragState.moved = dragState.moved || Math.abs(deltaX) > 2 || Math.abs(deltaY) > 2;
    dragState.currentX = nextX;
    dragState.currentY = nextY;
    requestNodeDragFrame(dragState);
  }

  function finishNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || !durableCanvas) {
      return;
    }
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current = null;
    if (dragFrameRef.current) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = 0;
    }
    if (!dragState.moved) {
      return;
    }
    commitNodeDragPosition(dragState);
    saveCanvas({
      ...durableCanvas,
      nodes: durableCanvas.nodes.map((node) => (node.id === dragState.nodeId ? { ...node, x: dragState.currentX, y: dragState.currentY } : node)),
    });
  }

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
        !agent && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching),
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
      return candidate.currentWorkflowNode === "steward_ingestion" || String(metadata.taskType || "") === "steward_pack_draft";
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
      "progress",
    ],
    queryFn: () => getTeamResearchProjectProgress(
      effectiveTeamId,
      activeSourceCollectionResearchProjectId,
    ),
    enabled: Boolean(
      researchWorkflowTeamSelected
      && researchWorkspaceView === "overview"
      && effectiveTeamId
      && activeSourceCollectionResearchProjectId,
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
    experimentDesignFrozen: Boolean(
      researchProjectProgress
      && researchProjectProgress.frozenExperimentPlanCount > 0,
    ),
  }), [
    activeSourceCollectionResearchProjectId,
    researchProjectProgress,
    researchStagePhases,
    sourceCollectionRuns.length,
    teamWorkflow?.candidateStore?.candidateCount,
  ]);
  const researchPrimaryAction = useMemo(
    () => resolveResearchPrimaryAction(researchPrimaryActionInput),
    [researchPrimaryActionInput],
  );
  const researchStageHandoff = useMemo(
    () => resolveResearchStageHandoff(researchPrimaryActionInput),
    [researchPrimaryActionInput],
  );
  const sourceCollectionSummary = sourceCollectionSummaryQuery.data ?? null;
  const sourceCollectionSummaryRun = isRecord(sourceCollectionSummary?.run) ? sourceCollectionSummary.run : null;
  const sourceCollectionSummaryRunId = String(sourceCollectionSummaryRun?.runId || sourceCollectionSummary?.runId || "");
  const sourceCollectionActionRunId = selectedSourceCollectionRunEffectiveId || sourceCollectionSummaryRunId;
  const sourceCollectionPhaseCloseGate = sourceCollectionPhaseCloseGateForRun(
    sourceCollectionSummary,
    selectedSourceCollectionRunEffectiveId,
  );
  const sourceCollectionSummaryStageRound = useMemo<ResearchStageRound | null>(() => {
    if (!sourceCollectionSummary?.runId && !sourceCollectionSummary?.stageCards?.length) {
      return null;
    }
    const summaryRunId = String(sourceCollectionSummary.runId || sourceCollectionSummaryRunId || "");
    if (selectedSourceCollectionRunEffectiveId && summaryRunId && summaryRunId !== selectedSourceCollectionRunEffectiveId) {
      return null;
    }
    const roundRef = sourceCollectionSummary.stageRound ?? {};
    return {
      stageRoundId: String(roundRef.stageRoundId || `source-summary-${summaryRunId || "latest"}`),
      stageType: "knowledge_collection",
      roundNumber: Number(roundRef.roundNumber || 0),
      status: String(roundRef.status || sourceCollectionSummary.status || "ready"),
      topic: "",
      goal: "",
      sourceRunIds: summaryRunId ? [summaryRunId] : [],
      sourceCollectionStageCards: sourceCollectionSummary.stageCards ?? [],
      sourceCollectionStageCardSummary: sourceCollectionSummary.stageCardSummary ?? sourceCollectionSummary.summary ?? {},
    };
  }, [selectedSourceCollectionRunEffectiveId, sourceCollectionSummary, sourceCollectionSummaryRunId]);
  const sourceCollectionStageRound = useMemo(() => selectSourceCollectionStageRound(
    sourceCollectionSummaryStageRound,
    researchStagePhases,
    researchStageRoundStatus,
    selectedSourceCollectionRunEffectiveId,
  ), [
    researchStagePhases,
    researchStageRoundStatus,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSummaryStageRound,
  ]);
  const sourceCollectionStageCards = sourceCollectionStageRound?.sourceCollectionStageCards ?? [];
  const sourceCollectionStageCardById = useMemo(() => {
    const mapping = new Map<SourceCollectionStageModuleId, SourceCollectionStageCardProjection>();
    sourceCollectionStageCards.forEach((card) => {
      const stageId = parseSourceCollectionStageModuleId(card.stageId);
      if (stageId) {
        mapping.set(stageId, { ...card, stageId });
      }
    });
    return mapping;
  }, [sourceCollectionStageCards]);
  const experimentPlanningStatus = experimentPlanningStatusQuery.data ?? null;
  const sourceCollectionRecords = sourceCollectionRecordsQuery.data?.records ?? [];
  const sourceCollectionAssignments = sourceCollectionAssignmentsQuery.data?.assignments ?? [];
  const sourceCollectionRunStatus = sourceCollectionRunStatusQuery.data ?? sourceCollectionSummary?.runStatus ?? null;
  const sourceCollectionSearchPlanRef = selectedSourceCollectionRun?.scope?.dataSearchPlanRef ?? null;
  const aiSearchRuns = aiSearchRunsQuery.data?.runs ?? [];
  const selectedTeamStartAiSearchPending =
    startAiSearchRunMutation.isPending && startAiSearchRunMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartAiSearchError =
    startAiSearchRunMutation.variables?.teamId === selectedTeam?.teamId && startAiSearchRunMutation.error instanceof Error
      ? startAiSearchRunMutation.error
      : null;
  const selectedTeamStartAiSearchResult =
    startAiSearchRunMutation.variables?.teamId === selectedTeam?.teamId ? startAiSearchRunMutation.data : undefined;
  const latestAiSearchRun = selectedTeamStartAiSearchResult ?? aiSearchRuns[0] ?? null;
  const aiSearchRunCanStart = Boolean(selectedTeam?.teamId && aiSearchRunTopic.trim() && !selectedTeamStartAiSearchPending);
  const selectedSourceCollectionAssignment =
    sourceCollectionAssignments.find((item) => item.assignmentId === sourceCollectionOutputDraft.assignmentId)
    ?? sourceCollectionAssignments[0]
    ?? null;
  const selectedSourceCollectionQueries = selectedSourceCollectionAssignment?.scope?.assignedQueries ?? [];
  const sourceCollectionFindingRunOptions = sourceCollectionRuns.map((run) => ({
    id: run.runId,
    label: `${sourceCollectionRunLabel(run.runId)} · ${sourceCollectionRunTitleLabel(run.title, lang)}`,
  }));
  const sourceCollectionFindingAssignments = sourceCollectionAssignments.map((assignment) => ({
    id: assignment.assignmentId,
    roleLabel: sourceCollectionAgentRoleLabel(assignment.agentRole, lang),
    statusLabel: sourceCollectionStatusLabel(assignment.status, lang),
    queryCountLabel: `${assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0} ${lang === "zh" ? "条搜索" : "queries"}`,
    active: assignment.assignmentId === selectedSourceCollectionAssignment?.assignmentId,
  }));
  const sourceCollectionFindingQueries = selectedSourceCollectionQueries.slice(0, 6).map((query) => ({
    id: query.queryId,
    title: translateResearchPhrase(query.query, lang),
    meta: `${query.queryId} · ${sourceCollectionSourceTypeLabel(query.sourceType, lang)} · ${sourceCollectionLanguageLabel(query.language, lang)}`,
  }));
  const sourceCollectionCanStart = Boolean(selectedTeam?.teamId && sourceCollectionDraft.topic.trim());
  const researchStageCanLaunch = Boolean(selectedTeam?.teamId && sourceCollectionDraft.topic.trim());
  const sourceCollectionResetResearchProjectId = activeSourceCollectionResearchProjectId.trim();
  const sourceCollectionResetAvailable = Boolean(
    sourceCollectionResetResearchProjectId
    && sourceCollectionRuns.length > 0,
  );
  const selectedResearchProjectSourceCollectionResetPending =
    resetResearchProjectSourceCollectionMutation.isPending
    && resetResearchProjectSourceCollectionMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedResearchProjectSourceCollectionResetError =
    resetResearchProjectSourceCollectionMutation.variables?.teamId === selectedTeam?.teamId
    && resetResearchProjectSourceCollectionMutation.error instanceof Error
      ? resetResearchProjectSourceCollectionMutation.error
      : null;
  const selectedTeamStartResearchStagePending =
    (startResearchStageRoundMutation.isPending && startResearchStageRoundMutation.variables?.teamId === selectedTeam?.teamId)
    || researchStageProjectAgentTasks.isStarting;
  const selectedTeamStartResearchStageError =
    startResearchStageRoundMutation.variables?.teamId === selectedTeam?.teamId && startResearchStageRoundMutation.error instanceof Error
      ? startResearchStageRoundMutation.error
      : researchStageProjectAgentTasks.error instanceof Error
        ? researchStageProjectAgentTasks.error
        : null;
  const selectedTeamStartResearchStageResult =
    startResearchStageRoundMutation.variables?.teamId === selectedTeam?.teamId ? startResearchStageRoundMutation.data : undefined;
  const selectedTeamCreateExperimentPlanPending =
    createExperimentPlanMutation.isPending && createExperimentPlanMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamCreateExperimentPlanError =
    createExperimentPlanMutation.variables?.teamId === selectedTeam?.teamId && createExperimentPlanMutation.error instanceof Error
      ? createExperimentPlanMutation.error
      : null;
  const selectedTeamCreateExperimentPlanResult =
    createExperimentPlanMutation.variables?.teamId === selectedTeam?.teamId ? createExperimentPlanMutation.data : undefined;
  const selectedTeamMaterializeEngineeringProxyPending =
    materializeEngineeringProxyHypothesisMutation.isPending
    && materializeEngineeringProxyHypothesisMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamMaterializeEngineeringProxyError =
    materializeEngineeringProxyHypothesisMutation.variables?.teamId === selectedTeam?.teamId
    && materializeEngineeringProxyHypothesisMutation.error instanceof Error
      ? materializeEngineeringProxyHypothesisMutation.error
      : null;
  const selectedTeamCompleteScientificHypothesisCandidateId =
    completeScientificHypothesisFromDesignMutation.isPending
    && completeScientificHypothesisFromDesignMutation.variables?.teamId === selectedTeam?.teamId
      ? completeScientificHypothesisFromDesignMutation.variables.candidateId
      : "";
  const selectedTeamCompleteScientificHypothesisError =
    completeScientificHypothesisFromDesignMutation.variables?.teamId === selectedTeam?.teamId
    && completeScientificHypothesisFromDesignMutation.error instanceof Error
      ? completeScientificHypothesisFromDesignMutation.error
      : null;
  const selectedTeamReviewExperimentHypothesisCandidateId =
    reviewExperimentHypothesisMutation.isPending
    && reviewExperimentHypothesisMutation.variables?.teamId === selectedTeam?.teamId
      ? reviewExperimentHypothesisMutation.variables.candidateId
      : "";
  const selectedTeamReviewExperimentHypothesisError =
    reviewExperimentHypothesisMutation.variables?.teamId === selectedTeam?.teamId
    && reviewExperimentHypothesisMutation.error instanceof Error
      ? reviewExperimentHypothesisMutation.error
      : null;
  const selectedTeamCreateExperimentHypothesisRevisionCandidateId =
    createExperimentHypothesisRevisionMutation.isPending
    && createExperimentHypothesisRevisionMutation.variables?.teamId === selectedTeam?.teamId
      ? createExperimentHypothesisRevisionMutation.variables.candidateId
      : "";
  const selectedTeamCreateExperimentHypothesisRevisionError =
    createExperimentHypothesisRevisionMutation.variables?.teamId === selectedTeam?.teamId
    && createExperimentHypothesisRevisionMutation.error instanceof Error
      ? createExperimentHypothesisRevisionMutation.error
      : null;
  const selectedTeamFreezeExperimentDesignPending =
    freezeExperimentDesignMutation.isPending && freezeExperimentDesignMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamFreezeExperimentDesignError =
    freezeExperimentDesignMutation.variables?.teamId === selectedTeam?.teamId && freezeExperimentDesignMutation.error instanceof Error
      ? freezeExperimentDesignMutation.error
      : null;
  const selectedTeamFreezeExperimentDesignResult =
    freezeExperimentDesignMutation.variables?.teamId === selectedTeam?.teamId
      ? freezeExperimentDesignMutation.data
      : undefined;
  const selectedTeamRegisterExperimentBaselineArtifactPending =
    registerExperimentBaselineArtifactMutation.isPending && registerExperimentBaselineArtifactMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRegisterExperimentBaselineArtifactError =
    registerExperimentBaselineArtifactMutation.variables?.teamId === selectedTeam?.teamId && registerExperimentBaselineArtifactMutation.error instanceof Error
      ? registerExperimentBaselineArtifactMutation.error
      : null;
  const selectedTeamRegisterExperimentBaselineArtifactResult =
    registerExperimentBaselineArtifactMutation.variables?.teamId === selectedTeam?.teamId
      ? registerExperimentBaselineArtifactMutation.data
      : undefined;
  const selectedTeamRunExperimentSmokePending =
    runExperimentSmokeMutation.isPending && runExperimentSmokeMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRunExperimentSmokeError =
    runExperimentSmokeMutation.variables?.teamId === selectedTeam?.teamId && runExperimentSmokeMutation.error instanceof Error
      ? runExperimentSmokeMutation.error
      : null;
  const selectedTeamRunExperimentSmokeResult =
    runExperimentSmokeMutation.variables?.teamId === selectedTeam?.teamId
      ? runExperimentSmokeMutation.data
      : undefined;
  const selectedTeamRegisterExperimentSmokeResultPending =
    registerExperimentSmokeResultMutation.isPending && registerExperimentSmokeResultMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRegisterExperimentSmokeResultError =
    registerExperimentSmokeResultMutation.variables?.teamId === selectedTeam?.teamId && registerExperimentSmokeResultMutation.error instanceof Error
      ? registerExperimentSmokeResultMutation.error
      : null;
  const selectedTeamRegisterExperimentSmokeResultResult =
    registerExperimentSmokeResultMutation.variables?.teamId === selectedTeam?.teamId
      ? registerExperimentSmokeResultMutation.data
      : undefined;
  const selectedTeamRegisterExperimentFullRunResultPending =
    registerExperimentFullRunResultMutation.isPending && registerExperimentFullRunResultMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRegisterExperimentFullRunResultError =
    registerExperimentFullRunResultMutation.variables?.teamId === selectedTeam?.teamId && registerExperimentFullRunResultMutation.error instanceof Error
      ? registerExperimentFullRunResultMutation.error
      : null;
  const selectedTeamRegisterExperimentFullRunResultResult =
    registerExperimentFullRunResultMutation.variables?.teamId === selectedTeam?.teamId
      ? registerExperimentFullRunResultMutation.data
      : undefined;
  const selectedTeamRequestExperimentKnowledgeIngestionPending =
    requestExperimentKnowledgeIngestionMutation.isPending && requestExperimentKnowledgeIngestionMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRequestExperimentKnowledgeIngestionError =
    requestExperimentKnowledgeIngestionMutation.variables?.teamId === selectedTeam?.teamId
    && requestExperimentKnowledgeIngestionMutation.error instanceof Error
      ? requestExperimentKnowledgeIngestionMutation.error
      : null;
  const selectedTeamRequestExperimentKnowledgeIngestionResult =
    requestExperimentKnowledgeIngestionMutation.variables?.teamId === selectedTeam?.teamId
      ? requestExperimentKnowledgeIngestionMutation.data
      : undefined;
  const researchLoopTemplatesPayload = researchLoopTemplatesQuery.data ?? null;
  const researchLoopStatus = researchLoopStatusQuery.data ?? null;
  const selectedTeamCreateResearchLoopPending =
    createResearchLoopMutation.isPending && createResearchLoopMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamCreateResearchLoopError =
    createResearchLoopMutation.variables?.teamId === selectedTeam?.teamId && createResearchLoopMutation.error instanceof Error
      ? createResearchLoopMutation.error
      : null;
  const selectedTeamCreateResearchLoopResult =
    createResearchLoopMutation.variables?.teamId === selectedTeam?.teamId ? createResearchLoopMutation.data : undefined;
  const selectedTeamRecordResearchLoopEvidencePending =
    recordResearchLoopEvidenceMutation.isPending && recordResearchLoopEvidenceMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRecordResearchLoopEvidenceError =
    recordResearchLoopEvidenceMutation.variables?.teamId === selectedTeam?.teamId && recordResearchLoopEvidenceMutation.error instanceof Error
      ? recordResearchLoopEvidenceMutation.error
      : null;
  const selectedTeamRecordResearchLoopEvidenceResult =
    recordResearchLoopEvidenceMutation.variables?.teamId === selectedTeam?.teamId ? recordResearchLoopEvidenceMutation.data : undefined;
  const selectedTeamRecordResearchLoopDecisionPending =
    recordResearchLoopDecisionMutation.isPending && recordResearchLoopDecisionMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRecordResearchLoopDecisionError =
    recordResearchLoopDecisionMutation.variables?.teamId === selectedTeam?.teamId && recordResearchLoopDecisionMutation.error instanceof Error
      ? recordResearchLoopDecisionMutation.error
      : null;
  const selectedTeamRecordResearchLoopDecisionResult =
    recordResearchLoopDecisionMutation.variables?.teamId === selectedTeam?.teamId ? recordResearchLoopDecisionMutation.data : undefined;
  const selectedTeamStartSourceCollectionPending =
    startSourceCollectionRunMutation.isPending && startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartSourceCollectionError =
    startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId && startSourceCollectionRunMutation.error instanceof Error
      ? startSourceCollectionRunMutation.error
      : null;
  const selectedTeamStartSourceCollectionResult =
    startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId ? startSourceCollectionRunMutation.data : undefined;
  const selectedTeamStartSourceCollectionStageTaskPending =
    startSourceCollectionStageSessionTaskMutation.isPending && startSourceCollectionStageSessionTaskMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartSourceCollectionStageTaskError =
    startSourceCollectionStageSessionTaskMutation.variables?.teamId === selectedTeam?.teamId && startSourceCollectionStageSessionTaskMutation.error instanceof Error
      ? startSourceCollectionStageSessionTaskMutation.error
      : null;
  const sourceCollectionStageSessionTaskPendingStageId =
    selectedTeamStartSourceCollectionStageTaskPending ? startSourceCollectionStageSessionTaskMutation.variables?.stageId : "";
  const sourceCollectionPromptCachePolicy =
    [
      selectedTeamStartSourceCollectionResult?.promptCachePolicy,
      selectedTeamStartSourceCollectionResult?.searchPlan.promptCachePolicy,
      selectedTeamStartResearchStageResult?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.sourceCollectionRun?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.searchPlan?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.stageRound.promptCachePolicy,
    ].find(hasSourceCollectionPromptCachePolicy) ?? null;
  const sourceCollectionPromptCachePolicyRef: TeamWorkflowSourceCollectionPromptCachePolicyRef | null =
    selectedSourceCollectionRun?.scope.promptCachePolicyRef
    ?? selectedSourceCollectionAssignment?.scope.promptCachePolicyRef
    ?? (sourceCollectionSearchPlanRef?.promptCachePolicyId
      ? {
          policyId: sourceCollectionSearchPlanRef.promptCachePolicyId,
          requirement: sourceCollectionSearchPlanRef.promptCacheRequirement,
          gateStatus: sourceCollectionSearchPlanRef.promptCacheGateStatus,
        }
      : null);
  const sourceCollectionPromptCacheStatus =
    sourceCollectionPromptCachePolicy?.gate?.status || sourceCollectionPromptCachePolicyRef?.gateStatus || "";
  const sourceCollectionPromptCacheMode =
    sourceCollectionPromptCachePolicy?.promptCacheMode || sourceCollectionPromptCachePolicyRef?.promptCacheMode || "";
  const sourceCollectionPromptCacheRequirement =
    sourceCollectionPromptCachePolicy?.requirement || sourceCollectionPromptCachePolicyRef?.requirement || SOURCE_COLLECTION_PROMPT_CACHE_POLICY.requirement;
  const sourceCollectionOutputHasRecord =
    Boolean(sourceCollectionOutputDraft.title.trim() || sourceCollectionOutputDraft.sourceRef.trim() || sourceCollectionOutputDraft.rawLocation.trim());
  const selectedTeamRecordSourceCollectionOutputPending =
    recordSourceCollectionOutputMutation.isPending && recordSourceCollectionOutputMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamRecordSourceCollectionOutputError =
    recordSourceCollectionOutputMutation.variables?.teamId === selectedTeam?.teamId && recordSourceCollectionOutputMutation.error instanceof Error
      ? recordSourceCollectionOutputMutation.error
      : null;
  const selectedTeamRecordSourceCollectionOutputResult =
    recordSourceCollectionOutputMutation.variables?.teamId === selectedTeam?.teamId ? recordSourceCollectionOutputMutation.data : undefined;
  const selectedTeamExecuteSourceCollectionSearchPending =
    executeSourceCollectionSearchMutation.isPending && executeSourceCollectionSearchMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamExecuteSourceCollectionSearchError =
    executeSourceCollectionSearchMutation.variables?.teamId === selectedTeam?.teamId && executeSourceCollectionSearchMutation.error instanceof Error
      ? executeSourceCollectionSearchMutation.error
      : null;
  const selectedTeamExecuteSourceCollectionSearchResult =
    executeSourceCollectionSearchMutation.variables?.teamId === selectedTeam?.teamId ? executeSourceCollectionSearchMutation.data : undefined;
  const selectedTeamExtractSourceCollectionCandidatesPending =
    extractSourceCollectionCandidatesMutation.isPending && extractSourceCollectionCandidatesMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamExtractSourceCollectionCandidatesError =
    extractSourceCollectionCandidatesMutation.variables?.teamId === selectedTeam?.teamId && extractSourceCollectionCandidatesMutation.error instanceof Error
      ? extractSourceCollectionCandidatesMutation.error
      : null;
  const selectedTeamExtractSourceCollectionCandidatesResult =
    extractSourceCollectionCandidatesMutation.variables?.teamId === selectedTeam?.teamId
    && extractSourceCollectionCandidatesMutation.data?.runId === selectedSourceCollectionRunEffectiveId
      ? extractSourceCollectionCandidatesMutation.data
      : null;
  const selectedTeamInitialSourceCollectionSearchResult = selectedTeamStartResearchStageResult?.sourceCollectionSearchExecution;
  const selectedSourceCollectionSearchExecutionResult =
    selectedTeamExecuteSourceCollectionSearchResult ?? selectedTeamInitialSourceCollectionSearchResult;
  const selectedSourceCollectionSearchAccepted = Boolean(selectedSourceCollectionSearchExecutionResult?.accepted);
  const runtimeSourceCollectionActiveWorkRun = sourceCollectionActiveWorkRunFromRuntime(
    runtimeSummaryQuery.data,
    selectedSourceCollectionRunEffectiveId,
  );
  const summarySourceCollectionActiveWorkRun = isRecord(sourceCollectionSummary?.activeWorkRun)
    ? sourceCollectionSummary.activeWorkRun as WorkRunSnapshot
    : undefined;
  const selectedSourceCollectionActiveWorkRun =
    runtimeSummaryQuery.data
      ? runtimeSourceCollectionActiveWorkRun ?? undefined
      : summarySourceCollectionActiveWorkRun ?? selectedSourceCollectionSearchExecutionResult?.activeWorkRun;
  const sourceCollectionSummaryStorageArtifacts = sourceCollectionSummary?.storageArtifacts as SourceCollectionStorageArtifacts | undefined;
  const selectedSourceCollectionStorageArtifacts =
    selectedSourceCollectionSearchExecutionResult?.storageArtifacts
    ?? sourceCollectionSummaryStorageArtifacts
    ?? sourceCollectionStorageArtifactsForRun(selectedTeam?.teamId ?? effectiveTeamId, selectedSourceCollectionRunEffectiveId);
  const selectedSourceCollectionStorageOpenPending =
    openSourceCollectionStorageMutation.isPending && openSourceCollectionStorageMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedSourceCollectionStorageOpenResult =
    openSourceCollectionStorageMutation.variables?.teamId === selectedTeam?.teamId ? openSourceCollectionStorageMutation.data : undefined;
  const selectedSourceCollectionStorageOpenError =
    openSourceCollectionStorageMutation.variables?.teamId === selectedTeam?.teamId && openSourceCollectionStorageMutation.error instanceof Error
      ? openSourceCollectionStorageMutation.error
      : null;
  useEffect(() => {
    if (!researchWorkflowTeamSelected || !pageVisible || !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId) {
      return;
    }
    if (requestedSourceCollectionStage) {
      setSourceCollectionStageSyncUntilMs(Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS);
    }
    void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryKey(selectedTeam.teamId, selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeam.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId) });
  }, [
    pageVisible,
    queryClient,
    requestedSourceCollectionStage,
    researchWorkflowTeamSelected,
    selectedSourceCollectionRunEffectiveId,
    selectedTeam?.teamId,
  ]);
  useEffect(() => {
    if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeam.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryKey(selectedTeam.teamId, selectedSourceCollectionRunEffectiveId) });
  }, [
    queryClient,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionSearchAccepted,
    selectedTeam?.teamId,
  ]);
  const openSourceCollectionStorageTarget = (target: SourceCollectionStorageOpenTarget, runIdOverride?: string) => {
    const runId = runIdOverride || selectedSourceCollectionRunEffectiveId;
    if (!selectedTeam?.teamId || !runId) {
      return;
    }
    openSourceCollectionStorageMutation.mutate({
      teamId: selectedTeam.teamId,
      runId,
      target,
    });
  };
  const sourceCollectionRunSummary = sourceCollectionRunStatus?.summary as (DataProcessingStatus["summary"] & {
    searchOpenAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
  }) | undefined;
  const sourceCollectionOpenAssignments = sourceCollectionAssignments.filter((assignment) => ["open", "in_progress", "returned"].includes(assignment.status));
  const sourceCollectionOpenAssignmentCount =
    sourceCollectionRunSummary?.openAssignmentCount
    ?? sourceCollectionOpenAssignments.length;
  const sourceCollectionSearchOpenAssignmentCount =
    sourceCollectionRunSummary?.searchOpenAssignmentCount
    ?? sourceCollectionOpenAssignments.filter((assignment) => SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(assignment.agentRole)).length;
  const sourceCollectionDownstreamOpenAssignmentCount =
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount
    ?? Math.max(0, sourceCollectionOpenAssignmentCount - sourceCollectionSearchOpenAssignmentCount);
  const sourceManifestCandidates = useMemo(
    () => teamWorkflowCandidates.filter((candidate) => candidate.candidateType === "source_manifest"),
    [teamWorkflowCandidates],
  );
  const teamWorkflowCandidatesById = useMemo(() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    teamWorkflowCandidates.forEach((candidate) => {
      mapping.set(candidate.candidateId, candidate);
    });
    return mapping;
  }, [teamWorkflowCandidates]);
  const sourceCollectionRunCandidates = useMemo(
    () => selectedSourceCollectionRunEffectiveId
      ? sourceManifestCandidates.filter((candidate) => sourceCollectionCandidateTrace(candidate).runId === selectedSourceCollectionRunEffectiveId)
      : sourceManifestCandidates,
    [selectedSourceCollectionRunEffectiveId, sourceManifestCandidates],
  );
  const selectedSourceCollectionCandidate = useMemo(
    () => sourceManifestCandidates.find((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId) ?? null,
    [selectedSourceCollectionCandidateId, sourceManifestCandidates],
  );
  const selectedSourceCollectionCandidateTrace = selectedSourceCollectionCandidate
    ? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate)
    : null;
  const selectedSourceCollectionCandidateRunId =
    selectedSourceCollectionCandidateTrace?.runId || selectedSourceCollectionRunEffectiveId;
  const selectedSourceCollectionCandidateStorageArtifacts =
    sourceCollectionStorageArtifactsForRun(selectedTeam?.teamId ?? effectiveTeamId, selectedSourceCollectionCandidateRunId)
    ?? selectedSourceCollectionStorageArtifacts;
  useEffect(() => {
    if (!selectedSourceCollectionCandidateId) {
      return;
    }
    if (!sourceManifestCandidates.some((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId)) {
      setSelectedSourceCollectionCandidateId("");
    }
  }, [selectedSourceCollectionCandidateId, sourceManifestCandidates]);
  const selectSourceCollectionCandidate = (candidate: TeamWorkflowCandidate) => {
    setSelectedSourceCollectionCandidateId(candidate.candidateId);
  };
  const sourceCollectionCandidateCardKeyDown = (
    event: ReactKeyboardEvent<HTMLElement>,
    candidate: TeamWorkflowCandidate,
  ) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    selectSourceCollectionCandidate(candidate);
  };
  const sourceCollectionCandidatesByRecordId = useMemo(() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    sourceCollectionRunCandidates.forEach((candidate) => {
      const trace = sourceCollectionCandidateTrace(candidate);
      if (trace.recordId && !mapping.has(trace.recordId)) {
        mapping.set(trace.recordId, candidate);
      }
    });
    return mapping;
  }, [sourceCollectionRunCandidates]);
  const sourceCollectionRecordProvenances = useMemo(
    () => sourceCollectionRecords.map((record) => sourceCollectionRecordProvenance(record, lang)),
    [lang, sourceCollectionRecords],
  );
  const sourceCollectionRecordSourceCategories = useMemo(
    () => sourceCollectionRecords.map((record) => sourceCollectionRecordSourceCategory(record, lang)),
    [lang, sourceCollectionRecords],
  );
  const sourceCollectionFilteredRecords = useMemo(
    () => sourceCollectionRecords.filter((record) =>
      sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionRecordSourceCategory(record, lang)),
    ),
    [lang, sourceCollectionRecords, sourceCollectionSourceFilter],
  );
  const sourceCollectionRunCandidateSourceCategories = useMemo(
    () => sourceCollectionRunCandidates.map((candidate) => sourceCollectionCandidateSourceCategory(candidate, lang)),
    [lang, sourceCollectionRunCandidates],
  );
  const sourceCollectionFilteredRunCandidates = useMemo(
    () => sourceCollectionRunCandidates.filter((candidate) =>
      sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionCandidateSourceCategory(candidate, lang)),
    ),
    [lang, sourceCollectionRunCandidates, sourceCollectionSourceFilter],
  );
  const sourceCollectionSummaryCounts = sourceCollectionSummary?.summary ?? {};
  const sourceCollectionRawRecordCount =
    Number(
      sourceCollectionRecordsQuery.data?.summary?.recordCount
      ?? sourceCollectionSummaryCounts.recordCount
      ?? sourceCollectionRunSummary?.recordCount
      ?? selectedSourceCollectionRun?.summary?.recordCount
      ?? sourceCollectionRecords.length,
    ) || 0;
  const sourceCollectionRecordClickableSourceCount = sourceCollectionRecordProvenances.filter((item) => item.href).length;
  const sourceCollectionRecordLocalFileCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "file").length;
  const sourceCollectionRecordMissingSourceCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "missing").length;
  const sourceCollectionRunCandidateCount = sourceCollectionRunCandidates.length;
  const sourceCollectionRecordFilterCounts = sourceCollectionFilterCounts(sourceCollectionRecordSourceCategories);
  const sourceCollectionCandidateFilterCounts = sourceCollectionFilterCounts(sourceCollectionRunCandidateSourceCategories);
  const sourceCollectionReviewableRunCandidates = useMemo(
    () => sourceCollectionRunCandidates.filter(
      (candidate) => candidate.sourceVersionFamily?.state !== "superseded",
    ),
    [sourceCollectionRunCandidates],
  );
  const sourceCollectionRunReviewableCandidateCount = sourceCollectionReviewableRunCandidates.length;
  const sourceCollectionRunAssessedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).assessed,
  ).length;
  const sourceCollectionRunApprovedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).approved,
  ).length;
  const sourceCollectionRunNeedsRevisionCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).needsRevision,
  ).length;
  const sourceCollectionEvidenceLedgerSummaries = useMemo(
    () => sourceCollectionRunCandidates
      .map((candidate) => sourceCollectionEvidenceLedgerSummary(candidate))
      .filter((summary): summary is SourceCollectionEvidenceLedgerSummary => Boolean(summary)),
    [sourceCollectionRunCandidates],
  );
  const sourceCollectionEvidenceReadyCandidateCount = sourceCollectionEvidenceLedgerSummaries.filter((summary) => !summary.missingAnchor).length;
  const sourceCollectionMissingEvidenceAnchorCount = sourceCollectionEvidenceLedgerSummaries.filter((summary) => summary.missingAnchor).length;
  const sourceCollectionCollectedCount = sourceCollectionRawRecordCount;
  const sourceCollectionRunSummaryHasRecordCount = typeof sourceCollectionRunSummary?.recordCount === "number";
  const sourceCollectionSummaryHasRecordCount = typeof sourceCollectionSummaryCounts.recordCount === "number";
  const sourceCollectionRunSummaryHasAssignmentCounts = [
    sourceCollectionRunSummary?.openAssignmentCount,
    sourceCollectionRunSummary?.searchOpenAssignmentCount,
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount,
  ].some((value) => typeof value === "number");
  const sourceCollectionCandidateListDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateListEnabled
    && sourceCollectionNeedsCandidateList
    && !teamWorkflowCandidatesQuery.data
    && (teamWorkflowCandidatesQuery.isPending || teamWorkflowCandidatesQuery.isFetching)
  );
  const sourceCollectionRecordsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionRecordsQuery.data
    && !sourceCollectionSummaryHasRecordCount
    && !sourceCollectionRunSummaryHasRecordCount
    && (
      sourceCollectionRecordsQuery.isPending
      || sourceCollectionRunStatusQuery.isPending
    ),
  );
  const sourceCollectionAssignmentsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionAssignmentsQuery.data
    && !sourceCollectionRunSummaryHasAssignmentCounts
    && (sourceCollectionAssignmentsQuery.isPending || sourceCollectionRunStatusQuery.isPending),
  );
  const sourceCollectionCollectionProjection = sourceCollectionStageCardById.get("finding") ?? null;
  const sourceCollectionExtractionProjection = sourceCollectionStageCardById.get("extraction") ?? null;
  const sourceCollectionCandidateProjection = sourceCollectionExtractionProjection;
  const sourceCollectionScreeningProjection = sourceCollectionExtractionProjection;
  const sourceCollectionGraphProjection = sourceCollectionStageCardById.get("relations") ?? null;
  const sourceCollectionMemoryProjection = sourceCollectionStageCardById.get("ingestion") ?? null;
  const sourceCollectionExcludedSourceCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionStageRound?.sourceCollectionStageCardSummary?.excludedSourceCount),
    sourceCollectionNonNegativeCount(sourceCollectionSummaryCounts.excludedSourceCount),
    sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "excluded", 0),
    sourceCollectionNonNegativeCount(sourceCollectionCandidateProjection?.latestTask?.closureSummary?.excludedSourceCount),
  );
  const sourceCollectionStageSummaryCandidateCount = Number(
    sourceCollectionStageRound?.sourceCollectionStageCardSummary?.sourceCandidateCount
    ?? sourceCollectionSummaryCounts.sourceCandidateCount,
  );
  const sourceCollectionCandidateProjectionFallbackCount = Number.isFinite(sourceCollectionStageSummaryCandidateCount)
    ? Math.max(sourceCollectionRunCandidateCount, Math.max(0, sourceCollectionStageSummaryCandidateCount))
    : sourceCollectionRunCandidateCount;
  const sourceCollectionProjectedCollectedCount = Math.max(
    sourceCollectionCollectedCount,
    sourceCollectionStageProjectionCount(
      sourceCollectionCollectionProjection,
      "artifact",
      sourceCollectionCollectedCount,
    ),
  );
  const sourceCollectionProjectedCandidateCount = sourceCollectionStageProjectionCount(
    sourceCollectionCandidateProjection,
    "artifact",
    sourceCollectionCandidateProjectionFallbackCount,
  );
  const sourceCollectionProjectedAssessedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunAssessedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "artifact",
      sourceCollectionRunAssessedCount,
    );
  const sourceCollectionProjectedApprovedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunApprovedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "output",
      sourceCollectionRunApprovedCount,
    );
  const sourceCollectionDisplayedCandidateCount = Math.max(sourceCollectionRunCandidateCount, sourceCollectionProjectedCandidateCount);
  const sourceCollectionQueryCount =
    sourceCollectionSearchPlanRef?.queryCount
    ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount
    ?? sourceCollectionAssignments.reduce((total, assignment) => total + (assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0), 0);
  const sourceCollectionPrimaryDataLoading = Boolean(
    researchWorkflowTeamSelected
    && (
      sourceCollectionCandidateListDataLoading
      || (
        sourceCollectionDisplayedCandidateCount <= 0
        && (
          sourceCollectionRecordsDataLoading
          || sourceCollectionAssignmentsDataLoading
          || (sourceCollectionRunsQuery.isPending && !sourceCollectionRunsQuery.data)
          || (
            selectedSourceCollectionRunEffectiveId
            && sourceCollectionSummaryQuery.isPending
            && sourceCollectionWorkspaceSelected
            && !sourceCollectionSummaryQuery.data
          )
        )
      )
    ),
  );
  const sourceCollectionSourceQualityLoading = Boolean(
    researchWorkflowTeamSelected
    && teamWorkflowSourceQualityEnabled
    && !teamWorkflowSourceQualityStatus
    && (teamWorkflowSourceQualityStatusQuery.isPending || teamWorkflowSourceQualityStatusQuery.isFetching)
  );
  const sourceCollectionGraphDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowGraphEnabled
    && teamWorkflowCandidateGraphQuery.isPending && !teamWorkflowCandidateGraphQuery.data
  );
  const sourceCollectionKnowledgeIngestionDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionEnabled
    && teamWorkflowKnowledgeIngestionStatusQuery.isPending && !teamWorkflowKnowledgeIngestionStatusQuery.data
  );
  const sourceCollectionActionInitialDataPending = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      sourceCollectionRecordsDataLoading
      || sourceCollectionAssignmentsDataLoading
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionGraphDataLoading
      || sourceCollectionKnowledgeIngestionDataLoading
    ),
  );
  const sourceCollectionActionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      (sourceCollectionRecordsQuery.error && !sourceCollectionRecordsQuery.data && !sourceCollectionSummaryHasRecordCount && !sourceCollectionRunSummaryHasRecordCount)
      || (sourceCollectionAssignmentsQuery.error && !sourceCollectionAssignmentsQuery.data && !sourceCollectionRunSummaryHasAssignmentCounts)
      || (sourceCollectionSummaryQuery.error && sourceCollectionWorkspaceSelected && !sourceCollectionSummaryQuery.data)
    ),
  );
  const sourceCollectionSourceQualityDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowSourceQualityStatusQuery.error
    && !teamWorkflowSourceQualityStatusQuery.data
  );
  const sourceCollectionGraphDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateGraphQuery.error
    && !teamWorkflowCandidateGraphQuery.data
  );
  const sourceCollectionKnowledgeIngestionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionStatusQuery.error
    && !teamWorkflowKnowledgeIngestionStatusQuery.data
  );
  const sourceCollectionScreeningDataLoading = sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading;
  const sourceCollectionLoadingText = lang === "zh" ? "加载中" : "loading";
  const sourceCollectionDataSyncText = lang === "zh" ? "同步中" : "syncing";
  const sourceCollectionLoadingSummary = lang === "zh" ? "正在读取资料提炼结果" : "Loading extraction results";
  const sourceCollectionActionLoadingReason = lang === "zh" ? "正在读取当前批次数据" : "Loading current batch data";
  const sourceCollectionActionErrorReason = lang === "zh" ? "当前批次数据读取失败，请刷新后重试" : "Current batch data failed to load. Refresh and retry.";
  const sourceCollectionActionNoRunReason = lang === "zh" ? "还没有可执行的搜集批次" : "No collection run is available yet.";
  const sourceCollectionActionNoInputReason = lang === "zh" ? "当前阶段还没有可执行输入" : "This stage has no runnable input yet.";
  const sourceCollectionActionBusyReason = lang === "zh" ? "已有任务正在执行" : "A task is already running.";
  const sourceCollectionActionReady: SourceCollectionActionReadiness = { disabled: false, loading: false, reason: "" };
  const sourceCollectionActionReadiness = (
    disabled: boolean,
    reason: string,
    loading = false,
  ): SourceCollectionActionReadiness => disabled
    ? { disabled: true, loading, reason }
    : sourceCollectionActionReady;
  const sourceCollectionActionDisabledTitle = (readiness: SourceCollectionActionReadiness, fallback: string) =>
    readiness.disabled && readiness.reason ? readiness.reason : fallback;
  const sourceCollectionCountText = (loading: boolean, value: number) => sourceCollectionStableCountText({
    loading,
    value,
    lang,
    loadingText: sourceCollectionLoadingText,
    syncingText: sourceCollectionDataSyncText,
  });
  const sourceCollectionCountWithUnit = (loading: boolean, value: number, zhUnit: string, enUnit = "") => sourceCollectionStableCountText({
    loading,
    value,
    lang,
    zhUnit,
    enUnit,
    loadingText: sourceCollectionLoadingText,
    syncingText: sourceCollectionDataSyncText,
  });
  const sourceCollectionCollectedCountText = sourceCollectionCountText(sourceCollectionRecordsDataLoading, sourceCollectionCollectedCount);
  const sourceCollectionProjectedCollectedCountText = sourceCollectionCountText(sourceCollectionRecordsDataLoading, sourceCollectionProjectedCollectedCount);
  const sourceCollectionSearchOpenAssignmentCountText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionSearchOpenAssignmentCount);
  const sourceCollectionDownstreamOpenAssignmentCountText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionDownstreamOpenAssignmentCount);
  const sourceCollectionQueryDataLoading = Boolean(
    sourceCollectionAssignmentsDataLoading
    && sourceCollectionSearchPlanRef?.queryCount == null
    && selectedTeamStartSourceCollectionResult?.searchPlan.queryCount == null
    && sourceCollectionAssignments.length <= 0,
  );
  const sourceCollectionQueryCountText = sourceCollectionQueryDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionQueryCount);
  const sourceCollectionCollectedCountLabel = sourceCollectionCountWithUnit(sourceCollectionRecordsDataLoading, sourceCollectionCollectedCount, "条", "raw records");
  const sourceCollectionProjectedCollectedCountLabel = sourceCollectionCountWithUnit(sourceCollectionRecordsDataLoading, sourceCollectionProjectedCollectedCount, "条", "raw records");
  const sourceCollectionSearchOpenAssignmentCountLabel = sourceCollectionCountWithUnit(sourceCollectionAssignmentsDataLoading, sourceCollectionSearchOpenAssignmentCount, "项");
  const sourceCollectionDownstreamOpenAssignmentCountLabel = sourceCollectionCountWithUnit(sourceCollectionAssignmentsDataLoading, sourceCollectionDownstreamOpenAssignmentCount, "项");
  const sourceCollectionQueryCountLabel = sourceCollectionCountWithUnit(sourceCollectionQueryDataLoading, sourceCollectionQueryCount, "个");
  const sourceCollectionCollectedRunSummaryText = sourceCollectionRecordsDataLoading
    ? sourceCollectionLoadingText
    : lang === "zh"
    ? `${sourceCollectionCollectedCount} 条资料`
    : `${sourceCollectionCollectedCount} records`;
  const sourceCollectionAssignmentRunSummaryText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : lang === "zh"
    ? `${sourceCollectionAssignments.length} 个任务`
    : `${sourceCollectionAssignments.length} assignments`;
  const sourceCollectionDisplayedCandidateCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, sourceCollectionDisplayedCandidateCount);
  const sourceCollectionProjectedCandidateCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, sourceCollectionProjectedCandidateCount);
  const sourceCollectionCoverageBoundCandidateCount = sourceCollectionBoundCountToCurrentCoverage(
    sourceCollectionCandidateProjection,
    sourceCollectionProjectedCandidateCount,
  );
  const sourceCollectionCurrentCandidateCount = sourceCollectionRunReviewableCandidateCount > 0
    ? Math.min(sourceCollectionCoverageBoundCandidateCount, sourceCollectionRunReviewableCandidateCount)
    : sourceCollectionCoverageBoundCandidateCount;
  const sourceCollectionCurrentCandidateCountText = sourceCollectionCountText(
    sourceCollectionPrimaryDataLoading,
    sourceCollectionCurrentCandidateCount,
  );
  const sourceCollectionProjectedCandidateCountLabel = sourceCollectionCountWithUnit(sourceCollectionPrimaryDataLoading, sourceCollectionProjectedCandidateCount, "条候选资料", "candidate sources");
  const sourceCollectionProjectedAssessedCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionProjectedAssessedCount);
  const sourceCollectionProjectedApprovedCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionProjectedApprovedCount);
  const sourceCollectionDisplayedCandidateFilterCounts = useMemo(() => {
    if (sourceCollectionDisplayedCandidateCount <= sourceCollectionRunCandidateCount) {
      return sourceCollectionCandidateFilterCounts;
    }
    return {
      ...sourceCollectionCandidateFilterCounts,
      all: sourceCollectionDisplayedCandidateCount,
    };
  }, [
    sourceCollectionCandidateFilterCounts,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionRunCandidateCount,
  ]);
  const sourceCollectionRunPendingScreeningCount = Math.max(
    0,
    sourceCollectionRunCandidateCount > 0
      ? sourceCollectionRunReviewableCandidateCount - sourceCollectionRunAssessedCount
      : sourceCollectionProjectedCandidateCount - sourceCollectionProjectedAssessedCount,
  );
  const sourceCollectionRunPendingScreeningCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionRunPendingScreeningCount);
  const sourceCollectionPendingCandidateImportCount = Math.max(0, sourceCollectionRawRecordCount - sourceCollectionDisplayedCandidateCount);
  const sourceCollectionExtractionRecoveryCoverage = sourceCollectionCandidateProjection?.currentCoverageSummary?.applicable
    ? sourceCollectionCandidateProjection.currentCoverageSummary
    : sourceCollectionCandidateProjection?.latestTask?.coverageSummary;
  const sourceCollectionExtractionRecoveryClosure = sourceCollectionCandidateProjection?.latestTask?.closureSummary;
  const sourceCollectionExtractionSourceVerificationCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryClosure?.blockedCount),
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryCoverage?.blocked),
  );
  const sourceCollectionUnverifiableCandidateIds = useMemo(() => {
    const blockedCount = sourceCollectionExtractionSourceVerificationCount;
    if (blockedCount <= 0) {
      return [];
    }
    return sourceCollectionReviewableRunCandidates
      .filter((candidate) => {
        const quality = sourceCollectionCandidateQualityState(candidate);
        const evidence = sourceCollectionEvidenceLedgerSummary(candidate);
        return quality.needsRevision && evidence?.missingAnchor !== true;
      })
      .map((candidate) => String(candidate.candidateId || "").trim())
      .filter(Boolean)
      .slice(0, blockedCount);
  }, [
    sourceCollectionExtractionSourceVerificationCount,
    sourceCollectionReviewableRunCandidates,
  ]);
  const sourceCollectionExtractionMissingEvidenceAnchorCount = sourceCollectionBoundCountToCurrentCoverage(
    sourceCollectionCandidateProjection,
    sourceCollectionCandidateProjection?.latestTask?.materializedContentExtraction?.missingEvidenceAnchorCount,
  );
  const sourceCollectionExtractionAgentMaterialCount = sourceCollectionMaterialGapCount({
    hasCurrentCandidates: Boolean(teamWorkflowCandidatesQuery.data),
    needsRevisionCount: sourceCollectionRunNeedsRevisionCount,
    missingEvidenceAnchorCount: sourceCollectionExtractionMissingEvidenceAnchorCount,
    taskBlockedCount: sourceCollectionExtractionSourceVerificationCount,
    projectedPendingCount: sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "pending", 0),
  });
  const sourceCollectionExtractionNeedsAgentMaterial = sourceCollectionExtractionAgentMaterialCount > 0;
  const sourceCollectionExtractionRecoveryMissingCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryCoverage?.missing),
    sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "pending", 0),
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.pendingRecordCount),
  );
  const sourceCollectionExtractionExcludedRecoveryState = deriveSourceCollectionExcludedRecoveryState({
    lang,
    excludedCount: Math.max(
      sourceCollectionExcludedSourceCount,
      sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryClosure?.excludedSourceCount),
      sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "excluded", 0),
    ),
    missingCount: sourceCollectionExtractionRecoveryMissingCount,
    importFailedCount: sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.failedCount),
    importPendingRecordCount: Math.max(
      sourceCollectionPendingCandidateImportCount,
      sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.pendingRecordCount),
    ),
  });
  const sourceCollectionExtractionCanProceedAfterExclusions = Boolean(
    sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
    && sourceCollectionProjectedApprovedCount > 0
    && sourceCollectionRunPendingScreeningCount <= 0,
  );
  const sourceCollectionExtractionProceedableSummary = lang === "zh"
    ? `${sourceCollectionProjectedApprovedCount} 条可进入关系整理；剩余 ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} 条已排除，可查看原因或补充新来源。`
    : `${sourceCollectionProjectedApprovedCount} ready for relation mapping; ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} excluded sources can be inspected or replaced.`;

  const sourceCollectionApprovedCount =
    teamWorkflowSourceQualityStatus?.summary.approvedSourceCandidateCount
    ?? sourceCollectionSummaryCounts.approvedSourceCandidateCount
    ?? 0;
  const sourceCollectionStageFocusLabel = !selectedSourceCollectionRun
    ? (lang === "zh" ? "尚未启动" : "not started")
    : sourceCollectionSearchOpenAssignmentCount > 0
      ? (lang === "zh" ? "继续搜索" : "continue search")
      : sourceCollectionDownstreamOpenAssignmentCount > 0
        ? (lang === "zh" ? "继续提炼" : "continue extraction")
      : sourceCollectionRunPendingScreeningCount > 0
        ? (lang === "zh" ? "继续审查" : "continue review")
        : sourceCollectionDisplayedCandidateCount > 0
          ? (lang === "zh" ? "准备实验" : "plan experiment")
          : (lang === "zh" ? "等待结果回写" : "waiting for writeback");
  const sourceCollectionRunStatusValue = String(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "").toLowerCase();
  const sourceCollectionAcceptedBackgroundActive = Boolean(
    selectedSourceCollectionSearchAccepted
    && selectedSourceCollectionActiveWorkRun
    && ["running", "queued"].includes(String(selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const canRecordSourceCollectionOutput = Boolean(
    selectedTeam?.teamId
    && selectedSourceCollectionRunEffectiveId
    && (sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId)
    && sourceCollectionOutputHasRecord
    && !selectedTeamRecordSourceCollectionOutputPending,
  );
  const canExecuteSourceCollectionSearch = Boolean(
    selectedTeam?.teamId
    && selectedSourceCollectionRunEffectiveId
    && !sourceCollectionAssignmentsDataLoading
    && !sourceCollectionActionDataError
    && sourceCollectionSearchOpenAssignmentCount > 0
    && !selectedTeamExecuteSourceCollectionSearchPending
    && !sourceCollectionAcceptedBackgroundActive,
  );
  const selectedTeamBuildCandidateGraphPending =
    buildCandidateGraphMutation.isPending && buildCandidateGraphMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamBuildCandidateGraphError =
    buildCandidateGraphMutation.variables?.teamId === selectedTeam?.teamId && buildCandidateGraphMutation.error instanceof Error
      ? buildCandidateGraphMutation.error
      : null;
  const selectedTeamKnowledgePrecheckPending =
    runKnowledgeIngestionPrecheckMutation.isPending && runKnowledgeIngestionPrecheckMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamKnowledgePrecheckError =
    runKnowledgeIngestionPrecheckMutation.variables?.teamId === selectedTeam?.teamId
    && runKnowledgeIngestionPrecheckMutation.error instanceof Error
      ? runKnowledgeIngestionPrecheckMutation.error
      : null;
  const selectedTeamKnowledgeIngestionActiveWorkRun =
    teamWorkflowKnowledgeIngestionStatusQuery.data?.activeWorkRun ?? null;
  const selectedTeamKnowledgeIngestionLatestWorkRun =
    teamWorkflowKnowledgeIngestionStatusQuery.data?.latestWorkRun ?? null;
  const selectedTeamKnowledgeCollectionWorkRun =
    selectedTeamKnowledgeIngestionActiveWorkRun ?? selectedTeamKnowledgeIngestionLatestWorkRun ?? null;
  const selectedTeamKnowledgeCollectionSourceRunId = String(selectedTeamKnowledgeCollectionWorkRun?.sourceRunId || "");
  const selectedTeamKnowledgeCollectionMatchesSelectedRun =
    !selectedTeamKnowledgeCollectionSourceRunId
    || !selectedSourceCollectionRunEffectiveId
    || selectedTeamKnowledgeCollectionSourceRunId === selectedSourceCollectionRunEffectiveId;
  const selectedTeamKnowledgeCollectionWorkRunStatus = String(selectedTeamKnowledgeCollectionWorkRun?.status || "").toLowerCase();
  const selectedTeamKnowledgeCollectionFlowStatus = String(
    selectedTeamKnowledgeCollectionWorkRun?.flowVisualization?.status || "",
  ).toLowerCase();
  const selectedTeamKnowledgeCollectionCompleted =
    selectedTeamKnowledgeCollectionWorkRunStatus === "completed"
    || selectedTeamKnowledgeCollectionFlowStatus === "completed";
  const selectedTeamKnowledgeCollectionCompletedForSelectedRun =
    selectedTeamKnowledgeCollectionCompleted && selectedTeamKnowledgeCollectionMatchesSelectedRun;
  const selectedTeamKnowledgeCollectionIngestPending =
    (runKnowledgeCollectionCompletionMutation.isPending && runKnowledgeCollectionCompletionMutation.variables?.teamId === selectedTeam?.teamId)
    || Boolean(selectedTeamKnowledgeIngestionActiveWorkRun);
  const selectedTeamKnowledgeCollectionIngestError =
    runKnowledgeCollectionCompletionMutation.variables?.teamId === selectedTeam?.teamId
    && !selectedTeamKnowledgeCollectionCompleted
    && runKnowledgeCollectionCompletionMutation.error instanceof Error
      ? runKnowledgeCollectionCompletionMutation.error
      : null;
  const selectedTeamKnowledgeCollectionIngestResult =
    runKnowledgeCollectionCompletionMutation.variables?.teamId === selectedTeam?.teamId
      ? runKnowledgeCollectionCompletionMutation.data
      : null;
  const selectedTeamPlanPaperNoteChunksPending =
    planPaperNoteChunksMutation.isPending && planPaperNoteChunksMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamPlanPaperNoteChunksError =
    planPaperNoteChunksMutation.variables?.teamId === selectedTeam?.teamId && planPaperNoteChunksMutation.error instanceof Error
      ? planPaperNoteChunksMutation.error
      : null;
  const selectedTeamAssessSourceQualityPending =
    assessSourceQualityMutation.isPending && assessSourceQualityMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamAssessSourceQualityError =
    assessSourceQualityMutation.variables?.teamId === selectedTeam?.teamId && assessSourceQualityMutation.error instanceof Error
      ? assessSourceQualityMutation.error
      : null;
  const selectedTeamAssessSourceQualityBatchPending =
    assessSourceQualityBatchMutation.isPending && assessSourceQualityBatchMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamAssessSourceQualityBatchError =
    assessSourceQualityBatchMutation.variables?.teamId === selectedTeam?.teamId && assessSourceQualityBatchMutation.error instanceof Error
      ? assessSourceQualityBatchMutation.error
      : null;
  const selectedTeamSourceQualityPending = selectedTeamAssessSourceQualityPending || selectedTeamAssessSourceQualityBatchPending;
  const selectedTeamSourceQualityError = selectedTeamAssessSourceQualityError || selectedTeamAssessSourceQualityBatchError;
  const selectedTeamSourceQualityBatchResult =
    assessSourceQualityBatchMutation.isSuccess
    && assessSourceQualityBatchMutation.variables?.teamId === selectedTeam?.teamId
    && assessSourceQualityBatchMutation.data
      ? assessSourceQualityBatchMutation.data
      : null;
  const sourceCollectionQualityBatchFeedback = selectedTeamSourceQualityBatchResult
    ? (() => {
      const summary = selectedTeamSourceQualityBatchResult.summary;
      const approved = Number(summary?.approvedCandidateCount || 0);
      const needsRevision = Number(summary?.needsRevisionCandidateCount || 0);
      const rejected = Number(summary?.rejectedCandidateCount || 0);
      const assessed = Number(summary?.assessedCandidateCount || 0);
      const skipped = Number(summary?.skippedCandidateCount || 0);
      if (lang === "zh") {
        const stillBlocked = needsRevision > 0
          ? " 仍为「待补」的条目需要先补充全文/DOI/证据锚点，再审查；只点审查不会自动通过。"
          : "";
        return `质量审查完成：通过 ${approved} · 待补 ${needsRevision} · 排除 ${rejected}（本批评估 ${assessed}${skipped ? `，跳过 ${skipped}` : ""}）。${stillBlocked}`;
      }
      const stillBlocked = needsRevision > 0
        ? " Needs-revision items stay blocked until materials are fixed; review alone does not auto-approve."
        : "";
      return `Quality review finished: approved ${approved} · needs revision ${needsRevision} · rejected ${rejected} (assessed ${assessed}${skipped ? `, skipped ${skipped}` : ""}).${stillBlocked}`;
    })()
    : null;
  const sourceCollectionAcceptedBackgroundFailed = Boolean(
    selectedSourceCollectionActiveWorkRun
    && ["failed", "blocked"].includes(String(selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const sourceCollectionOperationFailed = Boolean(
    sourceCollectionRunStatusValue === "failed"
    || sourceCollectionRunStatusValue === "blocked"
    || sourceCollectionAcceptedBackgroundFailed
    || selectedTeamStartResearchStageError
    || selectedTeamStartSourceCollectionError
    || selectedTeamExecuteSourceCollectionSearchError
    || selectedTeamExtractSourceCollectionCandidatesError
    || selectedTeamRecordSourceCollectionOutputError
    || selectedTeamSourceQualityError
    || selectedTeamBuildCandidateGraphError
    || selectedTeamKnowledgePrecheckError
    || selectedTeamKnowledgeCollectionIngestError
    || selectedTeamStartSourceCollectionStageTaskError
  );
  const sourceCollectionDisplayState = deriveSourceCollectionDisplayState({
    lang,
    hasRun: Boolean(selectedSourceCollectionRun),
    startPending: selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionPending || selectedTeamStartSourceCollectionStageTaskPending,
    searchPending: selectedTeamExecuteSourceCollectionSearchPending,
    backgroundActive: sourceCollectionAcceptedBackgroundActive,
    recordOutputPending: selectedTeamRecordSourceCollectionOutputPending,
    extractionPending: selectedTeamExtractSourceCollectionCandidatesPending,
    sourceQualityPending: selectedTeamSourceQualityPending,
    graphPending: selectedTeamBuildCandidateGraphPending,
    knowledgeIngestionPending: selectedTeamKnowledgePrecheckPending || selectedTeamKnowledgeCollectionIngestPending,
    failed: sourceCollectionOperationFailed,
    searchOpenAssignmentCount: sourceCollectionSearchOpenAssignmentCount,
    downstreamOpenAssignmentCount: sourceCollectionDownstreamOpenAssignmentCount,
    pendingScreeningCount: sourceCollectionRunPendingScreeningCount,
    rawRecordCount: sourceCollectionRawRecordCount,
    candidateCount: sourceCollectionDisplayedCandidateCount,
    activeWorkSummary: workRunString(selectedSourceCollectionActiveWorkRun, "currentTask")
      || workRunString(selectedSourceCollectionActiveWorkRun, "summary"),
  });
  const candidateGraphNodeCount = teamWorkflowCandidateGraph?.summary.nodeCount ?? sourceCollectionSummaryCounts.graphNodeCount ?? 0;
  const candidateGraphEdgeCount = teamWorkflowCandidateGraph?.summary.edgeCount ?? 0;
  const knowledgeStewardPackCount = teamWorkflowKnowledgeIngestionStatus?.summary.stewardPackCandidateCount ?? sourceCollectionSummaryCounts.stewardPackCount ?? 0;
  const knowledgePendingReviewCount = teamWorkflowKnowledgeIngestionStatus?.summary.pendingKnowledgeReviewCandidateCount ?? 0;
  const formalKnowledgeItemCount =
    teamWorkflowKnowledgeIngestionStatus?.summary.formalKnowledgeItemCount
    ?? sourceCollectionSummaryCounts.formalKnowledgeSyncCount
    ?? 0;
  const sourceCollectionProjectedGraphNodeCount = sourceCollectionStageProjectionCount(
    sourceCollectionGraphProjection,
    "artifact",
    candidateGraphNodeCount,
  );
  const sourceCollectionProjectedGraphEdgeCount = sourceCollectionStageProjectionCount(
    sourceCollectionGraphProjection,
    "output",
    candidateGraphEdgeCount,
  );
  const sourceCollectionProjectedStewardPackCount = sourceCollectionStageProjectionCount(
    sourceCollectionMemoryProjection,
    "artifact",
    knowledgeStewardPackCount,
  );
  const sourceCollectionProjectedFormalKnowledgeCount = sourceCollectionStageProjectionCount(
    sourceCollectionMemoryProjection,
    "output",
    formalKnowledgeItemCount,
  );
  const sourceCollectionDefaultKnowledgeBaseId =
    teamWorkflowKnowledgeIngestionStatus?.knowledgeBases[0]?.scopedKnowledgeBaseId
    ?? teamWorkflowKnowledgeIngestionStatus?.knowledgeBases[0]?.knowledgeBaseId
    ?? "";
  const sourceCollectionPrecheckCandidateCount = Math.max(sourceCollectionApprovedCount, sourceCollectionRunApprovedCount);
  const sourceCollectionIngestCandidateCount = Math.max(sourceCollectionPrecheckCandidateCount, sourceCollectionDisplayedCandidateCount);
  const sourceCollectionCanBuildGraph = sourceCollectionRunApprovedCount > 0 || sourceCollectionDisplayedCandidateCount > 0;
  const sourceCollectionSearchActionReadiness = sourceCollectionActionReadiness(
    !canExecuteSourceCollectionSearch,
    !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionAssignmentsDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionAssignmentsDataLoading,
  );
  const sourceCollectionCandidateExtractionActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || !selectedSourceCollectionRunEffectiveId
      || sourceCollectionRecordsDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionRawRecordCount <= 0
      || selectedTeamExtractSourceCollectionCandidatesPending,
    !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionRecordsDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamExtractSourceCollectionCandidatesPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionRecordsDataLoading,
  );
  const sourceCollectionScreeningActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionDisplayedCandidateCount <= 0
      || selectedTeamSourceQualityPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamSourceQualityPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading,
  );
  const sourceCollectionGraphActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionGraphDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionGraphDataError
      || !sourceCollectionCanBuildGraph
      || selectedTeamBuildCandidateGraphPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionGraphDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionGraphDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamBuildCandidateGraphPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionGraphDataLoading,
  );
  const sourceCollectionMemoryActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionKnowledgeIngestionDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionKnowledgeIngestionDataError
      || sourceCollectionIngestCandidateCount <= 0
      || selectedTeamKnowledgeCollectionIngestPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError || sourceCollectionKnowledgeIngestionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamKnowledgeCollectionIngestPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading,
  );
  const sourceCollectionCompletionActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || !sourceCollectionActionRunId
      || sourceCollectionActionInitialDataPending
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionGraphDataError
      || sourceCollectionKnowledgeIngestionDataError
      || (sourceCollectionIngestCandidateCount <= 0 && sourceCollectionRawRecordCount <= 0 && sourceCollectionSearchOpenAssignmentCount <= 0)
      || selectedTeamKnowledgeCollectionIngestPending,
    !selectedTeam?.teamId || !sourceCollectionActionRunId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionActionInitialDataPending
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError || sourceCollectionGraphDataError || sourceCollectionKnowledgeIngestionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamKnowledgeCollectionIngestPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionActionInitialDataPending,
  );
  const sourceCollectionLoopStartsNewRun = !selectedSourceCollectionRun || selectedTeamKnowledgeCollectionCompletedForSelectedRun;
  const sourceCollectionLoopStartReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || selectedTeamStartSourceCollectionPending
      || selectedTeamKnowledgeCollectionIngestPending
      || !sourceCollectionCanStart,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : selectedTeamStartSourceCollectionPending || selectedTeamKnowledgeCollectionIngestPending
        ? sourceCollectionActionBusyReason
        : sourceCollectionActionNoInputReason,
  );
  const sourceCollectionLoopActionReadiness = sourceCollectionLoopStartsNewRun
    ? sourceCollectionLoopStartReadiness
    : sourceCollectionCompletionActionReadiness;
  const sourceCollectionMemoryActionDisabled = sourceCollectionMemoryActionReadiness.disabled;
  const sourceCollectionMemoryActionLabel = sourceCollectionMemoryActionDisabled && sourceCollectionMemoryActionReadiness.loading
    ? (lang === "zh" ? "读取中" : "Loading")
    : selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "通知入库 Agent 中" : "Notifying ingestion Agent")
    : sourceCollectionPrecheckCandidateCount > 0
      ? (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "提炼后通知入库 Agent" : "Extract and notify ingestion Agent")
        : (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent");
  const sourceCollectionCompletionActionDisabled = sourceCollectionCompletionActionReadiness.disabled;
  const sourceCollectionCompletionActionLabel = selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "一键完成中" : "Completing")
    : (lang === "zh" ? "一键完成知识搜集" : "Complete knowledge collection");
  const sourceCollectionLoopActionDisabled = sourceCollectionLoopActionReadiness.disabled;
  const sourceCollectionLoopActionLabel = selectedTeamStartSourceCollectionPending || selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "闭环执行中" : "Loop running")
    : sourceCollectionLoopStartsNewRun
      ? selectedTeamKnowledgeCollectionCompletedForSelectedRun && selectedSourceCollectionRun
        ? (lang === "zh" ? "开始下一轮闭环" : "Start next loop")
        : (lang === "zh" ? "开始第一轮闭环" : "Start first loop")
      : sourceCollectionOperationFailed
        ? (lang === "zh" ? "重试本轮闭环" : "Retry this loop")
        : (lang === "zh" ? "继续本轮闭环" : "Continue this loop");
  const sourceCollectionGraphActionDisabled = sourceCollectionGraphActionReadiness.disabled;
  const sourceCollectionGraphActionLabel = selectedTeamBuildCandidateGraphPending
    ? (lang === "zh" ? "Agent 生成中" : "Agent building")
    : sourceCollectionRunApprovedCount > 0
      ? (lang === "zh" ? "Agent 生成关系图" : "Agent build map")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "审查并生成关系图" : "Review and build map")
        : (lang === "zh" ? "Agent 生成关系图" : "Agent build map");
  const sourceCollectionScreeningDisabled = sourceCollectionScreeningActionReadiness.disabled;
  const sourceCollectionScreeningForceRescreen = sourceCollectionRunPendingScreeningCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
  // Quality review only (re-score). Do not imply "re-extract" — that confuses 待补 users.
  const sourceCollectionScreeningButtonText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "质量审查中" : "Reviewing quality")
    : sourceCollectionRunPendingScreeningCount > 0
      ? (lang === "zh" ? "Agent 质量审查" : "Agent quality review")
      : sourceCollectionScreeningForceRescreen
        ? (lang === "zh" ? "重新质量审查" : "Re-run quality review")
        : (lang === "zh" ? "Agent 质量审查" : "Agent quality review");
  const sourceCollectionScreeningButtonTitle = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "资料提炼 Agent 正在按现有材料重新打分" : "Source Extractor is re-scoring with current materials")
    : sourceCollectionScreeningForceRescreen
      ? (lang === "zh"
        ? "仅重新质量打分，不会自动补全文/DOI/证据锚点。列表「待补资料」需先补充材料再审查，否则结果仍可能是待补。"
        : "Re-scores only; does not auto-fill full text/DOI/anchors. Repair needs-revision sources first or they stay blocked.")
      : (lang === "zh"
        ? "对尚未审查的候选做来源质量打分（通过 / 待补 / 排除）。"
        : "Score pending candidates (approved / needs revision / rejected).");
  const sourceCollectionScreeningStatusText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "进行中" : "running")
    : sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingText
    : sourceCollectionRunPendingScreeningCount > 0
      ? `${sourceCollectionRunPendingScreeningCountText} ${lang === "zh" ? "待质量审查" : "pending quality review"}`
      : sourceCollectionExtractionNeedsAgentMaterial
        ? (lang === "zh" ? "有待补资料：先补材料再审查" : "needs material first")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "已审查" : "done")
        : (lang === "zh" ? "暂无候选" : "no candidates");
  const sourceCollectionCandidateExtractionButtonText = selectedTeamExtractSourceCollectionCandidatesPending
    ? (lang === "zh" ? "Agent 提炼中" : "Agent extracting")
    : sourceCollectionPendingCandidateImportCount > 0
      ? (lang === "zh" ? "Agent 提炼资料" : "Agent extract")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "Agent 重新提炼" : "Agent re-extract")
        : (lang === "zh" ? "Agent 提炼资料" : "Agent extract");
  const sourceCollectionStageForPanel = (panelId: string): SourceCollectionStageModuleId => {
    if (panelId === "source-collection-screening-panel") {
      return "extraction";
    }
    if (panelId === "source-collection-graph-panel") {
      return "relations";
    }
    if (panelId === "source-collection-memory-panel") {
      return "ingestion";
    }
    return "finding";
  };
  const selectSourceCollectionStage = (stageId: SourceCollectionStageModuleId) => {
    setSelectedSourceCollectionStageId(stageId);
    if (!sourceCollectionStandalone) {
      return;
    }
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("researchView", "knowledge_collection");
    nextParams.set("collectionStage", stageId);
    setSearchParams(nextParams, { replace: true });
  };
  const scrollSourceCollectionPanelIntoView = (panelId: string) => {
    selectSourceCollectionStage(sourceCollectionStageForPanel(panelId));
    setSourceCollectionExpandedPanelId(panelId);
    setSourceCollectionFocusedPanelId(panelId);
    window.setTimeout(() => {
      setSourceCollectionFocusedPanelId((current) => (current === panelId ? "" : current));
    }, 2200);
    window.requestAnimationFrame(() => {
      const target = document.getElementById(panelId);
      if (!target) {
        return;
      }
      if (target instanceof HTMLDetailsElement) {
        target.open = true;
      }
      const container = sourceCollectionControlPanelRef.current;
      if (container && container.contains(target)) {
        const containerTop = container.getBoundingClientRect().top;
        const targetTop = target.getBoundingClientRect().top;
        const nextTop = Math.max(0, container.scrollTop + targetTop - containerTop - 10);
        container.scrollTo({
          top: nextTop,
          behavior: "smooth",
        });
        target.focus({ preventScroll: true });
        return;
      }
      target.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      target.focus({ preventScroll: true });
    });
  };
  scrollSourceCollectionPanelIntoViewRef.current = scrollSourceCollectionPanelIntoView;
  const openSourceCollectionScreeningPanel = () => {
    if (!selectedTeam?.teamId || sourceCollectionScreeningDisabled) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
  };
  const runSourceCollectionScreeningAction = () => {
    openSourceCollectionStage("extraction");
    if (sourceCollectionScreeningActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    const forceRescreen = sourceCollectionRunPendingScreeningCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
    const maxCandidates = forceRescreen ? sourceCollectionDisplayedCandidateCount : sourceCollectionRunPendingScreeningCount;
    assessSourceQualityBatchMutation.mutate({
      teamId: selectedTeam.teamId,
      assessedByAgent: sourceCollectionExtractorAgentId,
      maxCandidates: Math.max(1, Math.min(200, maxCandidates)),
      force: forceRescreen,
      notes: forceRescreen
        ? "Source Extractor Agent re-ran quality scoring on already assessed source_manifest candidates (no content rewrite)."
        : "Source Extractor Agent ran quality scoring on pending source_manifest candidates.",
    });
  };

  const excludeUnverifiableSourceCollectionCandidates = async () => {
    if (
      !selectedTeam?.teamId
      || selectedTeamSourceQualityPending
      || sourceCollectionUnverifiableCandidateIds.length <= 0
    ) {
      return;
    }
    for (const candidateId of sourceCollectionUnverifiableCandidateIds) {
      await assessSourceQualityMutation.mutateAsync({
        teamId: selectedTeam.teamId,
        candidateId,
        decision: "rejected",
      });
    }
  };
  const openSourceCollectionCandidatePanel = () => {
    if (!selectedTeam?.teamId) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
  };
  const runSourceCollectionCandidateExtractionAction = () => {
    openSourceCollectionStage("extraction");
    if (
      sourceCollectionCandidateExtractionActionReadiness.disabled
      || !selectedTeam?.teamId
      || !selectedSourceCollectionRunEffectiveId
    ) {
      return;
    }
    const forceExtraction = sourceCollectionPendingCandidateImportCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
    const targetRecordCount = forceExtraction
      ? Math.max(sourceCollectionRawRecordCount, sourceCollectionDisplayedCandidateCount)
      : Math.max(sourceCollectionPendingCandidateImportCount, sourceCollectionRawRecordCount);
    extractSourceCollectionCandidatesMutation.mutate({
      teamId: selectedTeam.teamId,
      runId: selectedSourceCollectionRunEffectiveId,
      extractionAgentId: sourceCollectionExtractorAgentId,
      maxRecords: Math.max(1, Math.min(500, targetRecordCount)),
      force: forceExtraction,
      notes: forceExtraction
        ? "Source Extractor Agent re-checked the DataRecord to source_manifest bridge without creating duplicate candidates."
        : "Source Extractor Agent imported pending DataRecords into source_manifest candidates.",
    });
  };
  const runSourceCollectionGraphAction = () => {
    if (sourceCollectionGraphActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    buildCandidateGraphMutation.mutate({
      teamId: selectedTeam.teamId,
      title: "Agent curated candidate graph",
      createdByAgent: sourceCollectionRelationMapperAgentId,
      sourceQualityAgentId: sourceCollectionExtractorAgentId,
      curationMode: "agent_approved_only",
      maxCandidates: Math.max(1, Math.min(80, sourceCollectionIngestCandidateCount)),
      forceReview: sourceCollectionRunApprovedCount <= 0 && sourceCollectionDisplayedCandidateCount > 0,
    });
    openSourceCollectionStage("relations");
  };
  const startKnowledgeCollectionCompletionForRun = (
    runId: string,
    options: {
      displayedCandidateCount?: number;
      ingestCandidateCount?: number;
      precheckCandidateCount?: number;
      rawRecordCount?: number;
      searchOpenAssignmentCount?: number;
    } = {},
  ) => {
    if (!selectedTeam?.teamId || !runId) {
      return;
    }
    const searchOpenAssignmentCount = options.searchOpenAssignmentCount ?? sourceCollectionSearchOpenAssignmentCount;
    const rawRecordCount = options.rawRecordCount ?? sourceCollectionRawRecordCount;
    const displayedCandidateCount = options.displayedCandidateCount ?? sourceCollectionDisplayedCandidateCount;
    const ingestCandidateCount = options.ingestCandidateCount ?? sourceCollectionIngestCandidateCount;
    const precheckCandidateCount = options.precheckCandidateCount ?? sourceCollectionPrecheckCandidateCount;
    selectResearchWorkspaceView("canvas");
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("team", selectedTeam.teamId);
    nextParams.set("researchView", "canvas");
    setSearchParams(nextParams, { replace: false });
    runKnowledgeCollectionCompletionMutation.mutate({
      teamId: selectedTeam.teamId,
      runId,
      extractionAgentId: sourceCollectionExtractorAgentId,
      sourceQualityAgentId: sourceCollectionExtractorAgentId,
      candidateGraphAgentId: sourceCollectionRelationMapperAgentId,
      stewardAgentId: sourceCollectionIngestorAgentId,
      knowledgeBaseId: sourceCollectionDefaultKnowledgeBaseId,
      targetDomain: sourceCollectionDraft.topic || "神经机制启发神经网络算法",
      maxCandidates: Math.max(1, Math.min(80, ingestCandidateCount)),
      maxSearchBatches: 20,
      maxQueriesPerBatch: Math.max(1, Math.min(50, searchOpenAssignmentCount || 4)),
      maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 3)),
      maxRecords: Math.max(1, Math.min(1000, Math.max(rawRecordCount, displayedCandidateCount, 100))),
      forceReview: precheckCandidateCount <= 0 && displayedCandidateCount > 0,
    });
  };
  const runKnowledgeCollectionCompletionAction = () => {
    if (sourceCollectionCompletionActionReadiness.disabled || !sourceCollectionActionRunId) {
      return;
    }
    startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId);
  };
  const runKnowledgeCollectionLoopAction = async () => {
    if (sourceCollectionLoopActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    if (sourceCollectionLoopStartsNewRun) {
      try {
        const started = await startSourceCollectionRunMutation.mutateAsync({
          teamId: selectedTeam.teamId,
          draft: sourceCollectionDraft,
        });
        const startedRunId = started.run.runId;
        const startedAssignmentCount = Math.max(started.assignmentCount, started.assignments.length);
        startKnowledgeCollectionCompletionForRun(startedRunId, {
          displayedCandidateCount: 0,
          ingestCandidateCount: 0,
          precheckCandidateCount: 0,
          rawRecordCount: 0,
          searchOpenAssignmentCount: startedAssignmentCount || 4,
        });
      } catch {
        return;
      }
      return;
    }
    if (!sourceCollectionActionRunId) {
      return;
    }
    startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId);
  };
  const runSourceCollectionSearchFromHeader = () => {
    if (sourceCollectionSearchActionReadiness.disabled || !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId) {
      return;
    }
    const selectedAssignmentIsRunnable = selectedSourceCollectionAssignment
      ? ["open", "in_progress", "returned"].includes(selectedSourceCollectionAssignment.status)
        && SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(selectedSourceCollectionAssignment.agentRole)
      : false;
    executeSourceCollectionSearchMutation.mutate({
      teamId: selectedTeam.teamId,
      runId: selectedSourceCollectionRunEffectiveId,
      assignmentId: selectedAssignmentIsRunnable ? selectedSourceCollectionAssignment?.assignmentId : "",
      maxQueries: 4,
      maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 2)),
    });
  };
  const runSourceCollectionCollectionAction = () => {
    if (sourceCollectionCollectionActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    openSourceCollectionStage("finding");
    if (!selectedSourceCollectionRun) {
      launchResearchStage("knowledge_collection");
      return;
    }
    if (sourceCollectionSearchOpenAssignmentCount > 0) {
      runSourceCollectionSearchFromHeader();
      return;
    }
    launchResearchStage("knowledge_collection", "new_round");
  };
  const sourceCollectionConsoleState: SourceCollectionStepState = sourceCollectionDisplayState.consoleState;
  const sourceCollectionConsoleStatusText = sourceCollectionDisplayState.statusText;
  const sourceCollectionDecisionText = sourceCollectionDisplayState.decisionText;
  const sourceCollectionStepStatusText = (state: SourceCollectionStepState) => {
    const labels: Record<SourceCollectionStepState, string> = lang === "zh"
      ? {
          active: "进行中",
          done: "已完成",
          failed: "失败",
          idle: "未进行",
          pending: "待处理",
        }
      : {
          active: "running",
          done: "done",
          failed: "failed",
          idle: "not started",
          pending: "pending",
    };
    return labels[state];
  };
  const sourceCollectionStageProjectionSyncing = (projection: SourceCollectionStageCardProjection | null | undefined) => {
    if (!sourceCollectionStageWritebackSyncActive || !projection) {
      return false;
    }
    const latestTaskStatus = String(projection.latestTask?.status || "").toLowerCase();
    return projection.status === "agent_running" || latestTaskStatus === "queued" || latestTaskStatus === "running";
  };
  const sourceCollectionStageProjectionLabel = (projection: SourceCollectionStageCardProjection | null | undefined) => {
    if (!projection?.status) {
      return "";
    }
    return sourceCollectionStageUserStatusLabel(projection, lang, sourceCollectionStageProjectionSyncing(projection));
  };
  function sourceCollectionStageLaunchActive(stageId: SourceCollectionStageModuleId) {
    const projection = sourceCollectionStageCardById.get(stageId);
    return sourceCollectionStageLaunchActivePure(stageId, {
      pendingStageId: sourceCollectionStageSessionTaskPendingStageId,
      pendingTaskIds: sourceCollectionPendingStageTaskIds[stageId] ?? [],
      writebackSyncActive: sourceCollectionStageWritebackSyncActive,
      latestTaskId: projection?.latestTask?.taskId || "",
      latestTaskStatus: String(projection?.latestTask?.status || "").toLowerCase(),
      projectionStatus: String(projection?.status || "").toLowerCase(),
    });
  }
  function sourceCollectionStageFormalRetryRequired(stageId: SourceCollectionStageModuleId) {
    const latestTaskStatus = String(
      sourceCollectionStageCardById.get(stageId)?.latestTask?.status || "",
    ).trim().toLowerCase();
    return new Set(["failed", "error", "blocked", "cancelled", "canceled", "incomplete"]).has(
      latestTaskStatus,
    );
  }
  function sourceCollectionStageLaunchSummary(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageLaunchSummaryPure(stageId, sourceCollectionStageSessionTaskPendingStageId, lang);
  }
  function sourceCollectionStageDisplayState(stageId: SourceCollectionStageModuleId, fallback: SourceCollectionStepState) {
    return sourceCollectionStageDisplayStatePure(sourceCollectionStageLaunchActive(stageId), fallback);
  }
  function sourceCollectionStageDisplayStatus(stageId: SourceCollectionStageModuleId, fallback: string) {
    return sourceCollectionStageDisplayStatusPure(
      stageId,
      sourceCollectionStageLaunchActive(stageId),
      sourceCollectionStageSessionTaskPendingStageId,
      fallback,
      lang,
    );
  }
  function sourceCollectionStageDisplaySummary(stageId: SourceCollectionStageModuleId, fallback: string) {
    return sourceCollectionStageDisplaySummaryPure(
      sourceCollectionStageLaunchActive(stageId),
      sourceCollectionStageLaunchSummary(stageId),
      fallback,
    );
  }
  const sourceCollectionStepClassName = (state: SourceCollectionStepState) => ({
    active: styles.sourceCollectionStepActive,
    done: styles.sourceCollectionStepDone,
    failed: styles.sourceCollectionStepFailed,
    idle: styles.sourceCollectionStepIdle,
    pending: styles.sourceCollectionStepPending,
  }[state]);
  const sourceCollectionSearchStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionCollectionProjection,
    sourceCollectionDisplayState.searchStepState,
  );
  const sourceCollectionScreeningFallbackStepState: SourceCollectionStepState = selectedTeamSourceQualityError
    ? "failed"
      : selectedTeamSourceQualityPending
        ? "active"
      : sourceCollectionRunAssessedCount > 0
        ? "done"
      : sourceCollectionDisplayedCandidateCount > 0 && sourceCollectionSearchOpenAssignmentCount <= 0
          ? "pending"
          : "idle";
  const sourceCollectionScreeningStepStateRaw: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionScreeningProjection,
    sourceCollectionScreeningFallbackStepState,
  );
  const sourceCollectionScreeningStepState: SourceCollectionStepState = sourceCollectionExtractionCanProceedAfterExclusions
    ? "done"
    : sourceCollectionScreeningStepStateRaw;
  const sourceCollectionCandidateFallbackStepState: SourceCollectionStepState = selectedTeamRecordSourceCollectionOutputError || selectedTeamExtractSourceCollectionCandidatesError
    ? "failed"
    : selectedTeamRecordSourceCollectionOutputPending || selectedTeamExtractSourceCollectionCandidatesPending
      ? "active"
      : sourceCollectionDisplayedCandidateCount > 0
        ? "done"
        : selectedSourceCollectionRun
          ? "pending"
          : "idle";
  const sourceCollectionCandidateStepStateRaw: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionCandidateProjection,
    sourceCollectionCandidateFallbackStepState,
  );
  const sourceCollectionCandidateStepState: SourceCollectionStepState = sourceCollectionExtractionCanProceedAfterExclusions
    ? "done"
    : sourceCollectionCandidateStepStateRaw;
  const sourceCollectionExtractionDefaultPanelId = "source-collection-screening-panel";
  const sourceCollectionGraphFallbackStepState: SourceCollectionStepState = selectedTeamBuildCandidateGraphError || teamWorkflowCandidateGraphQuery.error
    ? "failed"
      : selectedTeamBuildCandidateGraphPending
        ? "active"
      : candidateGraphNodeCount > 0
        ? "done"
        : sourceCollectionRunApprovedCount > 0
          ? "pending"
          : "idle";
  const sourceCollectionGraphStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionGraphProjection,
    sourceCollectionGraphFallbackStepState,
  );
  const sourceCollectionMemoryFallbackStepState: SourceCollectionStepState = teamWorkflowKnowledgeIngestionStatusQuery.error || selectedTeamKnowledgePrecheckError || selectedTeamKnowledgeCollectionIngestError
    ? "failed"
    : selectedTeamKnowledgePrecheckPending || selectedTeamKnowledgeCollectionIngestPending
      ? "active"
      : formalKnowledgeItemCount > 0
        ? "done"
        : knowledgePendingReviewCount > 0 || knowledgeStewardPackCount > 0 || sourceCollectionIngestCandidateCount > 0
          ? "pending"
          : "idle";
  const sourceCollectionMemoryStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionMemoryProjection,
    sourceCollectionMemoryFallbackStepState,
  );
  const sourceCollectionExtractionStepState: SourceCollectionStepState =
    sourceCollectionCandidateStepState === "failed" || sourceCollectionScreeningStepState === "failed"
      ? "failed"
      : sourceCollectionCandidateStepState === "active" || sourceCollectionScreeningStepState === "active"
        ? "active"
        : sourceCollectionDisplayedCandidateCount > 0
          ? sourceCollectionScreeningStepState
          : sourceCollectionCandidateStepState;
  const sourceCollectionCollectionActionLabel = !selectedSourceCollectionRun
    ? sourceCollectionStageSessionTaskPendingStageId === "finding"
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : (lang === "zh" ? "开始搜集" : "Start")
    : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
      ? (lang === "zh" ? "搜索中" : "Searching")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? "搜索下一批" : "Search next")
      : (lang === "zh" ? "新一轮搜集" : "New round");
  const sourceCollectionCollectionActionReadiness = !selectedSourceCollectionRun
    ? sourceCollectionActionReadiness(
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
          ? sourceCollectionActionBusyReason
          : sourceCollectionActionNoInputReason,
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
      )
    : sourceCollectionAssignmentsDataLoading || sourceCollectionActionDataError
      ? sourceCollectionActionReadiness(
          true,
          sourceCollectionAssignmentsDataLoading ? sourceCollectionActionLoadingReason : sourceCollectionActionErrorReason,
          sourceCollectionAssignmentsDataLoading,
        )
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? sourceCollectionSearchActionReadiness
        : sourceCollectionActionReadiness(
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
              ? sourceCollectionActionBusyReason
              : sourceCollectionActionNoInputReason,
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
          );
  const sourceCollectionStageTaskActionLabel = (stageId: SourceCollectionStageModuleId, label: string) =>
    sourceCollectionStageSessionTaskPendingStageId === stageId
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : sourceCollectionStageLaunchActive(stageId)
        ? (lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback")
        : label;
  const sourceCollectionStageTaskActionReadiness = (stageId: SourceCollectionStageModuleId, readiness: SourceCollectionActionReadiness) =>
    sourceCollectionStageLaunchActive(stageId)
      ? sourceCollectionActionReadiness(true, lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback", true)
      : readiness.disabled
        ? readiness
        : sourceCollectionActionReadiness(
            selectedTeamStartSourceCollectionStageTaskPending,
            sourceCollectionActionBusyReason,
            selectedTeamStartSourceCollectionStageTaskPending,
          );
  const sourceCollectionStageActionLabelFor = (stageId: SourceCollectionStageModuleId, fallback: string) =>
    sourceCollectionStageTaskActionLabel(
      stageId,
      sourceCollectionStageCardById.get(stageId)?.actionReadiness?.actionLabel || fallback,
    );
  const sourceCollectionStageActionReadinessFor = (stageId: SourceCollectionStageModuleId): SourceCollectionActionReadiness => {
    if (stageId === "finding") {
      return sourceCollectionStageTaskActionReadiness(
        "finding",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("finding"),
          sourceCollectionCollectionActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "extraction") {
      const extractionDisabled = sourceCollectionCandidateExtractionActionReadiness.disabled && sourceCollectionScreeningActionReadiness.disabled;
      const extractionLoading = sourceCollectionCandidateExtractionActionReadiness.loading || sourceCollectionScreeningActionReadiness.loading;
      const extractionReason = !sourceCollectionCandidateExtractionActionReadiness.disabled
        ? sourceCollectionCandidateExtractionActionReadiness.reason
        : sourceCollectionScreeningActionReadiness.reason || sourceCollectionCandidateExtractionActionReadiness.reason;
      return sourceCollectionStageTaskActionReadiness(
        "extraction",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("extraction"),
          sourceCollectionActionReadiness(extractionDisabled, extractionReason || sourceCollectionActionNoInputReason, extractionLoading),
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "relations") {
      return sourceCollectionStageTaskActionReadiness(
        "relations",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("relations"),
          sourceCollectionGraphActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    return sourceCollectionStageTaskActionReadiness(
      "ingestion",
      sourceCollectionStageBackendActionReadiness(
        sourceCollectionStageCardById.get("ingestion"),
        sourceCollectionMemoryActionReadiness,
        sourceCollectionActionNoInputReason,
      ),
    );
  };
  const sourceCollectionFindingDisplayLoading = sourceCollectionRecordsDataLoading || sourceCollectionAssignmentsDataLoading;
  const sourceCollectionFindingDisplayState: SourceCollectionStepState = sourceCollectionFindingDisplayLoading
    ? "pending"
    : sourceCollectionSearchStepState;
  const sourceCollectionExtractionDisplayLoading = sourceCollectionPrimaryDataLoading || sourceCollectionScreeningDataLoading;
  const sourceCollectionExtractionDisplayState: SourceCollectionStepState = sourceCollectionExtractionDisplayLoading
    ? "pending"
    : sourceCollectionExtractionStepState;
  const sourceCollectionRelationsDisplayLoading = sourceCollectionGraphDataLoading;
  const sourceCollectionRelationsDisplayState: SourceCollectionStepState = sourceCollectionRelationsDisplayLoading
    ? "pending"
    : sourceCollectionGraphStepState;
  const sourceCollectionIngestionDisplayLoading = sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading;
  const sourceCollectionIngestionDisplayState: SourceCollectionStepState = sourceCollectionIngestionDisplayLoading
    ? "pending"
    : sourceCollectionMemoryStepState;
  const sourceCollectionSourceSyncStatusText = sourceCollectionProjectedCollectedCount > 0
    ? sourceCollectionDataSyncText
    : sourceCollectionLoadingText;
  const sourceCollectionCandidateSyncStatusText = sourceCollectionDisplayedCandidateCount > 0 || sourceCollectionProjectedCollectedCount > 0
    ? sourceCollectionDataSyncText
    : sourceCollectionLoadingText;
  const sourceCollectionExtractionLoadingMetric = sourceCollectionProjectedCandidateCount > 0
    ? (lang === "zh"
      ? `已处理 ${sourceCollectionProjectedAssessedCount}/${sourceCollectionProjectedCandidateCount} · ${sourceCollectionDataSyncText}`
      : `${sourceCollectionProjectedAssessedCount}/${sourceCollectionProjectedCandidateCount} processed · ${sourceCollectionDataSyncText}`)
      : (lang === "zh" ? "提炼进度 加载中" : "extraction loading");
  const sourceCollectionExtractionMaterialMetric = lang === "zh"
    ? `已提炼 ${sourceCollectionCurrentCandidateCount}/${sourceCollectionCurrentCandidateCount} · ${sourceCollectionExtractionAgentMaterialCount} 条待补材料`
    : `${sourceCollectionCurrentCandidateCount}/${sourceCollectionCurrentCandidateCount} extracted · ${sourceCollectionExtractionAgentMaterialCount} need material`;
  const sourceCollectionExtractionLoadingOutputLabel = sourceCollectionProjectedCandidateCount > 0 || sourceCollectionProjectedApprovedCount > 0
    ? (lang === "zh"
      ? `${sourceCollectionProjectedApprovedCount} 条保留 / ${sourceCollectionRunPendingScreeningCount} 条待处理 · ${sourceCollectionDataSyncText}`
      : `${sourceCollectionProjectedApprovedCount} kept / ${sourceCollectionRunPendingScreeningCount} pending · ${sourceCollectionDataSyncText}`)
    : (lang === "zh" ? "提炼结果加载中" : "extraction result loading");
  const sourceCollectionIngestionReadyForExperiment = sourceCollectionProjectedFormalKnowledgeCount > 0;
  const sourceCollectionExperimentPlanningRoute = researchWorkspaceStageRoute(
    selectedTeam?.teamId || RESEARCH_TEAM_ID,
    "experiment",
  );
  const sourceCollectionStageModules: SourceCollectionStageModule[] = [
    {
      id: "finding",
      label: lang === "zh" ? "找资料" : "Find",
      metric: lang === "zh" ? `原始资料 ${sourceCollectionProjectedCollectedCountLabel}` : sourceCollectionProjectedCollectedCountLabel,
      summary: sourceCollectionStageLaunchActive("finding")
        ? sourceCollectionStageLaunchSummary("finding")
        : sourceCollectionFindingDisplayLoading
        ? (lang === "zh" ? "正在读取资料结果" : "Loading source results")
        : sourceCollectionStageUserSummary(sourceCollectionCollectionProjection, lang) || (!selectedSourceCollectionRun
        ? (lang === "zh" ? "点击开始生成本轮任务" : "Start to create this run")
        : sourceCollectionSearchOpenAssignmentCount > 0
          ? (lang === "zh" ? `${sourceCollectionSearchOpenAssignmentCount} 个搜索任务待执行` : `${sourceCollectionSearchOpenAssignmentCount} search tasks remain`)
          : sourceCollectionPrimaryDataLoading
            ? (lang === "zh" ? "正在读取资料结果" : "Loading source results")
            : (lang === "zh" ? `已找到 ${sourceCollectionProjectedCollectedCountText} 条资料` : `${sourceCollectionProjectedCollectedCountText} sources found`)),
      inputLabel: lang === "zh" ? `${sourceCollectionQueryCountLabel} 搜索问题` : `${sourceCollectionQueryCountText} queries`,
      outputLabel: lang === "zh" ? `${sourceCollectionProjectedCollectedCountLabel} 原始资料` : sourceCollectionProjectedCollectedCountLabel,
      nextLabel: sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? "继续寻找资料" : "Continue finding")
        : (lang === "zh" ? "进入资料提炼" : "Move to extraction"),
      state: sourceCollectionStageDisplayState("finding", sourceCollectionFindingDisplayState),
      status: sourceCollectionStageDisplayStatus("finding", sourceCollectionFindingDisplayLoading ? sourceCollectionSourceSyncStatusText : sourceCollectionStepStatusText(sourceCollectionSearchStepState)),
      detailLabel: lang === "zh" ? "查看资料记录" : "View source records",
      actionLabel: sourceCollectionStageActionLabelFor("finding", sourceCollectionCollectionActionLabel),
      actionDisabled: sourceCollectionStageActionReadinessFor("finding").disabled,
      actionTone: "primary",
      actionIcon: selectedSourceCollectionRun && sourceCollectionSearchOpenAssignmentCount > 0 ? "search" : "play",
      projection: sourceCollectionCollectionProjection,
      onAction: () => void startSourceCollectionStageSessionTask("finding"),
      onDetail: () => openSourceCollectionStage("finding"),
    },
    {
      id: "extraction",
      label: lang === "zh" ? "提炼" : "Extract",
      metric: sourceCollectionScreeningDataLoading || sourceCollectionPrimaryDataLoading
        ? sourceCollectionExtractionLoadingMetric
        : sourceCollectionExtractionNeedsAgentMaterial
          ? sourceCollectionExtractionMaterialMetric
        : (lang === "zh" ? `已处理 ${sourceCollectionProjectedAssessedCountText}/${sourceCollectionCurrentCandidateCountText}` : `${sourceCollectionProjectedAssessedCountText}/${sourceCollectionCurrentCandidateCountText} processed`),
      summary: sourceCollectionStageLaunchActive("extraction")
        ? sourceCollectionStageLaunchSummary("extraction")
        : sourceCollectionExtractionDisplayLoading
        ? sourceCollectionLoadingSummary
        : sourceCollectionExtractionCanProceedAfterExclusions
        ? sourceCollectionExtractionProceedableSummary
        : sourceCollectionExtractionNeedsAgentMaterial
        ? (lang === "zh"
          ? `${sourceCollectionExtractionAgentMaterialCount} 条待补：现在只点右侧主按钮补材料，完成后流程会自动切到质量审查。`
          : `${sourceCollectionExtractionAgentMaterialCount} need material: use the right-stage primary button only; review becomes the next recommended step after repair.`)
        : sourceCollectionStageUserSummary(sourceCollectionExtractionProjection, lang) || (sourceCollectionPrimaryDataLoading
        ? sourceCollectionLoadingSummary
        : sourceCollectionDisplayedCandidateCount <= 0
          ? (lang === "zh" ? "等待资料寻找结果" : "Waiting for found sources")
          : sourceCollectionRunPendingScreeningCount > 0
            ? (lang === "zh" ? `${sourceCollectionRunPendingScreeningCountText} 条待继续提炼或审查` : `${sourceCollectionRunPendingScreeningCountText} need extraction or review`)
            : (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条可进入关系整理` : `${sourceCollectionProjectedApprovedCountText} ready for relation mapping`)),
      inputLabel: lang === "zh" ? `${sourceCollectionProjectedCollectedCountLabel} 原始资料` : sourceCollectionProjectedCollectedCountLabel,
      outputLabel: sourceCollectionPrimaryDataLoading || sourceCollectionScreeningDataLoading
        ? sourceCollectionExtractionLoadingOutputLabel
        : sourceCollectionExtractionCanProceedAfterExclusions
          ? (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条保留 / ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} 条已排除` : `${sourceCollectionProjectedApprovedCountText} kept / ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} excluded`)
          : sourceCollectionExtractionNeedsAgentMaterial
            ? (lang === "zh" ? `${sourceCollectionCurrentCandidateCountText} 条已提炼 / ${sourceCollectionExtractionAgentMaterialCount} 条待补材料` : `${sourceCollectionCurrentCandidateCountText} extracted / ${sourceCollectionExtractionAgentMaterialCount} need material`)
          : (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条保留 / ${sourceCollectionRunPendingScreeningCountText} 条待处理` : `${sourceCollectionProjectedApprovedCountText} kept / ${sourceCollectionRunPendingScreeningCountText} pending`),
      nextLabel: sourceCollectionExtractionNeedsAgentMaterial
        ? (lang === "zh" ? "要求 Agent 补充材料" : "Request Agent material supplement")
        : sourceCollectionRunPendingScreeningCount > 0
        ? (lang === "zh" ? "Agent 继续提炼" : "Agent continues extraction")
        : (lang === "zh" ? "进入资料关系整理" : "Move to relation mapping"),
      state: sourceCollectionStageDisplayState("extraction", sourceCollectionExtractionCanProceedAfterExclusions ? "done" : sourceCollectionExtractionDisplayState),
      status: sourceCollectionStageDisplayStatus(
        "extraction",
        sourceCollectionExtractionDisplayLoading
          ? sourceCollectionCandidateSyncStatusText
        : sourceCollectionExtractionCanProceedAfterExclusions
            ? sourceCollectionExtractionExcludedRecoveryState.statusLabel
            : sourceCollectionExtractionNeedsAgentMaterial
              ? (lang === "zh" ? "待补材料" : "material needed")
            : sourceCollectionStepStatusText(sourceCollectionExtractionStepState),
      ),
      detailLabel: lang === "zh" ? "查看提炼结果" : "View extraction details",
      actionLabel: sourceCollectionExtractionCanProceedAfterExclusions
        ? sourceCollectionExtractionExcludedRecoveryState.primaryActionText
        : sourceCollectionExtractionNeedsAgentMaterial
          ? (lang === "zh" ? "要求 Agent 补充材料" : "Request Agent material supplement")
        : sourceCollectionStageActionLabelFor(
          "extraction",
          sourceCollectionDisplayedCandidateCount > 0
            ? (lang === "zh" ? "Agent 提炼资料" : "Agent extract sources")
            : sourceCollectionCandidateExtractionButtonText,
        ),
      actionDisabled: sourceCollectionExtractionCanProceedAfterExclusions ? false : sourceCollectionStageActionReadinessFor("extraction").disabled,
      actionTone: "primary",
      actionIcon: selectedTeamExtractSourceCollectionCandidatesPending || selectedTeamSourceQualityPending ? "refresh" : "archive",
      projection: sourceCollectionExtractionProjection,
      onAction: sourceCollectionExtractionCanProceedAfterExclusions
        ? () => void openSourceCollectionStageAgentChat("extraction")
        : () => void startSourceCollectionStageSessionTask("extraction"),
      onDetail: () => openSourceCollectionStage("extraction"),
    },
    {
      id: "relations",
      label: lang === "zh" ? "整理关系" : "Map",
      metric: lang === "zh" ? `节点 ${sourceCollectionProjectedGraphNodeCount} / 关系 ${sourceCollectionProjectedGraphEdgeCount}` : `${sourceCollectionProjectedGraphNodeCount} nodes / ${sourceCollectionProjectedGraphEdgeCount} edges`,
      summary: sourceCollectionStageLaunchActive("relations")
        ? sourceCollectionStageLaunchSummary("relations")
        : sourceCollectionRelationsDisplayLoading
        ? (lang === "zh" ? "正在读取候选和关系数据" : "Loading candidates and relations")
        : sourceCollectionStageUserSummary(sourceCollectionGraphProjection, lang) || (sourceCollectionProjectedGraphNodeCount > 0
        ? (lang === "zh" ? "资料关系已整理" : "Source relations are ready")
        : sourceCollectionDisplayedCandidateCount > 0
          ? (lang === "zh" ? "可由 Agent 整理资料关系" : "Agent can map source relationships")
          : (lang === "zh" ? "等资料提炼后整理关系" : "Map after extraction")),
      inputLabel: sourceCollectionPrimaryDataLoading
        ? sourceCollectionProjectedCandidateCountLabel
        : (lang === "zh" ? `${sourceCollectionProjectedCandidateCountText} 条候选资料` : `${sourceCollectionProjectedCandidateCountText} candidate sources`),
      outputLabel: lang === "zh" ? `${sourceCollectionProjectedGraphNodeCount} 个节点 / ${sourceCollectionProjectedGraphEdgeCount} 条关系` : `${sourceCollectionProjectedGraphNodeCount} nodes / ${sourceCollectionProjectedGraphEdgeCount} edges`,
      nextLabel: sourceCollectionProjectedGraphNodeCount > 0
        ? (lang === "zh" ? "进入资料入库" : "Move to ingestion")
        : (lang === "zh" ? "生成资料关系" : "Build source relations"),
      state: sourceCollectionStageDisplayState("relations", sourceCollectionRelationsDisplayState),
      status: sourceCollectionStageDisplayStatus("relations", sourceCollectionRelationsDisplayLoading ? sourceCollectionDataSyncText : sourceCollectionStepStatusText(sourceCollectionGraphStepState)),
      detailLabel: lang === "zh" ? "查看资料关系" : "View relations",
      actionLabel: sourceCollectionStageActionLabelFor("relations", sourceCollectionGraphActionLabel),
      actionDisabled: sourceCollectionStageActionReadinessFor("relations").disabled,
      actionTone: "primary",
      actionIcon: "refresh",
      projection: sourceCollectionGraphProjection,
      onAction: () => void startSourceCollectionStageSessionTask("relations"),
      onDetail: () => openSourceCollectionStage("relations"),
    },
    {
      id: "ingestion",
      label: lang === "zh" ? "入库" : "Ingest",
      metric: lang === "zh" ? `正式知识 ${sourceCollectionProjectedFormalKnowledgeCount}` : `${sourceCollectionProjectedFormalKnowledgeCount} formal items`,
      summary: sourceCollectionStageLaunchActive("ingestion")
        ? sourceCollectionStageLaunchSummary("ingestion")
        : sourceCollectionIngestionDisplayLoading
        ? (lang === "zh" ? "正在读取候选和入库数据" : "Loading candidates and ingestion data")
        : sourceCollectionStageUserSummary(sourceCollectionMemoryProjection, lang) || (sourceCollectionProjectedFormalKnowledgeCount > 0
        ? (lang === "zh" ? "已进入团队知识库" : "Synced into Team Knowledge")
        : sourceCollectionProjectedStewardPackCount > 0
          ? (lang === "zh" ? "已生成入库待审包" : "Ingestion review pack ready")
        : knowledgePendingReviewCount > 0
          ? (lang === "zh" ? "有待入库对象" : "Ingestion items pending")
        : sourceCollectionPrecheckCandidateCount > 0
          ? (lang === "zh" ? "可通知资料入库 Agent" : "Can notify ingestion Agent")
          : sourceCollectionDisplayedCandidateCount > 0
            ? (lang === "zh" ? "可先提炼再入库" : "Extract before ingestion")
            : (lang === "zh" ? "等资料提炼后入库" : "Ingest after extraction")),
      inputLabel: sourceCollectionPrecheckCandidateCount > 0
        ? (lang === "zh" ? `${sourceCollectionPrecheckCandidateCount} 条通过资料` : `${sourceCollectionPrecheckCandidateCount} approved sources`)
        : sourceCollectionPrimaryDataLoading
          ? sourceCollectionProjectedCandidateCountLabel
          : (lang === "zh" ? `${sourceCollectionProjectedCandidateCountText} 条候选资料` : `${sourceCollectionProjectedCandidateCountText} candidate sources`),
      outputLabel: lang === "zh" ? `${sourceCollectionProjectedFormalKnowledgeCount} 条正式知识 / ${sourceCollectionProjectedGraphNodeCount} 个关系节点` : `${sourceCollectionProjectedFormalKnowledgeCount} formal / ${sourceCollectionProjectedGraphNodeCount} graph nodes`,
      nextLabel: sourceCollectionIngestionReadyForExperiment
        ? (lang === "zh" ? "进入实验规划" : "Move to experiment planning")
        : sourceCollectionProjectedStewardPackCount > 0
          ? (lang === "zh" ? "等待入库完成" : "Wait for ingestion")
          : (lang === "zh" ? "Agent 入库资料" : "Agent ingest sources"),
      state: sourceCollectionStageDisplayState("ingestion", sourceCollectionIngestionDisplayState),
      status: sourceCollectionStageDisplayStatus("ingestion", sourceCollectionIngestionDisplayLoading ? sourceCollectionDataSyncText : sourceCollectionStepStatusText(sourceCollectionMemoryStepState)),
      detailLabel: lang === "zh" ? "查看入库详情" : "View ingestion details",
      actionLabel: sourceCollectionIngestionReadyForExperiment
        ? (lang === "zh" ? "进入实验规划" : "Plan experiments")
        : sourceCollectionStageActionLabelFor("ingestion", sourceCollectionMemoryActionLabel),
      actionDisabled: sourceCollectionIngestionReadyForExperiment
        ? false
        : sourceCollectionStageActionReadinessFor("ingestion").disabled,
      actionTone: "primary",
      actionIcon: "check",
      projection: sourceCollectionMemoryProjection,
      onAction: sourceCollectionIngestionReadyForExperiment
        ? () => navigate(sourceCollectionExperimentPlanningRoute)
        : () => void startSourceCollectionStageSessionTask("ingestion"),
      onDetail: () => openSourceCollectionStage("ingestion"),
    },
  ];
  const sourceCollectionBoardCurrentModule =
    sourceCollectionStageModules.find((module) => module.state === "active")
    ?? sourceCollectionStageModules.find((module) => module.state === "failed")
    ?? sourceCollectionStageModules.find((module) => module.state === "pending")
    ?? sourceCollectionStageModules.find((module) => module.state === "idle")
    ?? sourceCollectionStageModules[sourceCollectionStageModules.length - 1];
  const sourceCollectionBoardNextStepLabel = sourceCollectionBoardCurrentModule?.state === "done"
    ? (lang === "zh" ? "进入实验规划" : "Plan experiments")
    : sourceCollectionBoardCurrentModule?.label ?? sourceCollectionStageFocusLabel;
  const sourceCollectionCompletionFlow = selectedTeamKnowledgeCollectionWorkRun?.flowVisualization ?? null;
  const sourceCollectionCompletionFlowNodes: SourceCollectionCompletionFlowNode[] =
    sourceCollectionCompletionFlow?.nodes?.length
      ? sourceCollectionCompletionFlow.nodes
      : sourceCollectionStageModules.map((module) => ({
          stageId: module.id,
          label: module.label,
          agentRole: SOURCE_COLLECTION_STAGE_AGENT_KEYS[module.id][0] || module.id,
          status: module.state === "active" ? "running" : module.state === "done" ? "completed" : module.state === "failed" ? "failed" : module.state === "pending" ? "pending" : "queued",
          inputCount: 0,
          outputCount: 0,
          artifactIds: [],
          detail: module.summary,
        }));
  const sourceCollectionStandaloneStageModules: TeamSourceCollectionStandaloneStageModule[] = sourceCollectionStageModules.map((module) => {
    const cardActionReadiness = sourceCollectionStageActionReadinessFor(module.id);
    return {
      id: module.id,
      tone: module.state,
      selected: module.id === selectedSourceCollectionStageId,
      title: module.detailLabel,
      status: module.status,
      label: module.label,
      metric: module.metric,
      nextLabel: `${lang === "zh" ? "下一步：" : "Next: "}${module.nextLabel}`,
      actionLabel: module.actionLabel,
      actionDisabled: module.actionDisabled,
      actionTitle: sourceCollectionActionDisabledTitle(cardActionReadiness, module.actionLabel),
      actionIcon: module.actionIcon,
      onAction: module.onAction,
      onDetail: module.onDetail,
    };
  });
  const sourceCollectionFindingHasVisibleRecords =
    sourceCollectionPageItems("finding", sourceCollectionFilteredRecords).items.length > 0;
  const sourceCollectionFindingStageCompact =
    selectedSourceCollectionStageId === "finding"
    && !sourceCollectionFindingHasVisibleRecords;
  const activeWorkflowItemCount = teamWorkflow?.activeWorkflowItems.length ?? 0;
  /** Shell mode owns left/right IA: board = full team workbench, canvas = org graph. */
  const researchCanvasVisible = teamShellMode === "canvas";
  // Board/Canvas page recipes own split geometry; rail width persists via layoutId.
  const teamsRailResize = useMemo(
    () => ({
      sidebar: {
        id: TEAMS_RAIL_PANE.id,
        defaultWidth: TEAMS_RAIL_PANE.defaultWidth,
        minWidth: TEAMS_RAIL_PANE.minWidth,
        maxWidth: TEAMS_RAIL_PANE.maxWidth,
      },
    }),
    [],
  );
  const teamListInitialLoading = teamsQuery.isPending && !teamsQuery.data;
  const teamListUnavailable = teamsQuery.isError && !teamsQuery.data;
  const showTeamInitialLoadingSurface = teamListInitialLoading;
  const showTeamUnavailableSurface = !teamListInitialLoading && !hasTeams;
  const selectedTeamDetailUnavailable = Boolean(
    effectiveTeamId && selectedTeamReference && !teamDetailQuery.data && teamDetailQuery.isError
  );
  const researchTeamDetailDegraded = Boolean(
    researchWorkflowTeamSelected && (selectedTeamDetailLoading || selectedTeamDetailUnavailable)
  );
  const showTeamLoadingSurface =
    !showTeamInitialLoadingSurface && !showTeamUnavailableSurface && selectedTeamDetailLoading && !researchWorkflowTeamSelected;
  const showTeamDetailUnavailableSurface =
    !showTeamInitialLoadingSurface && !showTeamUnavailableSurface && selectedTeamDetailUnavailable && !researchWorkflowTeamSelected;
  const teamInitialLoadingTitle = lang === "zh" ? "正在读取团队" : "Loading teams";
  const teamInitialLoadingMessage = lang === "zh"
    ? "正在连接团队索引；画布和检查器会在数据返回后原位补齐。"
    : "Connecting to the team index. The canvas and inspector will fill in place when data arrives.";
  const teamUnavailableTitle = teamListUnavailable
    ? (lang === "zh" ? "团队数据不可用" : "Team data unavailable")
    : (lang === "zh" ? "团队尚未初始化" : "Teams are not initialized");
  const teamUnavailableMessage = teamListUnavailable
    ? (lang === "zh"
      ? "当前前端没有拿到团队列表。请刷新团队数据，或通过 Launcher 恢复后端 API。"
      : "The frontend cannot read the team list. Refresh teams or restore the backend API from Launcher.")
    : (lang === "zh" ? "暂时没有可展示团队。请确认 AI 搜索范围团队、知识库扩充团队和挑战杯ai科研团队已初始化。" : "No visible teams are available. Confirm the AI search, knowledge expansion, and research teams are initialized.");
  const teamUnavailableDetail = teamsQuery.error instanceof Error ? teamsQuery.error.message : "";
  const teamWorkspaceLoadingTitle = lang === "zh" ? "正在读取团队详情" : "Loading team details";
  const teamWorkspaceLoadingMessage = selectedTeamReference
    ? (lang === "zh"
      ? `正在补齐 ${selectedTeamReference.name} 的完整详情；当前先保留工作台结构和可用画布。`
      : `Completing details for ${selectedTeamReference.name}; the workspace shell and available canvas stay visible.`)
    : (lang === "zh"
      ? "正在补齐团队详情；当前先保留工作台结构和可用画布。"
      : "Completing team details; the workspace shell and available canvas stay visible.");
  const teamWorkspaceUnavailableTitle = lang === "zh" ? "团队详情不可用" : "Team details unavailable";
  const teamWorkspaceUnavailableMessage = selectedTeamReference
    ? (lang === "zh"
      ? `${selectedTeamReference.name} 已出现在团队列表里，但详情接口没有返回完整工作区数据。请刷新团队，或通过 Launcher 恢复后端 API。`
      : `${selectedTeamReference.name} is present in the team list, but the detail API did not return the complete workspace data. Refresh teams or restore the backend API from Launcher.`)
    : (lang === "zh"
      ? "团队详情接口没有返回完整工作区数据。请刷新团队，或通过 Launcher 恢复后端 API。"
      : "The team detail API did not return the complete workspace data. Refresh teams or restore the backend API from Launcher.");
  const teamWorkspaceUnavailableDetail = teamDetailQuery.error instanceof Error ? teamDetailQuery.error.message : "";
  const teamContextMeta = selectedTeam?.name
    ?? (teamListInitialLoading
      ? (lang === "zh" ? "正在读取团队" : "Loading teams")
      : (lang === "zh" ? "暂无团队" : "No team"));
  const teamSummaryLoadingText = lang === "zh" ? "读取中" : "loading";
  const teamSummaryUnavailableText = lang === "zh" ? "不可用" : "unavailable";
  const teamListMetricLoadingLabel = lang === "zh" ? "正在读取团队指标" : "Loading team metrics";
  const teamSummaryStatusItems = [
    {
      label: lang === "zh" ? "团队" : "Teams",
      value: teamListInitialLoading ? teamSummaryLoadingText : visibleTeamSummary.activeTeamCount,
      tone: "info" as const,
    },
    {
      label: lang === "zh" ? "成员" : "Members",
      value: teamListInitialLoading ? teamSummaryLoadingText : visibleTeamSummary.memberCount,
      tone: "success" as const,
    },
    {
      label: lang === "zh" ? "失效" : "Stale",
      value: teamListInitialLoading ? teamSummaryLoadingText : visibleTeamSummary.staleMemberCount,
      tone: visibleTeamSummary.staleMemberCount > 0 ? "warning" as const : "neutral" as const,
    },
    { label: lang === "zh" ? "来源" : "Source", value: "Agent Center" },
  ];
  const workspaceClassName = [
    styles.workspace,
    styles.teamShellWorkspace,
    researchCanvasVisible ? styles.teamShellWorkspaceCanvas : styles.teamShellWorkspaceBoard,
  ].filter(Boolean).join(" ");
  const canvasPanelClassName = [
    styles.canvasPanel,
    !researchCanvasVisible ? styles.researchCanvasPanelHidden : "",
    researchCanvasVisible ? "min-h-0 flex-1" : "",
  ].filter(Boolean).join(" ");
  const inspectorClassName = [
    styles.inspector,
    researchWorkflowTeamSelected ? styles.researchInspector : "",
    challengeCupResearchTeamSelected && !researchCanvasVisible ? styles.challengeWorkspaceInspector : "",
    !researchCanvasVisible
      ? "flex h-full min-h-0 w-full max-w-none flex-1 flex-col overflow-hidden border-0 !bg-transparent"
      : "min-h-0 shrink-0",
  ].filter(Boolean).join(" ");
  const showNodeBindingPanel = researchCanvasVisible && !researchCanvasReadOnly;
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
  const showResearchSourceCollection = researchWorkflowTeamSelected && researchWorkspaceView === "source_collection";
  const showResearchCoordination = researchWorkflowTeamSelected && researchWorkspaceView === "coordination";
  const showResearchIngestion = researchWorkflowTeamSelected && researchWorkspaceView === "ingestion";
  const showResearchGraph = researchWorkflowTeamSelected && researchWorkspaceView === "graph";
  const showResearchCandidates = researchWorkflowTeamSelected && researchWorkspaceView === "candidates";
  const teamWorkflowCandidatePreviewItems: TeamWorkflowCandidatePreviewItem[] = teamWorkflowCandidates.map((candidate) => {
    const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
    const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
    const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(candidate);
    const canPlanPaperNoteChunks = sourceCandidateHasCompletedExtraction(candidate);
    const candidateQualityPending =
      selectedTeamAssessSourceQualityPending
      && assessSourceQualityMutation.variables?.candidateId === candidate.candidateId;
    const candidatePlanPending =
      selectedTeamPlanPaperNoteChunksPending
      && planPaperNoteChunksMutation.variables?.candidateId === candidate.candidateId;
    return {
      id: candidate.candidateId,
      tone: evidenceLedgerSummary?.missingAnchor ? "warning" : sourceCollectionResultTone(candidate.qualityStatus),
      statusLabel: workflowStateLabel(candidate.currentState, lang),
      title: candidate.title || candidate.candidateId,
      summary: candidate.summary || candidate.candidateType,
      meta: [
        { key: "type", label: candidate.candidateType },
        { key: "quality", label: candidate.qualityStatus },
        { key: "updated", label: formatTime(candidate.updatedAt, lang) },
        ...(sourceQualitySummary
          ? [{ key: "decision", label: `${lang === "zh" ? "质量判断" : "source quality"} ${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100` }]
          : candidate.candidateType === "source_manifest"
            ? [{ key: "decision", label: lang === "zh" ? "待质量审查" : "pending quality review" }]
            : []),
        ...(chunkPlanSummary
          ? [{ key: "chunks", label: `paper_note chunks ${chunkPlanSummary.completedChunkCount}/${chunkPlanSummary.chunkCount}` }]
          : canPlanPaperNoteChunks
          ? [{ key: "chunks", label: lang === "zh" ? "可生成 paper_note 分块" : "ready for paper_note chunks" }]
          : []),
        ...(evidenceLedgerSummary
          ? [{ key: "evidence-ledger", label: sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang) }]
          : []),
      ],
      actions: candidate.candidateType === "source_manifest" ? (
        <>
          <VNativeButton
            type="button"
            onClick={() => {
              if (!selectedTeam?.teamId || selectedTeamSourceQualityPending) {
                return;
              }
              assessSourceQualityMutation.mutate({
                teamId: selectedTeam.teamId,
                candidateId: candidate.candidateId,
                decision: "approved",
              });
            }}
            disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending}
            title={lang === "zh" ? "由资料提炼 Agent 标记为可保留" : "Mark this source as approved by the source extraction Agent"}
          >
            <CheckCircle2 size={13} />
            {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "approved"
              ? (lang === "zh" ? "筛选中" : "Assessing")
              : (lang === "zh" ? "通过复核" : "Approve source")}
          </VNativeButton>
          <VNativeButton
            type="button"
            onClick={() => {
              if (!selectedTeam?.teamId || selectedTeamSourceQualityPending) {
                return;
              }
              assessSourceQualityMutation.mutate({
                teamId: selectedTeam.teamId,
                candidateId: candidate.candidateId,
                decision: "needs_revision",
              });
            }}
            disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending}
            title={lang === "zh" ? "退回资料寻找 Agent 补资料" : "Return this source to the source finder for repair"}
          >
            <AlertTriangle size={13} />
            {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "needs_revision"
              ? (lang === "zh" ? "退回中" : "Returning")
              : (lang === "zh" ? "退回补资料" : "Needs repair")}
          </VNativeButton>
          <VNativeButton
            type="button"
            onClick={() => {
              if (!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending) {
                return;
              }
              planPaperNoteChunksMutation.mutate({
                teamId: selectedTeam.teamId,
                candidateId: candidate.candidateId,
              });
            }}
            disabled={!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending}
            title={
              canPlanPaperNoteChunks
                ? (lang === "zh" ? "生成或重建 paper_note 分块计划" : "Generate or rebuild the paper_note chunk plan")
                : (lang === "zh" ? "需要先完成 source extraction" : "Complete source extraction first")
            }
          >
            {chunkPlanSummary ? <RefreshCw size={13} /> : <Plus size={13} />}
            {candidatePlanPending
              ? (lang === "zh" ? "规划中" : "Planning")
              : chunkPlanSummary
                ? (lang === "zh" ? "重建分块计划" : "Rebuild chunk plan")
                : (lang === "zh" ? "生成分块计划" : "Generate chunk plan")}
          </VNativeButton>
        </>
      ) : undefined,
    };
  });
  const sourceCollectionOverviewSummary = selectedSourceCollectionRun
    ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionCollectedRunSummaryText} / ${sourceCollectionAssignmentRunSummaryText}`
    : sourceCollectionRunsQuery.isPending
      ? (lang === "zh" ? "读取批次中" : "loading runs")
      : (lang === "zh" ? "等待启动批次" : "waiting for run");
  const sourceCollectionOverviewStatus = sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "";
  const sourceCollectionOverviewStats: TeamSourceCollectionOverviewStat[] = [
    { key: "records", label: lang === "zh" ? "资料" : "records", value: sourceCollectionCollectedCountText },
    { key: "search", label: lang === "zh" ? "可搜索" : "search", value: sourceCollectionSearchOpenAssignmentCountText },
    { key: "next", label: lang === "zh" ? "后续" : "next work", value: sourceCollectionDownstreamOpenAssignmentCountText },
    { key: "queries", label: lang === "zh" ? "搜索问题" : "queries", value: sourceCollectionQueryCountText },
    {
      key: "prompt-cache",
      label: "KV",
      value: `${sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}${sourceCollectionPromptCacheMode ? ` · ${sourceCollectionPromptCacheMode}` : ""}`,
    },
  ];
  const sourceCollectionOverviewPlan: TeamSourceCollectionOverviewPlan | null = selectedTeamStartSourceCollectionResult ? {
    planId: selectedTeamStartSourceCollectionResult.searchPlan.planId,
    seeds: selectedTeamStartSourceCollectionResult.searchPlan.querySeeds.join(" / "),
    promptCache: `${sourceCollectionPromptCacheStatusLabel(selectedTeamStartSourceCollectionResult.promptCachePolicy.gate.status, lang)} · ${selectedTeamStartSourceCollectionResult.promptCachePolicy.promptCacheMode}`,
    boundary: lang === "zh" ? "不触发外部搜索，不写正式知识/RAG/图谱" : "No external search, formal Knowledge/RAG/Graph writes off",
  } : null;
  const sourceCollectionOverviewAssignmentEmptyMessage = sourceCollectionAssignmentsQuery.isPending
    ? (lang === "zh" ? "正在读取功能 Agent assignment..." : "Loading functional Agent assignments...")
    : (lang === "zh" ? "启动批次后会生成资料寻找、资料提炼、资料关系整理和资料入库任务。" : "Starting a run will create source finding, extraction, relation mapping, and ingestion assignments.");
  const sourceCollectionOverviewBoundaryItems = [
    lang === "zh" ? "执行器：手动/Agent 均可提交 CollectionOutput" : "Executor: manual or Agent CollectionOutput",
    lang === "zh" ? "正式知识写入关闭" : "formal knowledge write off",
    lang === "zh" ? "进入候选仓库后再筛选" : "screen after candidate import",
  ];
  const sourceCollectionOverviewErrors = [
    selectedTeamStartSourceCollectionError?.message,
    selectedTeamRecordSourceCollectionOutputError?.message,
  ].filter((message): message is string => Boolean(message));
  const sourceCollectionOverviewResult: TeamSourceCollectionOverviewResult | null = selectedTeamRecordSourceCollectionOutputResult ? {
    title: lang === "zh" ? "已回写" : "Written",
    detail: `${selectedTeamRecordSourceCollectionOutputResult.output.createdRecords.length} DataRecord / ${selectedTeamRecordSourceCollectionOutputResult.imported.length} candidate`,
  } : null;
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

  if (sourceCollectionStandalone) {
    return (
      <section className={`${styles.route} ${styles.sourceCollectionPage}`}>
        <header className={`${styles.header} ${styles.sourceCollectionPageHeader}`}>
          <div className={styles.sourceCollectionPageTitleBlock}>
            <div className={styles.sourceCollectionPageTitleLine}>
              <h1>{lang === "zh" ? "知识搜集工作台" : "Knowledge collection workspace"}</h1>
              <span className={`${styles.sourceCollectionRunBadge} ${sourceCollectionStepClassName(sourceCollectionConsoleState)}`}>
                {sourceCollectionConsoleStatusText}
              </span>
            </div>
          </div>
          <div className={styles.sourceCollectionPageActions}>
            {linkedChatRoomId ? (
              <Link to={teamChatRoomRoute(linkedChatRoomId, researchSourceCollectionRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID), lang === "zh" ? "返回知识搜集" : "Back to knowledge collection")}>
                <Users size={14} />
                {lang === "zh" ? "团队讨论" : "Team discussion"}
              </Link>
            ) : (
              <VNativeButton
                type="button"
                onClick={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
                disabled={!selectedTeam || activeTeamMemberCount === 0 || selectedTeamSyncPending}
              >
                <Users size={14} />
                {selectedTeamSyncPending
                  ? (lang === "zh" ? "同步中" : "Syncing")
                  : (lang === "zh" ? "同步团队讨论" : "Sync team discussion")}
              </VNativeButton>
            )}
            <Link to={teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <ArrowLeft size={14} />
              {lang === "zh" ? "返回团队页面" : "Back to team"}
            </Link>
            <VButton
              type="button"
              density="compact"
              variant="secondary"
              icon={<RefreshCw size={14} />}
              onPress={() => void sourceCollectionRunsQuery.refetch()}
              isDisabled={sourceCollectionRunsQuery.isFetching}
            >
              {lang === "zh" ? "刷新" : "Refresh"}
            </VButton>
          </div>
        </header>
        {researchWorkflowTeamSelected && !showTeamDetailUnavailableSurface ? (
          <TeamSourceCollectionStandaloneStagePanel
            commandAriaLabel={lang === "zh" ? "知识搜集操作台" : "Knowledge collection command bar"}
            commandTone={sourceCollectionConsoleState}
            commandTitle={
              sourceCollectionSelectedRunTopic
              || sourceCollectionDraft.topic.trim()
              || sourceCollectionRunTitleLabel(selectedSourceCollectionRun?.title || sourceCollectionDraft.title, lang)
            }
            commandSubtitle={
              lang === "zh"
                ? `${sourceCollectionSelectedRunQueryCount || compactSourceCollectionQuerySeeds(sourceCollectionDraft.topic, sourceCollectionDraft.querySeeds).length} 个搜索问题 · ${splitDraftList(sourceCollectionDraft.searchLanguages, 8).length || 1} 种语言 · ${splitDraftList(sourceCollectionDraft.sourceTypes, 12).length || 1} 类来源`
                : `${sourceCollectionSelectedRunQueryCount || compactSourceCollectionQuerySeeds(sourceCollectionDraft.topic, sourceCollectionDraft.querySeeds).length} queries · ${splitDraftList(sourceCollectionDraft.searchLanguages, 8).length || 1} languages · ${splitDraftList(sourceCollectionDraft.sourceTypes, 12).length || 1} source types`
            }
            commandStats={[
              { key: "status", label: lang === "zh" ? "当前" : "status", value: sourceCollectionConsoleStatusText },
              { key: "next", label: lang === "zh" ? "下一步" : "next", value: sourceCollectionBoardNextStepLabel },
              { key: "sources", label: lang === "zh" ? "资料" : "sources", value: sourceCollectionCollectedCountLabel },
            ]}
            searchBrief={renderSourceCollectionSearchBrief()}
            runSwitcher={renderSourceCollectionRunSwitcher()}
            runHistoryLabel={lang === "zh" ? "切换历史批次" : "Switch historical run"}
            phaseCloseGate={(
              <TeamSourceCollectionPhaseCloseGatePanel
                lang={lang}
                selectedRunId={selectedSourceCollectionRunEffectiveId}
                gate={sourceCollectionPhaseCloseGate}
                loading={Boolean(
                  selectedSourceCollectionRunEffectiveId
                  && sourceCollectionSummaryQuery.isPending
                  && !sourceCollectionSummaryQuery.data,
                )}
                compact
                onOpenStage={selectSourceCollectionStage}
              />
            )}
            stagePipelineId="source-collection-stage-status"
            stagePipelineAriaLabel={lang === "zh" ? "知识搜集内部模块" : "Knowledge collection modules"}
            modules={sourceCollectionStandaloneStageModules}
            activePanel={renderSourceCollectionActiveStagePanel()}
            compactActivePanel={sourceCollectionFindingStageCompact}
          />
        ) : (
          <main className={styles.sourceCollectionPageBody}>
            <section className={styles.sourceCollectionUnavailable}>
              <strong>
                {showTeamLoadingSurface
                  ? teamWorkspaceLoadingTitle
                  : showTeamDetailUnavailableSurface
                    ? teamWorkspaceUnavailableTitle
                    : (lang === "zh" ? "正在读取 挑战杯ai科研团队" : "Loading Challenge Cup AI research team")}
              </strong>
              <span>
                {showTeamLoadingSurface
                  ? teamWorkspaceLoadingMessage
                  : showTeamDetailUnavailableSurface
                  ? (teamWorkspaceUnavailableDetail || teamWorkspaceUnavailableMessage)
                  : teamDetailQuery.error instanceof Error
                  ? teamDetailQuery.error.message
                  : (lang === "zh" ? "这个一级页只绑定 research-team，不会展示给普通团队。" : "This workspace is bound to research-team and is hidden from ordinary teams.")}
              </span>
              <Link to={teamWorkspaceRoute(RESEARCH_TEAM_ID)}>
                <ArrowLeft size={14} />
                {lang === "zh" ? "返回团队页面" : "Back to team"}
              </Link>
            </section>
          </main>
        )}
      </section>
    );
  }

  if (stageStandaloneView) {
    return renderResearchStageStandalonePage(stageStandaloneView);
  }

  const teamShellRail = (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" data-vui-region="teams-sidebar">
      <TeamShellRail
        lang={lang}
        teams={visibleTeams}
        selectedTeamId={effectiveTeamId}
        onSelectTeam={selectTeamRecord}
      />
    </div>
  );

  const teamShellToolbar = (
    <TeamShellToolbar
      lang={lang}
      teamName={selectedTeam?.name ?? ""}
      purpose={selectedTeam?.purpose ?? ""}
      mode={teamShellMode}
      onModeChange={selectTeamShellMode}
      onRefresh={() => void teamsQuery.refetch()}
      identityClassName={styles.teamShellToolbarIdentity}
      actionsClassName={styles.teamShellToolbarActions}
      refreshButtonClassName={styles.teamRefreshButton}
    />
  );

  if (showTeamInitialLoadingSurface || showTeamUnavailableSurface || showTeamDetailUnavailableSurface) {
    return (
    <VDenseOpsPage
      className={styles.route}
      headerClassName={styles.challengeWorkspaceContextHidden}
      bodyClassName={styles.teamShellPageBody}
      data-vui-domain-recipe="teams-organization-workbench"
      ariaLabel={selectedTeamContextTitle}
      eyebrow={lang === "zh" ? "团队" : "Teams"}
      title={lang === "zh" ? "团队工作台" : "Team workbench"}
      meta={teamContextMeta}
      actions={null}
    >

      {showTeamInitialLoadingSurface ? (
        <main className={styles.teamUnavailableSurface} aria-label={teamInitialLoadingTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
            fill
            title={teamInitialLoadingTitle}
            tone="loading"
            skeletonLines={3}
            facts={[
              {
                key: "teams",
                label: lang === "zh" ? "团队" : "Teams",
                value: <VLoadingValue label={teamListMetricLoadingLabel} />,
              },
              {
                key: "members",
                label: lang === "zh" ? "成员" : "Members",
                value: <VLoadingValue label={teamListMetricLoadingLabel} />,
              },
              { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Agent Center" },
            ]}
          >
            {teamInitialLoadingMessage}
          </VStateSurface>
        </main>
      ) : showTeamUnavailableSurface ? (
        <main className={styles.teamUnavailableSurface} aria-label={teamUnavailableTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
            title={teamUnavailableTitle}
            tone={teamListUnavailable ? "error" : "empty"}
            facts={[
              {
                key: "teams",
                label: lang === "zh" ? "团队" : "Teams",
                value: teamListUnavailable ? teamSummaryUnavailableText : visibleTeamSummary.activeTeamCount,
              },
              {
                key: "members",
                label: lang === "zh" ? "成员" : "Members",
                value: teamListUnavailable ? teamSummaryUnavailableText : visibleTeamSummary.memberCount,
              },
              { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Agent Center" },
            ]}
            actions={(
              <VButton type="button" variant="secondary" onPress={() => void teamsQuery.refetch()} isDisabled={teamsQuery.isFetching}>
                <RefreshCw size={14} />
                {teamsQuery.isFetching ? (lang === "zh" ? "刷新中" : "Refreshing") : (lang === "zh" ? "刷新" : "Refresh")}
              </VButton>
            )}
          >
            {teamUnavailableDetail || teamUnavailableMessage}
          </VStateSurface>
        </main>
      ) : (
        <main className={styles.teamUnavailableSurface} aria-label={teamWorkspaceUnavailableTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
            title={teamWorkspaceUnavailableTitle}
            tone="unavailable"
            facts={[
              { key: "team", label: lang === "zh" ? "团队" : "Team", value: selectedTeamReference?.name ?? effectiveTeamId },
              { key: "detail", label: lang === "zh" ? "详情" : "Details", value: teamDetailLoadMode },
              { key: "status", label: lang === "zh" ? "状态" : "Status", value: lang === "zh" ? "失败" : "failed" },
            ]}
            actions={(
              <VButton type="button" variant="secondary" onPress={() => void teamDetailQuery.refetch()} isDisabled={teamDetailQuery.isFetching}>
                <RefreshCw size={14} />
                {teamDetailQuery.isFetching ? (lang === "zh" ? "刷新中" : "Refreshing") : (lang === "zh" ? "刷新详情" : "Refresh details")}
              </VButton>
            )}
          >
            {teamWorkspaceUnavailableDetail || teamWorkspaceUnavailableMessage}
          </VStateSurface>
        </main>
      )}
    </VDenseOpsPage>
    );
  }


  const {
    renderResearchStageAgentSummary,
    renderResearchStageAgentPanel,
    renderTeamMemoryIndex,
    renderResearchCanvasReadOnlyPanel,
    renderTeamNodeBindingPanel,
    renderKnowledgeCollectionCompletionFlowPanel,
    renderAiSearchSourceScopePanel,
    renderResearchLoopPanel,
    renderExperimentPlanningLedgerPanel,
  } = createTeamsWorkspacePanelRenderers({
    lang,
    selectedTeam,
    selectedTeamMemoryMembers,
    selectedTeamKnowledgeRoute,
    selectedTeamGraphRoute,
    researchStageAgentBindingsByStage,
    agentSummaryQuery,
    selectedNode,
    activeAgents,
    validation,
    styles,
    showNodeBindingPanel,
    nodeDraft,
    setNodeDraft,
    agentTeamMembership,
    durableCanvas,
    hasWritableCanvas,
    selectedTeamSaveCanvasPending,
    teamDetailQuery,
    applyNodeDraft,
    connectFromLead,
    unbindSelectedNode,
    deleteSelectedNode,
    researchWorkflowTeamSelected,
    researchCanvasReadOnly,
    selectedTeamKnowledgeCollectionWorkRun,
    sourceCollectionCompletionFlow,
    sourceCollectionCompletionFlowNodes,
    sourceCollectionStageModules,
    workflowIngestionToneBound,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageReturnRoute,
    openSourceCollectionStageAgentChat,
    sourceCollectionStepClassName,
    runKnowledgeCollectionCompletionAction,
    sourceCollectionCompletionActionDisabled,
    selectedTeamKnowledgeCollectionIngestPending,
    sourceCollectionActionDisabledTitle,
    sourceCollectionCompletionActionReadiness,
    aiSearchRuns,
    aiSearchRunsQuery,
    latestAiSearchRun,
    aiSearchRunTopic,
    setAiSearchRunTopic,
    aiSearchRunCanStart,
    selectedTeamStartAiSearchPending,
    selectedTeamStartAiSearchError,
    startAiSearchRunMutation,
    researchLoopStatus,
    researchLoopTemplatesPayload,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    sourceCollectionDraft,
    researchLoopStatusQuery,
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    materializeResearchLoopIterationDesignMutation,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    preferredExperimentMethod,
    searchParams,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedTeamCreateExperimentPlanPending,
    selectedTeamCreateExperimentPlanError,
    selectedTeamCreateExperimentPlanResult,
    selectedTeamMaterializeEngineeringProxyPending,
    selectedTeamMaterializeEngineeringProxyError,
    selectedTeamCompleteScientificHypothesisCandidateId,
    selectedTeamCompleteScientificHypothesisError,
    selectedTeamReviewExperimentHypothesisCandidateId,
    selectedTeamReviewExperimentHypothesisError,
    selectedTeamCreateExperimentHypothesisRevisionCandidateId,
    selectedTeamCreateExperimentHypothesisRevisionError,
    selectedTeamFreezeExperimentDesignPending,
    selectedTeamFreezeExperimentDesignError,
    selectedTeamFreezeExperimentDesignResult,
    selectedTeamRegisterExperimentBaselineArtifactPending,
    selectedTeamRegisterExperimentBaselineArtifactError,
    selectedTeamRegisterExperimentBaselineArtifactResult,
    selectedTeamRunExperimentSmokePending,
    selectedTeamRunExperimentSmokeError,
    selectedTeamRunExperimentSmokeResult,
    selectedTeamRegisterExperimentSmokeResultPending,
    selectedTeamRegisterExperimentSmokeResultError,
    selectedTeamRegisterExperimentSmokeResultResult,
    selectedTeamRegisterExperimentFullRunResultPending,
    selectedTeamRegisterExperimentFullRunResultError,
    selectedTeamRegisterExperimentFullRunResultResult,
    selectedTeamRequestExperimentKnowledgeIngestionPending,
    selectedTeamRequestExperimentKnowledgeIngestionError,
    selectedTeamRequestExperimentKnowledgeIngestionResult,
    createExperimentPlanFromWorkspace,
    materializeEngineeringProxyHypothesisFromWorkspace,
    completeScientificHypothesisFromWorkspace,
    reviewExperimentHypothesisFromWorkspace,
    createExperimentHypothesisRevisionFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    navigate,
  });

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
          onDraftChange: (patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch })),
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
          onAssignmentSelect: (assignmentId) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId })),
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


  if (researchCanvasVisible) {
    return (
      <VCanvasWorkbenchPage
        className={styles.route}
        hideHeader
        domainRecipe="teams-organization-workbench"
        layoutId={TEAMS_LAYOUT_ID}
        resize={teamsRailResize}
        shellTestId="team-shell-workspace"
        shellMode="canvas"
        ariaLabel={selectedTeamContextTitle}
        title={lang === "zh" ? "团队工作台" : "Team workbench"}
        rail={teamShellRail}
        toolbar={teamShellToolbar}
        canvasClassName="!border-0 !rounded-none"
        inspectorClassName="!border-0 !rounded-none !bg-transparent"
        canvas={(
          <TeamOrganizationCanvasSurface
            lang={lang}
            selectedTeam={selectedTeam}
            selectedTeamReferenceName={selectedTeamReference?.name}
            effectiveTeamId={effectiveTeamId}
            teamDetailLoadMode={teamDetailLoadMode}
            researchTeamId={RESEARCH_TEAM_ID}
            canvas={canvas}
            displayCanvasNodes={displayCanvasNodes}
            visibleEdges={visibleEdges}
            selectedNodeId={selectedNodeId}
            activeAgents={activeAgents}
            agentDisplay={agentDisplayInfo}
            researchCanvasReadOnly={researchCanvasReadOnly}
            researchCanvasAutoLayoutActive={researchCanvasAutoLayoutActive}
            showCommunicationEdges={showCommunicationEdges}
            organizationEdgeCount={organizationEdges.length}
            communicationEdgeCount={communicationEdges.length}
            communicationEdgeHint={communicationEdgeHint}
            communicationEdgeButtonLabel={communicationEdgeButtonLabel}
            saveLabel={saveLabel}
            hasWritableCanvas={hasWritableCanvas}
            linkedChatRoomId={linkedChatRoomId || ""}
            activeTeamMemberCount={activeTeamMemberCount}
            teamSyncPending={selectedTeamSyncPending}
            teamArchivePending={selectedTeamArchivePending}
            teamArchiveDisabledReason={selectedTeamArchiveDisabledReason || ""}
            conversationStatus={conversationProjection?.status}
            conversationMissingAgentCount={conversationProjection?.missingAgentCount}
            showTeamLoadingSurface={showTeamLoadingSurface}
            teamWorkspaceLoadingTitle={teamWorkspaceLoadingTitle}
            teamWorkspaceLoadingMessage={teamWorkspaceLoadingMessage}
            teamDetailPending={teamDetailQuery.isPending}
            teamCanvasPending={teamCanvasQuery.isPending}
            teamDetailError={teamDetailQuery.isError}
            teamCanvasError={teamCanvasQuery.isError}
            canvasViewportStyle={canvasViewportStyle}
            canvasFrameRef={canvasFrameRef}
            nodeToneClass={nodeTone}
            roleBadgeToneClass={roleBadgeTone}
            nodeActiveClassName={styles.nodeActive}
            nodeReadOnlyClassName={styles.nodeReadOnly}
            styles={styles}
            completionFlowSlot={renderKnowledgeCollectionCompletionFlowPanel()}
            teamWorkspaceRoute={teamWorkspaceRoute}
            teamChatRoomRoute={teamChatRoomRoute}
            onSelectNode={setSelectedNodeId}
            onLayoutModeChange={setResearchCanvasLayoutMode}
            onToggleCommunicationEdges={() => setShowCommunicationEdges((current) => !current)}
            onAddNode={addNode}
            onArchiveTeam={() => selectedTeam?.teamId && archiveTeamMutation.mutate(selectedTeam.teamId)}
            onSyncRoom={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
            onNodePointerDown={startNodeDrag}
            onNodePointerMove={moveNodeDrag}
            onNodePointerUp={finishNodeDrag}
            onNodePointerCancel={finishNodeDrag}
          />
        )}
        inspector={(
        <aside
          className={[
            styles.inspector,
            researchWorkflowTeamSelected ? styles.researchInspector : "",
            "min-h-0 h-full flex-1 !border-0 !rounded-none",
          ].filter(Boolean).join(" ")}
          data-vui-region="teams-inspector"
        >
          <div className={styles.inspectorHeader}>
            <strong>
              {researchCanvasReadOnly
                ? (lang === "zh" ? "组织画布" : "Organization canvas")
                : (lang === "zh" ? "节点绑定" : "Node binding")}
            </strong>
            {validation && !validation.valid ? <AlertTriangle size={16} /> : researchCanvasReadOnly ? <Eye size={16} /> : <Link2 size={16} />}
          </div>
          <div className={styles.inspectorBody}>
            {renderTeamsInspectorSharedPanels()}
            </div>
        </aside>
        )}
      />
    );
  }

  return (
    <VBoardWorkbenchPage
      className={styles.route}
      hideHeader
      domainRecipe="teams-organization-workbench"
      layoutId={TEAMS_LAYOUT_ID}
      resize={teamsRailResize}
      shellTestId="team-shell-workspace"
      shellMode="board"
      ariaLabel={selectedTeamContextTitle}
      title={lang === "zh" ? "团队工作台" : "Team workbench"}
      rail={teamShellRail}
      toolbar={teamShellToolbar}
      boardClassName="!p-0"
      board={(
        <aside
          className="min-h-0 w-full flex-1 border-0 bg-transparent"
          data-vui-region="teams-inspector"
        >
          <div className={[
            challengeCupResearchTeamSelected ? styles.challengeWorkspaceBody : styles.inspectorBody,
            styles.teamShellBoardBody,
          ].filter(Boolean).join(" ")}>
            {/* Board mode: preview-aligned research board (CTA + 3-column kanban). */}
            <TeamResearchBoardPrimarySurface
              lang={lang}
              researchCanvasVisible={researchCanvasVisible}
              researchWorkflowTeamSelected={researchWorkflowTeamSelected}
              showResearchOverview={showResearchOverview}
              workflowPending={teamWorkflowQuery.isPending}
              workflowReady={Boolean(teamWorkflow)}
              overviewSlot={renderResearchOverviewSurface()}
              launcherSlot={renderResearchStageLauncher("interactive")}
            />
            {selectedTeam && !challengeCupResearchTeamSelected ? renderTeamMemoryIndex() : null}
            {renderTeamsInspectorSharedPanels()}
            </div>
        </aside>
      )}
    />
  );
}
