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
import { useSourceCollectionPresentation } from "./teams/useSourceCollectionPresentation";
import {
  buildSourceCollectionBoardChrome,
  buildSourceCollectionCompletionFlowNodes,
  buildSourceCollectionStageModules,
  buildSourceCollectionStandaloneStageModules,
  type SourceCollectionStageModule,
  type SourceCollectionCompletionFlowNode,
} from "./teams/source-collection/stageModulesModel";
import {
  buildSourceCollectionWriteMutationSurface,
  buildTeamsRouteMutationSurface,
} from "./teams/teamMutationSurface";
import {
  sourceCollectionActionDisabledTitle as sourceCollectionActionDisabledTitlePure,
  sourceCollectionActionReadinessOf,
  sourceCollectionLoadingChrome,
} from "./teams/source-collection/actionChrome";
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
  splitDraftList,
  workflowIngestionStatusLabel,
  type SourceCollectionDraft,
  type SourceCollectionMode,
  type SourceCollectionStorageArtifacts,
  type SourceCollectionStorageOpenTarget,
} from "./teams/source-collection/presentationModel";
import { createTeamsWorkspacePanelRenderers } from "./teams/teamsWorkspacePanelRenderers";
import { createSourceCollectionInjectRenderers } from "./teams/teamSourceCollectionInjectRenderers";
import { createResearchWorkflowSurfaceRenderers } from "./teams/teamResearchWorkflowSurfaceRenderers";

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
import { TeamResearchBoardPrimarySurface } from "./teams/TeamResearchBoardPrimarySurface";
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

  const {
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
    renderSourceCollectionSearchBrief,
    renderSourceCollectionManualWritebackPanel,
    renderSourceCollectionControlsPanel,
    renderSourceCollectionActiveStagePanel,
    runSourceCollectionProjectReset,
  } = createSourceCollectionInjectRenderers({
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
  });

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
  // Runtime summary is optional for SC active-work overlay; keep a stable empty query shape.
  const runtimeSummaryQuery = { data: undefined as RuntimeSummary | undefined };
  const {
    sourceCollectionSummary,
    sourceCollectionSummaryRun,
    sourceCollectionSummaryRunId,
    sourceCollectionActionRunId,
    sourceCollectionPhaseCloseGate,
    sourceCollectionSummaryStageRound,
    sourceCollectionStageRound,
    sourceCollectionStageCards,
    sourceCollectionStageCardById,
    experimentPlanningStatus,
    sourceCollectionRecords,
    sourceCollectionAssignments,
    sourceCollectionRunStatus,
    sourceCollectionSearchPlanRef,
    aiSearchRuns,
    researchLoopTemplatesPayload,
    researchLoopStatus,
    latestAiSearchRun,
    aiSearchRunCanStart,
    selectedSourceCollectionAssignment,
    selectedSourceCollectionQueries,
    sourceCollectionFindingRunOptions,
    sourceCollectionFindingAssignments,
    sourceCollectionFindingQueries,
    sourceCollectionCanStart,
    researchStageCanLaunch,
    sourceCollectionResetResearchProjectId,
    sourceCollectionResetAvailable,
    sourceCollectionPromptCachePolicy,
    sourceCollectionPromptCachePolicyRef,
    sourceCollectionPromptCacheStatus,
    sourceCollectionPromptCacheMode,
    sourceCollectionPromptCacheRequirement,
    sourceCollectionOutputHasRecord,
    selectedTeamInitialSourceCollectionSearchResult,
    selectedSourceCollectionSearchExecutionResult,
    selectedSourceCollectionSearchAccepted,
    runtimeSourceCollectionActiveWorkRun,
    summarySourceCollectionActiveWorkRun,
    selectedSourceCollectionActiveWorkRun,
    sourceCollectionSummaryStorageArtifacts,
    selectedSourceCollectionStorageArtifacts,
    openSourceCollectionStorageTarget,
    sourceCollectionRunSummary,
    sourceCollectionOpenAssignments,
    sourceCollectionOpenAssignmentCount,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceManifestCandidates,
    teamWorkflowCandidatesById,
    sourceCollectionRunCandidates,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionCandidateRunId,
    selectedSourceCollectionCandidateStorageArtifacts,
    selectSourceCollectionCandidate,
    sourceCollectionCandidateCardKeyDown,
    sourceCollectionCandidatesByRecordId,
    sourceCollectionRecordProvenances,
    sourceCollectionRecordSourceCategories,
    sourceCollectionFilteredRecords,
    sourceCollectionRunCandidateSourceCategories,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionSummaryCounts,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionRecordMissingSourceCount,
    sourceCollectionRunCandidateCount,
    sourceCollectionRecordFilterCounts,
    sourceCollectionCandidateFilterCounts,
    sourceCollectionReviewableRunCandidates,
    sourceCollectionRunReviewableCandidateCount,
    sourceCollectionRunAssessedCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionRunNeedsRevisionCount,
    sourceCollectionEvidenceLedgerSummaries,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    sourceCollectionCollectedCount,
    sourceCollectionRunSummaryHasRecordCount,
    sourceCollectionSummaryHasRecordCount,
    sourceCollectionRunSummaryHasAssignmentCounts,
    sourceCollectionCandidateListDataLoading,
    sourceCollectionRecordsDataLoading,
    sourceCollectionAssignmentsDataLoading,
    sourceCollectionCollectionProjection,
    sourceCollectionExtractionProjection,
    sourceCollectionCandidateProjection,
    sourceCollectionScreeningProjection,
    sourceCollectionGraphProjection,
    sourceCollectionMemoryProjection,
    sourceCollectionExcludedSourceCount,
    sourceCollectionStageSummaryCandidateCount,
    sourceCollectionCandidateProjectionFallbackCount,
    sourceCollectionProjectedCollectedCount,
    sourceCollectionProjectedCandidateCount,
    sourceCollectionProjectedAssessedCount,
    sourceCollectionProjectedApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionQueryCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionSourceQualityLoading,
    sourceCollectionGraphDataLoading,
    sourceCollectionKnowledgeIngestionDataLoading,
    sourceCollectionActionInitialDataPending,
    sourceCollectionActionDataError,
    sourceCollectionSourceQualityDataError,
    sourceCollectionGraphDataError,
    sourceCollectionKnowledgeIngestionDataError,
    sourceCollectionScreeningDataLoading,
    sourceCollectionActionReadiness,
    sourceCollectionActionDisabledTitle,
    sourceCollectionCountText,
    sourceCollectionCountWithUnit,
    sourceCollectionCollectedCountText,
    sourceCollectionProjectedCollectedCountText,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionQueryDataLoading,
    sourceCollectionQueryCountText,
    sourceCollectionCollectedCountLabel,
    sourceCollectionProjectedCollectedCountLabel,
    sourceCollectionSearchOpenAssignmentCountLabel,
    sourceCollectionDownstreamOpenAssignmentCountLabel,
    sourceCollectionQueryCountLabel,
    sourceCollectionCollectedRunSummaryText,
    sourceCollectionAssignmentRunSummaryText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedCandidateCountText,
    sourceCollectionCoverageBoundCandidateCount,
    sourceCollectionCurrentCandidateCount,
    sourceCollectionCurrentCandidateCountText,
    sourceCollectionProjectedCandidateCountLabel,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionDisplayedCandidateFilterCounts,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionExtractionRecoveryCoverage,
    sourceCollectionExtractionRecoveryClosure,
    sourceCollectionExtractionSourceVerificationCount,
    sourceCollectionUnverifiableCandidateIds,
    sourceCollectionExtractionMissingEvidenceAnchorCount,
    sourceCollectionExtractionAgentMaterialCount,
    sourceCollectionExtractionNeedsAgentMaterial,
    sourceCollectionExtractionRecoveryMissingCount,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionExtractionCanProceedAfterExclusions,
    sourceCollectionExtractionProceedableSummary,
    sourceCollectionApprovedCount,
    sourceCollectionStageFocusLabel,
    sourceCollectionRunStatusValue,
    sourceCollectionAcceptedBackgroundActive,
    canRecordSourceCollectionOutput,
    canExecuteSourceCollectionSearch,
    sourceCollectionAcceptedBackgroundFailed,
    sourceCollectionOperationFailed,
    sourceCollectionDisplayState,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    knowledgeStewardPackCount,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionProjectedStewardPackCount,
    sourceCollectionProjectedFormalKnowledgeCount,
    sourceCollectionDefaultKnowledgeBaseId,
    sourceCollectionPrecheckCandidateCount,
    sourceCollectionIngestCandidateCount,
    sourceCollectionCanBuildGraph,
    sourceCollectionSearchActionReadiness,
    sourceCollectionCandidateExtractionActionReadiness,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionGraphActionReadiness,
    sourceCollectionMemoryActionReadiness,
    sourceCollectionCompletionActionReadiness,
    sourceCollectionLoopStartsNewRun,
    sourceCollectionLoopStartReadiness,
    sourceCollectionLoopActionReadiness,
    sourceCollectionMemoryActionDisabled,
    sourceCollectionMemoryActionLabel,
    sourceCollectionCompletionActionDisabled,
    sourceCollectionCompletionActionLabel,
    sourceCollectionLoopActionDisabled,
    sourceCollectionLoopActionLabel,
    sourceCollectionGraphActionDisabled,
    sourceCollectionGraphActionLabel,
    sourceCollectionScreeningDisabled,
    sourceCollectionScreeningForceRescreen,
    sourceCollectionScreeningButtonText,
    sourceCollectionScreeningButtonTitle,
    sourceCollectionScreeningStatusText,
    sourceCollectionCandidateExtractionButtonText,
    sourceCollectionStageForPanel,
    selectSourceCollectionStage,
    scrollSourceCollectionPanelIntoView,
    openSourceCollectionScreeningPanel,
    runSourceCollectionScreeningAction,
    excludeUnverifiableSourceCollectionCandidates,
    openSourceCollectionCandidatePanel,
    runSourceCollectionCandidateExtractionAction,
    runSourceCollectionGraphAction,
    startKnowledgeCollectionCompletionForRun,
    runKnowledgeCollectionCompletionAction,
    runKnowledgeCollectionLoopAction,
    runSourceCollectionSearchFromHeader,
    runSourceCollectionCollectionAction,
    sourceCollectionConsoleState,
    sourceCollectionConsoleStatusText,
    sourceCollectionDecisionText,
    sourceCollectionStepStatusText,
    sourceCollectionStageProjectionSyncing,
    sourceCollectionStageProjectionLabel,
    sourceCollectionStageLaunchActive,
    sourceCollectionStageFormalRetryRequired,
    sourceCollectionStageLaunchSummary,
    sourceCollectionStageDisplayState,
    sourceCollectionStageDisplayStatus,
    sourceCollectionStageDisplaySummary,
    sourceCollectionStepClassName,
    sourceCollectionSearchStepState,
    sourceCollectionScreeningFallbackStepState,
    sourceCollectionScreeningStepStateRaw,
    sourceCollectionScreeningStepState,
    sourceCollectionCandidateFallbackStepState,
    sourceCollectionCandidateStepStateRaw,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionGraphFallbackStepState,
    sourceCollectionGraphStepState,
    sourceCollectionMemoryFallbackStepState,
    sourceCollectionMemoryStepState,
    sourceCollectionExtractionStepState,
    sourceCollectionCollectionActionLabel,
    sourceCollectionCollectionActionReadiness,
    sourceCollectionStageTaskActionLabel,
    sourceCollectionStageTaskActionReadiness,
    sourceCollectionStageActionLabelFor,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionFindingDisplayLoading,
    sourceCollectionFindingDisplayState,
    sourceCollectionExtractionDisplayLoading,
    sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayLoading,
    sourceCollectionRelationsDisplayState,
    sourceCollectionIngestionDisplayLoading,
    sourceCollectionIngestionDisplayState,
    sourceCollectionSourceSyncStatusText,
    sourceCollectionCandidateSyncStatusText,
    sourceCollectionExtractionLoadingMetric,
    sourceCollectionExtractionMaterialMetric,
    sourceCollectionExtractionLoadingOutputLabel,
    sourceCollectionIngestionReadyForExperiment,
    sourceCollectionExperimentPlanningRoute,
    selectedResearchProjectSourceCollectionResetPending,
    selectedResearchProjectSourceCollectionResetError,
    selectedTeamStartResearchStagePending,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
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
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    selectedTeamStartSourceCollectionPending,
    selectedTeamStartSourceCollectionError,
    selectedTeamStartSourceCollectionResult,
    selectedTeamStartSourceCollectionStageTaskPending,
    selectedTeamStartSourceCollectionStageTaskError,
    sourceCollectionStageSessionTaskPendingStageId,
    selectedTeamRecordSourceCollectionOutputPending,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamExecuteSourceCollectionSearchPending,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamExtractSourceCollectionCandidatesPending,
    selectedTeamExtractSourceCollectionCandidatesError,
    selectedTeamExtractSourceCollectionCandidatesResult,
    selectedSourceCollectionStorageOpenPending,
    selectedSourceCollectionStorageOpenResult,
    selectedSourceCollectionStorageOpenError,
    selectedTeamStartAiSearchPending,
    selectedTeamStartAiSearchError,
    selectedTeamStartAiSearchResult,
    sourceCollectionLoadingText,
    sourceCollectionDataSyncText,
    sourceCollectionLoadingSummary,
    sourceCollectionActionLoadingReason,
    sourceCollectionActionErrorReason,
    sourceCollectionActionNoRunReason,
    sourceCollectionActionNoInputReason,
    sourceCollectionActionBusyReason,
    selectedTeamBuildCandidateGraphPending,
    selectedTeamBuildCandidateGraphError,
    selectedTeamKnowledgePrecheckPending,
    selectedTeamKnowledgePrecheckError,
    selectedTeamKnowledgeIngestionActiveWorkRun,
    selectedTeamKnowledgeIngestionLatestWorkRun,
    selectedTeamKnowledgeCollectionWorkRun,
    selectedTeamKnowledgeCollectionSourceRunId,
    selectedTeamKnowledgeCollectionMatchesSelectedRun,
    selectedTeamKnowledgeCollectionWorkRunStatus,
    selectedTeamKnowledgeCollectionFlowStatus,
    selectedTeamKnowledgeCollectionCompleted,
    selectedTeamKnowledgeCollectionCompletedForSelectedRun,
    selectedTeamKnowledgeCollectionIngestPending,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamPlanPaperNoteChunksError,
    selectedTeamAssessSourceQualityPending,
    selectedTeamAssessSourceQualityError,
    selectedTeamAssessSourceQualityBatchPending,
    selectedTeamAssessSourceQualityBatchError,
    selectedTeamSourceQualityPending,
    selectedTeamSourceQualityError,
    selectedTeamSourceQualityBatchResult,
    sourceCollectionQualityBatchFeedback,
  } = useSourceCollectionPresentation({
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
    runtimeSummaryQuery,
    sourceCollectionSummaryQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionRuns,
    sourceCollectionRunsQuery,
    sourceCollectionWorkspaceSelected,
    teamWorkflowSourceQualityEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionDraft,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    selectedSourceCollectionStageId,
    setSelectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionFocusedPanelId,
    setSourceCollectionFocusedPanelId,
    activeSourceCollectionResearchProjectId,
    sourceCollectionNeedsCandidateList,
    experimentPlanningStatusQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    aiSearchRunsQuery,
    aiSearchRunTopic,
    resetResearchProjectSourceCollectionMutation,
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
    startSourceCollectionRunMutation,
    startSourceCollectionStageSessionTaskMutation,
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    startAiSearchRunMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
    planPaperNoteChunksMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    queryClient,
    requestedSourceCollectionStage: requestedSourceCollectionStage ?? null,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
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
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionPendingStageTaskIds,
    selectResearchWorkspaceView,
    launchResearchStage,
    styles,
  });

  const sourceCollectionStageModules = buildSourceCollectionStageModules({
    lang,
    selectedSourceCollectionRun,
    selectedSourceCollectionStageId,
    sourceCollectionProjectedCollectedCountLabel,
    sourceCollectionProjectedCollectedCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionProjectedCandidateCountLabel,
    sourceCollectionProjectedCandidateCountText,
    sourceCollectionCurrentCandidateCountText,
    sourceCollectionQueryCountLabel,
    sourceCollectionQueryCountText,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionFindingDisplayLoading,
    sourceCollectionExtractionDisplayLoading,
    sourceCollectionRelationsDisplayLoading,
    sourceCollectionIngestionDisplayLoading,
    sourceCollectionScreeningDataLoading,
    sourceCollectionLoadingSummary,
    sourceCollectionDataSyncText,
    sourceCollectionSourceSyncStatusText,
    sourceCollectionCandidateSyncStatusText,
    sourceCollectionCollectionProjection,
    sourceCollectionExtractionProjection,
    sourceCollectionGraphProjection,
    sourceCollectionMemoryProjection,
    sourceCollectionFindingDisplayState,
    sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayState,
    sourceCollectionIngestionDisplayState,
    sourceCollectionSearchStepState,
    sourceCollectionExtractionStepState,
    sourceCollectionGraphStepState,
    sourceCollectionMemoryStepState,
    sourceCollectionExtractionNeedsAgentMaterial,
    sourceCollectionExtractionAgentMaterialCount,
    sourceCollectionExtractionCanProceedAfterExclusions,
    sourceCollectionExtractionProceedableSummary,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionExtractionLoadingMetric,
    sourceCollectionExtractionMaterialMetric,
    sourceCollectionExtractionLoadingOutputLabel,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionProjectedFormalKnowledgeCount,
    sourceCollectionProjectedStewardPackCount,
    sourceCollectionPrecheckCandidateCount,
    knowledgePendingReviewCount,
    sourceCollectionIngestionReadyForExperiment,
    sourceCollectionCollectionActionLabel,
    sourceCollectionCandidateExtractionButtonText,
    sourceCollectionGraphActionLabel,
    sourceCollectionMemoryActionLabel,
    selectedTeamExtractSourceCollectionCandidatesPending,
    selectedTeamSourceQualityPending,
    sourceCollectionExperimentPlanningRoute,
    sourceCollectionStageFocusLabel,
    selectedTeamKnowledgeCollectionWorkRun: selectedTeamKnowledgeCollectionWorkRun as any,
    sourceCollectionStageLaunchActive,
    sourceCollectionStageLaunchSummary,
    sourceCollectionStageUserSummary,
    sourceCollectionStageDisplayState,
    sourceCollectionStageDisplayStatus,
    sourceCollectionStepStatusText,
    sourceCollectionStageActionLabelFor,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionActionDisabledTitle,
    startSourceCollectionStageSessionTask,
    openSourceCollectionStage,
    openSourceCollectionStageAgentChat,
    navigate,
  });
  const { sourceCollectionBoardCurrentModule, sourceCollectionBoardNextStepLabel } = buildSourceCollectionBoardChrome({
    lang,
    sourceCollectionStageModules,
    sourceCollectionStageFocusLabel,
  });
  const sourceCollectionCompletionFlow = selectedTeamKnowledgeCollectionWorkRun?.flowVisualization ?? null;
  const sourceCollectionCompletionFlowNodes = buildSourceCollectionCompletionFlowNodes({
    selectedTeamKnowledgeCollectionWorkRun: selectedTeamKnowledgeCollectionWorkRun as any,
    sourceCollectionStageModules,
  });
  const sourceCollectionStandaloneStageModules = buildSourceCollectionStandaloneStageModules({
    lang,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionActionDisabledTitle,
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
  const sourceCollectionStartResult = selectedTeamStartSourceCollectionResult as any;
  const sourceCollectionOverviewPlan: TeamSourceCollectionOverviewPlan | null = sourceCollectionStartResult ? {
    planId: sourceCollectionStartResult.searchPlan.planId,
    seeds: sourceCollectionStartResult.searchPlan.querySeeds.join(" / "),
    promptCache: `${sourceCollectionPromptCacheStatusLabel(sourceCollectionStartResult.promptCachePolicy.gate.status, lang)} · ${sourceCollectionStartResult.promptCachePolicy.promptCacheMode}`,
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
  const sourceCollectionOutputResult = selectedTeamRecordSourceCollectionOutputResult as any;
  const sourceCollectionOverviewResult: TeamSourceCollectionOverviewResult | null = sourceCollectionOutputResult ? {
    title: lang === "zh" ? "已回写" : "Written",
    detail: `${sourceCollectionOutputResult.output.createdRecords.length} DataRecord / ${sourceCollectionOutputResult.imported.length} candidate`,
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

  const {
    researchWorkflowStatusText,
    renderResearchWorkflowModules,
    renderResearchWorkflowPanel,
    renderTeamCommunicationPanel,
    renderTeamsInspectorSharedPanels,
  } = createResearchWorkflowSurfaceRenderers({
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
  });

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
