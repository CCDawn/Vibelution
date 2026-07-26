import "../design/route-css/teams.tailwind.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, ArrowLeft, Bot, CheckCircle2, Eye, Link2, MessageSquare, Play, Plus, RefreshCw, Save, Search, Send, Settings2, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { PaneResizeHandle } from "../components/layout/PaneResizeHandle";
import { type PaneSpec } from "../components/layout/paneLayoutPersistence";
import { usePersistedPaneResize } from "../components/layout/usePersistedPaneResize";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { createLazyNamedTeamPanel } from "./teams/lazyTeamPanel";
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
  sourceCollectionModeForTeam,
  sourceCollectionPromptCacheModelDisplay,
  sourceCollectionPromptCacheStatusLabel,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusLabel,
  sourceCollectionSimpleRecordStatusLabel,
  sourceCollectionStatusLabel,
  sourceCollectionStorageArtifactsForRun,
  sourceCollectionStorageTargetForRef,
  sourceCollectionStorageTargetLabel,
  splitDraftList,
  workflowIngestionStatusLabel,
  type SourceCollectionDraft,
  type SourceCollectionMode,
  type SourceCollectionStorageArtifacts,
  type SourceCollectionStorageOpenTarget,
} from "./teams/source-collection/presentationModel";
import {
  CANVAS_VIEWPORT_HEIGHT,
  CANVAS_VIEWPORT_WIDTH,
  autoLayoutResearchCanvasNodes,
  canvasStyleScale,
  canvasViewStyle,
  edgeLine,
  isCommunicationEdge,
  nextNodeId,
  teamCanvasNodeStyle,
  type CanvasFrameSize,
  type CanvasViewportStyle,
  type ResearchCanvasLayoutMode,
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
import { ResearchProjectSwitcher } from "./teams/research-projects/ResearchProjectSwitcher";
import {
  SOURCE_COLLECTION_DEFAULT_ROLES,
  SOURCE_COLLECTION_TEAM_AGENT_ROLES,
  isAiSearchScopeTeam,
  isChallengeCupResearchWorkflowTeam,
  isEvolutionSystemTeam,
  isKnowledgeExpansionWorkflowTeam,
  isResearchWorkflowTeam,
  sourceCollectionAgentRolesForTeam,
  sourceCollectionWorkflowKindForTeam,
  sourceCollectionWorkflowPurposeForTeam,
  systemManagedTeamArchiveReason,
} from "./teams/teamKindModel";
import { fetchJson } from "../api/client";
import { kernelTaskCenterHref } from "../api/kernel";
import {
  PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT,
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  projectAgentBusEventsForTeam,
  revokeProjectAgentBusMessage,
  sendTeamProjectBusMessage,
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
  ExperimentMethodId,
  RuntimeSummary,
  Team,
  TeamCanvasNode,
  TeamListPayload,
  TeamOrganizationCanvas,
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
import type { ExperimentPlanMethodRequest } from "./TeamExperimentMethodPanel";
import type { TeamSourceCollectionStageAgentCard, TeamSourceCollectionStageAgentTone } from "./TeamSourceCollectionStageAgentsPanel";
import type { TeamSourceCollectionRunSwitcherRun } from "./TeamSourceCollectionRunSwitcherPanel";
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
import type { TeamSourceCollectionFilterOption } from "./TeamSourceCollectionResultControls";
import type { TeamSourceCollectionStorageAction } from "./TeamSourceCollectionStorageActionsPanel";
import type { TeamWorkflowCandidatePreviewItem } from "./TeamWorkflowCandidatePreviewPanel";
import type { ResearchMemoryContextSummary } from "./teams/ResearchMemoryEvidencePanel";
import {
  SOURCE_COLLECTION_SOURCE_FILTERS,
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
  sourceCollectionSourceFilterLabel,
  sourceCollectionSourceTypeLabel,
  type SourceCollectionCandidateProvenance,
  type SourceCollectionEvidenceLedgerSummary,
  type SourceCollectionSourceFilter,
} from "./teams/source-collection/evidenceModel";
import {
  deriveSourceCollectionDisplayState,
  selectDefaultSourceCollectionRun,
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunHasUsableRecords,
  sourceCollectionRunLabel,
  sourceCollectionRunOptionLabel,
  sourceCollectionRunRecordCount,
  sourceCollectionRunsForTeam,
  sourceCollectionRunTitleLabel,
  sourceCollectionStableCountText,
  translateResearchPhrase,
  type SourceCollectionStepState,
} from "./teams/source-collection/runModel";
import {
  sourceCollectionCompletionFlowNodeState,
  sourceCollectionNonNegativeCount,
  sourceCollectionPhaseCloseGateForRun,
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
  resolveResearchSecondaryStatusQueryEnabled,
  resolveSourceCollectionRunsQueryEnabled,
  resolveTeamCanvasQueryEnabled,
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
  sourceCollectionRunRefetchInterval,
  teamConversationStatusLabel,
  workRunNumber,
  workRunString,
  workflowCoordinationChannelLabel,
  workflowCoordinationStatusLabel,
  workflowStateLabel,
} from "./teams/workflowPresentation";
import { workflowGraphLayout } from "./TeamWorkflowGraphLayout";
import {
  AI_SEARCH_TEAM_ID,
  KNOWLEDGE_EXPANSION_TEAM_ID,
  RESEARCH_TEAM_ID,
  TEAM_PICKER_TEAM_IDS,
  TEAM_ORGANIZATION_CANVAS_KIND,
  canvasFromKnownTeamId,
  canvasFromTeam,
  canvasFromTeamOrFallback,
  memberCanvasFromTeam,
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

/** One shared async pack for Teams panel UI (see teams/README.md). */
const loadTeamSecondaryPanels = () => import("./teams/teamSecondaryPanels");

const TeamMemoryIndexPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamMemoryIndexPanel");
const TeamAiSearchWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamAiSearchWorkspacePanel");
const TeamResearchStageAgentPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageAgentPanel");
const TeamResearchStageAgentSummary = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageAgentSummary");
const TeamResearchStageLauncherPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageLauncherPanel");
const TeamResearchStageStandalonePagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageStandalonePagePanel");
const TeamResearchLoopPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchLoopPanel");
const TeamExperimentPlanningLedgerPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamExperimentPlanningLedgerPanel");
// TeamExperimentMethodPanel is mounted inside TeamExperimentPlanningLedgerPanel (same secondary pack).
const TeamSourceCollectionActiveStagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionActiveStagePanel");
const TeamSourceCollectionPhaseCloseGatePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionPhaseCloseGatePanel");
const TeamSourceCollectionStageAgentsPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionStageAgentsPanel");
const TeamSourceCollectionRunSwitcherPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionRunSwitcherPanel");
const TeamSourceCollectionFindingDetailsPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionFindingDetailsPanel");
const TeamSourceCollectionCandidatePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionCandidatePanel");
const TeamSourceCollectionConversationPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionConversationPanel");
const TeamSourceCollectionControlsPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionControlsPanel");
const TeamSourceCollectionExtractionRecoveryPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionExtractionRecoveryPanel");
const TeamSourceCollectionGraphPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionGraphPanel");
const TeamSourceCollectionManualWritebackPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionManualWritebackPanel");
const TeamSourceCollectionMemoryPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionMemoryPanel");
const TeamSourceCollectionScreeningPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningPanel");
const TeamKnowledgeCollectionCompletionFlowPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamKnowledgeCollectionCompletionFlowPanel");
const TeamSourceCollectionConversationWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionConversationWorkspacePanel");
const TeamSourceCollectionScreeningWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningWorkspacePanel");
const TeamSourceCollectionExtractionRecoveryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionExtractionRecoveryWorkspacePanel");
const TeamSourceCollectionCandidateWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionCandidateWorkspacePanel");
const TeamSourceCollectionGraphWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionGraphWorkspacePanel");
const TeamSourceCollectionMemoryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionMemoryWorkspacePanel");
const TeamSourceCollectionSourceDetailPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionSourceDetailPanel");
const TeamSourceCollectionStandaloneStagePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionStandaloneStagePanel");
const TeamSourceCollectionRunSettingsPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionRunSettingsPanel");
const TeamSourceCollectionFilterBar = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionFilterBar");
const TeamSourceCollectionPagination = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionPagination");
const TeamSourceCollectionStorageActionsPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionStorageActionsPanel");
const TeamWorkflowCandidatePreviewPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowCandidatePreviewPanel");
const TeamsSourceCollectionPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamsSourceCollectionPanel");
const ResearchMemoryEvidencePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "ResearchMemoryEvidencePanel");
const TeamWorkflowGraphView = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowGraphView");
const TeamWorkflowCandidateGraphStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowCandidateGraphStatusPanel");
const TeamWorkflowCoordinationStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowCoordinationStatusPanel");
const TeamWorkflowKnowledgeIngestionStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowKnowledgeIngestionStatusPanel");
const TeamWorkflowModelEvidenceStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowModelEvidenceStatusPanel");
const TeamWorkflowPaperNoteChunkStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowPaperNoteChunkStatusPanel");
const TeamWorkflowSourceQualityStatusPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamWorkflowSourceQualityStatusPanel");

const TEAMS_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.teams;
const TEAMS_INSPECTOR_PANE: PaneSpec = {
  id: "inspector",
  defaultWidth: 360,
  minWidth: 320,
  maxWidth: 480,
};
const TEAMS_PANES: PaneSpec[] = [TEAMS_INSPECTOR_PANE];

type TeamsRouteProps = {
  forcedTeamId?: string;
  forcedResearchWorkspaceView?: ResearchWorkspaceView;
  sourceCollectionStandalone?: boolean;
};

type TeamWorkflowKnowledgeIngestionPrecheckPayload = {
  candidate: TeamWorkflowCandidate;
  validation: { valid: boolean; issues: Array<Record<string, unknown>> };
  precheck: {
    status: string;
    generatedByAgent: string;
    selectedCandidateCount: number;
    filteredCandidateCount?: number;
    candidateIds?: string[];
    candidateGraphId?: string;
    officialBoundary: {
      writesOfficialKnowledge: boolean;
      writesOfficialRag: boolean;
      writesOfficialGraph: boolean;
      requiresReviewBeforeOfficialSync?: boolean;
    };
  };
  status: TeamWorkflowKnowledgeIngestionStatus;
  workflow: TeamWorkflowOrchestration;
};

type NodeDraft = {
  label: string;
  role: string;
  purpose: string;
  agentId: string;
};

type SourceCollectionOutputDraft = {
  assignmentId: string;
  sourceType: string;
  title: string;
  sourceRef: string;
  rawLocation: string;
  summary: string;
  notes: string;
};

type DataProcessingRecordListPayload = {
  schemaVersion: number;
  runId: string;
  records: DataProcessingRecord[];
  summary: Record<string, unknown> & {
    recordCount?: number;
    sourceTypeCounts?: Record<string, number>;
    recordStatusCounts?: Record<string, number>;
  };
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

type SourceCollectionStageAgentChatStatus = "ready" | "loading" | "error" | "repair";

const SOURCE_COLLECTION_STAGE_AGENT_KEYS: Record<SourceCollectionStageModuleId, string[]> = {
  finding: ["source_finder"],
  extraction: ["source_extractor"],
  relations: ["source_relation_mapper"],
  ingestion: ["source_ingestor"],
};
const SOURCE_COLLECTION_STAGE_TERMINAL_TASK_STATUSES = new Set([
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "interrupted",
  "needs_review",
]);
const SOURCE_COLLECTION_STAGE_TERMINAL_PROJECTION_STATUSES = new Set([
  "agent_blocked",
  "agent_done_artifact_pending",
  "agent_interrupted",
  "artifact_ready_agent_blocked",
  "artifact_ready_no_latest_agent_task",
  "closed_loop",
]);

const SOURCE_COLLECTION_STAGE_CHAT_LABELS: Record<SourceCollectionStageModuleId, { zh: string; en: string }> = {
  finding: { zh: "资料寻找 Agent 私聊", en: "Source finder Agent chat" },
  extraction: { zh: "资料提炼 Agent 私聊", en: "Source extraction Agent chat" },
  relations: { zh: "资料关系整理 Agent 私聊", en: "Source relation Agent chat" },
  ingestion: { zh: "资料入库 Agent 私聊", en: "Source ingestion Agent chat" },
};

function parseSourceCollectionStageModuleId(value: string | null): SourceCollectionStageModuleId | null {
  if (value === "search") {
    return "finding";
  }
  if (value === "extract") {
    return "extraction";
  }
  if (value === "review") {
    return "extraction";
  }
  if (value === "ingest") {
    return "ingestion";
  }
  if (value === "collection") {
    return "finding";
  }
  if (value === "candidate" || value === "screening") {
    return "extraction";
  }
  if (value === "graph") {
    return "relations";
  }
  if (value === "memory") {
    return "ingestion";
  }
  return value === "finding" || value === "extraction" || value === "relations" || value === "ingestion"
    ? value
    : null;
}

type TeamWorkflowSourceCollectionStorageOpenPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  target: SourceCollectionStorageOpenTarget;
  path: string;
  openedPath: string;
  targetExists: boolean;
  storageArtifacts: SourceCollectionStorageArtifacts;
};

type SourceCollectionSearchExecutionEvent = {
  eventId: string;
  eventType: string;
  status: string;
  title: string;
  summary: string;
  agentRole: string;
  agentId: string;
  assignmentId: string;
  queryId: string;
  query: string;
  sourceType: string;
  refs: string[];
  rawLocation: string;
  storageRefs: string[];
  createdAt: string;
};

type TeamWorkflowSourceCollectionSearchExecutionPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  status: string;
  executionMode?: "background" | string;
  accepted?: boolean;
  provider: string;
  executedQueryCount: number;
  skippedQueryCount: number;
  failedQueryCount: number;
  resultCount: number;
  recordCount: number;
  createdUniqueRecordCount?: number;
  outputCount: number;
  importedCount: number;
  skippedDuplicateCount?: number;
  filteredExcludedCount?: number;
  duplicateSourceKeys?: string[];
  excludedSourceKeys?: string[];
  remainingQueryCount?: number;
  nextRunnableQueryIds?: string[];
  hasMore?: boolean;
  run: TeamWorkflowSourceCollectionRunStartPayload["run"];
  runStatus: DataProcessingStatus;
  sourceCollectionSummary?: {
    assignmentCount: number;
    openAssignmentCount: number;
    searchAssignmentCount: number;
    searchOpenAssignmentCount: number;
    collectionAssignmentCount: number;
    collectionOpenAssignmentCount: number;
    downstreamAssignmentCount: number;
    downstreamOpenAssignmentCount: number;
  };
  storageArtifacts: SourceCollectionStorageArtifacts;
  assignments: TeamWorkflowSourceCollectionRunStartPayload["assignments"];
  outputs: Array<DataProcessingCollectionOutputPayload["output"]>;
  createdRecords: DataProcessingCollectionOutputPayload["createdRecords"];
  imported: TeamWorkflowDataRecordSourceCandidateImportPayload[];
  executionEvents: SourceCollectionSearchExecutionEvent[];
  activeWorkRun?: {
    runId: string;
    status: string;
    currentPhase: string;
    currentTask?: string;
    summary?: string;
    openAssignmentCount?: number;
    searchAssignmentCount?: number;
    searchOpenAssignmentCount?: number;
    collectionAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
    recordCount?: number;
    queryCount?: number;
    error?: string;
    errorType?: string;
    storagePath?: string;
    updatedAt?: string;
  };
  boundaries: {
    externalSearchTriggered: boolean;
    externalSearchQueued?: boolean;
    metadataOnlyDownload: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  nextActions: string[];
};

type SourceCollectionSummaryPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  status: string;
  run?: DataProcessingRunListPayload["runs"][number] | Record<string, unknown>;
  runStatus?: DataProcessingStatus;
  scope?: {
    kind?: string;
    runId?: string;
    includesHistorical?: boolean;
    eligibleForPhaseCloseGate?: boolean;
  };
  summary?: {
    recordCount?: number;
    rawRecordCount?: number;
    excludedSourceCount?: number;
    assignmentCount?: number;
    openAssignmentCount?: number;
    outputCount?: number;
    sourceCandidateCount?: number;
    assessedSourceCandidateCount?: number;
    approvedSourceCandidateCount?: number;
    graphNodeCount?: number;
    stewardPackCount?: number;
    formalKnowledgeSyncCount?: number;
  };
  stageCards?: SourceCollectionStageCardProjection[];
  stageCardSummary?: ResearchStageRound["sourceCollectionStageCardSummary"];
  phaseCloseGate?: SourceCollectionPhaseCloseGate;
  latestTasks?: Record<string, SourceCollectionStageCardProjection["latestTask"]>;
  stageRound?: Partial<ResearchStageRound>;
  activeWorkRun?: WorkRunSnapshot | Record<string, unknown>;
  storageArtifacts?: Partial<SourceCollectionStorageArtifacts>;
  updatedAt?: string;
};

type ResearchStageRoundStartPayload = {
  created: boolean;
  continued?: boolean;
  stageRound: ResearchStageRound;
  phase: ResearchStagePhaseStatus;
  status: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  sourceCollectionRun?: TeamWorkflowSourceCollectionRunStartPayload;
  sourceCollectionSearchExecution?: TeamWorkflowSourceCollectionSearchExecutionPayload;
  run?: TeamWorkflowSourceCollectionRunStartPayload["run"];
  searchPlan?: TeamWorkflowSourceCollectionRunStartPayload["searchPlan"];
  assignments?: TeamWorkflowSourceCollectionRunStartPayload["assignments"];
  assignmentCount?: number;
  promptCachePolicy?: TeamWorkflowSourceCollectionRunStartPayload["promptCachePolicy"];
  continuedSourceRunRef?: {
    runId: string;
    status: string;
    recordCount: number;
    assignmentCount: number;
    openAssignmentCount: number;
    searchOpenAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
    queryCount?: number;
    planId?: string;
    externalSearchTriggered?: boolean;
    message?: string;
  };
  boundaries: ResearchStageRoundStatusPayload["boundaries"];
  nextActions?: string[];
};

type TeamWorkflowPaperNoteChunkPlanPayload = {
  candidate: TeamWorkflowCandidate;
  chunkPlan: {
    planId: string;
    status: string;
    chunkCount: number;
  };
  workflow: TeamWorkflowOrchestration;
  nextActions: string[];
};

type TeamWorkflowSourceQualityAssessmentPayload = {
  candidate: TeamWorkflowCandidate;
  assessment: {
    assessmentId: string;
    decision: string;
    scores: {
      relevance: number;
      reliability: number;
      accessibility: number;
      extractionReadiness: number;
      overall: number;
    };
  };
  status: TeamWorkflowSourceQualityStatus;
  workflow: TeamWorkflowOrchestration;
  nextActions: string[];
};

type TeamWorkflowSourceQualityBatchAssessmentPayload = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  batchRunId: string;
  executionMode: string;
  status: string;
  assessedByAgent: string;
  summary: {
    targetCandidateCount: number;
    assessedCandidateCount: number;
    approvedCandidateCount: number;
    needsRevisionCandidateCount: number;
    rejectedCandidateCount: number;
    failedCandidateCount: number;
    skippedCandidateCount: number;
  };
  assessments: Array<{
    candidateId: string;
    title: string;
    assessmentId: string;
    decision: string;
    overallScore: number;
    requiredFixes: string[];
    riskFlags: string[];
    currentState: string;
    qualityStatus: string;
    assessedAt: string;
  }>;
  skippedCandidates: Array<{ candidateId: string; title?: string; reason: string }>;
  failedCandidates: Array<{ candidateId: string; error: string }>;
  sourceQualityStatus: TeamWorkflowSourceQualityStatus;
  workflow: TeamWorkflowOrchestration;
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  nextActions: string[];
  updatedAt: string;
};

type NodeDragState = {
  nodeId: string;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  scale: number;
  moved: boolean;
};

function researchStageStartFeedbackText(payload: ResearchStageRoundStartPayload, lang: "zh" | "en", stageLabel?: string) {
  const label = stageLabel || payload.stageRound.stageType;
  const sourceRef = payload.continuedSourceRunRef;
  if (payload.created === false && payload.continued && sourceRef) {
    if (lang === "zh") {
      return `已复用正在运行的${label}第 ${payload.stageRound.roundNumber} 轮：${sourceCollectionRunLabel(sourceRef.runId)} · ${sourceRef.recordCount} 条记录 / ${sourceRef.openAssignmentCount} 个待回写任务。要创建全新批次，请点“开启新一轮”。`;
    }
    return `Reused active ${label} round ${payload.stageRound.roundNumber}: ${sourceCollectionRunLabel(sourceRef.runId)} · ${sourceRef.recordCount} records / ${sourceRef.openAssignmentCount} open tasks. Use "New round" to create a fresh batch.`;
  }
  if (lang === "zh") {
    return `已进入 ${label} 第 ${payload.stageRound.roundNumber} 轮`;
  }
  return `Entered ${label} round ${payload.stageRound.roundNumber}`;
}

function roleBadgeTone(node: TeamCanvasNode, displayTone = "") {
  if (node.status === "stale") {
    return styles.nodeRoleBadgeStale;
  }
  if (!node.agentId) {
    return styles.nodeRoleBadgeOpen;
  }
  const key = `${node.role} ${node.purpose} ${displayTone}`.toLowerCase();
  if (key.includes("ceo") || key.includes("lead") || key.includes("负责人")) {
    return styles.nodeRoleBadgeLead;
  }
  if (key.includes("advisor") || key.includes("organization") || key.includes("顾问")) {
    return styles.nodeRoleBadgeAdvisor;
  }
  if (key.includes("steward") || key.includes("capability") || key.includes("能力") || key.includes("管家")) {
    return styles.nodeRoleBadgeSteward;
  }
  if (key.includes("research") || key.includes("科研")) {
    return styles.nodeRoleBadgeResearch;
  }
  if (key.includes("self") || key.includes("进化")) {
    return styles.nodeRoleBadgeSelf;
  }
  return styles.nodeRoleBadgeGeneral;
}

function teamNodeFunctionLabel(node: TeamCanvasNode, displayLabel: string | undefined, lang: "zh" | "en") {
  const role = String(node.role || "").trim();
  const purpose = String(node.purpose || "").trim();
  const key = `${role} ${purpose}`.toLowerCase();
  if (key.includes("ceo") || key.includes("lead") || key.includes("负责人")) {
    return lang === "zh" ? "科研负责人" : "Research lead";
  }
  if (key.includes("organization") || key.includes("advisor") || key.includes("组织顾问") || key.includes("顾问")) {
    return lang === "zh" ? "组织顾问" : "Organization advisor";
  }
  if (key.includes("capability") || key.includes("steward") || key.includes("能力管家") || key.includes("管家")) {
    return lang === "zh" ? "能力管家" : "Capability steward";
  }
  if (purpose) {
    return purpose;
  }
  return displayLabel || role || (lang === "zh" ? "未绑定" : "Unbound");
}

function canvasNodeStatusLabel(node: TeamCanvasNode | null | undefined, lang: "zh" | "en") {
  if (!node) {
    return lang === "zh" ? "未选择" : "not selected";
  }
  const status = String(node.status || "").trim().toLowerCase();
  const role = String(node.role || "").trim();
  if (role === "knowledge_steward" && node.agentId) {
    return lang === "zh" ? "专属管理员" : "dedicated admin";
  }
  if (status === "stale") {
    return lang === "zh" ? "引用失效" : "stale reference";
  }
  if (node.agentId || status === "bound") {
    return lang === "zh" ? "已绑定" : "bound";
  }
  return lang === "zh" ? "未绑定" : "unbound";
}

function nodeTone(node: TeamCanvasNode) {
  if (node.status === "stale") {
    return styles.nodeStale;
  }
  if (node.agentId) {
    return styles.nodeBound;
  }
  return styles.nodeOpen;
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

function workflowQualityTone(value: string) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("approved") || normalized.includes("ready") || normalized.includes("prefiltered")) {
    return styles.workflowTagReady;
  }
  if (normalized.includes("invalid") || normalized.includes("broken") || normalized.includes("rejected")) {
    return styles.workflowTagDanger;
  }
  if (normalized.includes("revision") || normalized.includes("pending")) {
    return styles.workflowTagWarning;
  }
  return styles.workflowTagNeutral;
}

function workflowIngestionTone(value: string) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "ready" || normalized === "operational") {
    return styles.workflowTagReady;
  }
  if (normalized === "blocked" || normalized === "needs_revision") {
    return styles.workflowTagDanger;
  }
  if (normalized === "needs_review" || normalized === "needs_evidence" || normalized === "needs_screening" || normalized === "pending") {
    return styles.workflowTagWarning;
  }
  return styles.workflowTagNeutral;
}

function isWorkflowCandidateGraphPayload(value: unknown): value is TeamWorkflowCandidateGraphPayload {
  if (!isRecord(value)) {
    return false;
  }
  return (
    Array.isArray(value.nodes)
    && Array.isArray(value.edges)
    && Array.isArray(value.missingLinks)
    && Array.isArray(value.unreviewedNodes)
    && isRecord(value.officialBoundary)
    && isRecord(value.summary)
  );
}

function workflowCandidateGraphFromCandidate(candidate: TeamWorkflowCandidate | null | undefined) {
  const graph = candidate?.metadata?.graph;
  return isWorkflowCandidateGraphPayload(graph) ? graph : null;
}

function sourceCandidateHasCompletedExtraction(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const extraction = isRecord(metadata.sourceExtraction) ? metadata.sourceExtraction : {};
  return candidate.candidateType === "source_manifest" && extraction.status === "extracted" && Array.isArray(extraction.pageAnchors);
}

function candidatePaperNoteChunkPlanSummary(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const plan = isRecord(metadata.paperNoteChunkPlan) ? metadata.paperNoteChunkPlan : null;
  if (!plan) {
    return null;
  }
  return {
    planId: String(plan.planId || ""),
    status: String(plan.status || ""),
    chunkCount: Number(plan.chunkCount || 0),
    completedChunkCount: Number(plan.completedChunkCount || 0),
    needsRevisionChunkCount: Number(plan.needsRevisionChunkCount || 0),
  };
}

function latestWorkflowCandidate(candidates: TeamWorkflowCandidate[]) {
  return [...candidates].sort((left, right) => {
    const rightTime = new Date(right.updatedAt || right.createdAt || "").getTime();
    const leftTime = new Date(left.updatedAt || left.createdAt || "").getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  })[0] ?? null;
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
  const {
    layoutRef: teamsLayoutRef,
    widths: teamsPaneWidths,
    draggingPaneId: teamsDraggingPaneId,
    startResize: startTeamsInspectorResize,
    onResizeKeyDown: onTeamsInspectorResizeKeyDown,
  } = usePersistedPaneResize({
    layoutId: TEAMS_LAYOUT_ID,
    panes: TEAMS_PANES,
    preserveMainMinWidth: 480,
  });
  const teamsInspectorWidth = teamsPaneWidths.inspector ?? TEAMS_INSPECTOR_PANE.defaultWidth;
  const teamsLayoutStyle = {
    ["--teams-inspector-width" as string]: `${teamsInspectorWidth}px`,
  } as CSSProperties;
  const requestedResearchViewParam = searchParams.get("researchView");
  const requestedResearchWorkspaceView = parseResearchWorkspaceView(searchParams.get("researchView"));
  const requestedSourceCollectionStage = parseSourceCollectionStageModuleId(searchParams.get("collectionStage"));
  const sourceCollectionStandalone =
    sourceCollectionStandaloneProp || requestedResearchWorkspaceView === "knowledge_collection" || requestedResearchViewParam === "source_collection";
  const stageStandaloneView: ResearchStageWorkspaceView | null =
    requestedResearchWorkspaceView === "experiment" || requestedResearchWorkspaceView === "iteration" ? requestedResearchWorkspaceView : null;
  const pageVisible = usePageVisibility();
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>({ label: "", role: "", purpose: "", agentId: "" });
  const [teamMessage, setTeamMessage] = useState("");
  const [teamInterrupt, setTeamInterrupt] = useState(false);
  const [teamTaskTopic, setTeamTaskTopic] = useState("");
  const [showCommunicationEdges, setShowCommunicationEdges] = useState(false);
  const [researchCanvasLayoutMode, setResearchCanvasLayoutMode] = useState<ResearchCanvasLayoutMode>("auto");
  const [researchWorkspaceView, setResearchWorkspaceView] = useState<ResearchWorkspaceView>(
    forcedResearchWorkspaceView ?? requestedResearchWorkspaceView ?? "overview",
  );
  const [challengeTeamSurface, setChallengeTeamSurface] = useState<"workspace" | "progress">("workspace");
  const [preferredExperimentMethod, setPreferredExperimentMethod] = useState<ExperimentMethodId | "">("");
  const [sourceCollectionDraft, setSourceCollectionDraft] = useState<SourceCollectionDraft>({
    title: "神经算法资料搜索批次",
    topic: "神经预测编码",
    goal: "搜集可追踪的神经科学资料，用来支撑神经网络算法假设。",
    querySeeds: "预测编码皮层层级\n突触可塑性学习规则\n神经门控注意机制",
    inputRefs: "",
    searchLanguages: "en\nzh",
    sourceTypes: "paper\nreview\ndataset",
    maxResultsPerQuery: 8,
    collectionMode: "mixed",
    localScanRoots: SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS,
  });
  const [aiSearchRunTopic, setAiSearchRunTopic] = useState("AI 最新动态");
  const [selectedSourceCollectionRunId, setSelectedSourceCollectionRunId] = useState("");
  const [sourceCollectionOutputDraft, setSourceCollectionOutputDraft] = useState<SourceCollectionOutputDraft>({
    assignmentId: "",
    sourceType: "paper",
    title: "",
    sourceRef: "",
    rawLocation: "",
    summary: "",
    notes: "",
  });
  const [experimentBaselineArtifactDraft, setExperimentBaselineArtifactDraft] = useState<ExperimentBaselineArtifactDraft>({
    artifactPath: "",
    reproductionCommand: "",
    evaluationCommand: "",
    metricValue: "",
  });
  const [experimentSmokeResultDraft, setExperimentSmokeResultDraft] = useState<ExperimentSmokeResultDraft>({
    status: "needs_review",
    metricValue: "",
    baselineMetricValue: "",
    delta: "",
    resultPath: "",
    logRef: "",
    evaluationCommand: "",
    notes: "",
  });
  const [experimentFullRunResultDraft, setExperimentFullRunResultDraft] = useState<ExperimentFullRunResultDraft>({
    status: "needs_review",
    metricValue: "",
    baselineMetricValue: "",
    smokeMetricValue: "",
    delta: "",
    resultPath: "",
    logRef: "",
    configPath: "",
    reproductionCommand: "",
    evaluationCommand: "",
    notes: "",
  });
  const [experimentKnowledgeIngestionDraft, setExperimentKnowledgeIngestionDraft] = useState<ExperimentKnowledgeIngestionDraft>({
    knowledgeBaseId: "research-team-experiment-kb",
    targetDomain: "挑战杯实验结果",
    title: "",
    summary: "",
    notes: "",
    wakeStewardAgent: true,
  });
  const [selectedResearchLoopTemplateId, setSelectedResearchLoopTemplateId] = useState("algorithm_model_experiment");
  const [researchLoopCreateDraft, setResearchLoopCreateDraft] = useState<ResearchLoopCreateDraft>({
    researchQuestion: "",
    constraints: "",
    datasetRefs: "",
    environmentRefs: "",
  });
  const [researchLoopEvidenceDraft, setResearchLoopEvidenceDraft] = useState<ResearchLoopEvidenceDraft>({
    evidenceType: "",
    status: "needs_review",
    summary: "",
    metricName: "",
    metricValue: "",
    baselineMetricValue: "",
    delta: "",
    artifactRef: "",
    datasetRefs: "",
    environmentRefs: "",
    logRefs: "",
    commandPreview: "",
  });
  const [researchLoopDecisionDraft, setResearchLoopDecisionDraft] = useState<ResearchLoopDecisionDraft>({
    decision: "needs_more_evidence",
    rationale: "",
    nextTemplateId: "",
    nextActions: "",
  });
  const [selectedSourceCollectionStageId, setSelectedSourceCollectionStageId] = useState<SourceCollectionStageModuleId>(
    requestedSourceCollectionStage ?? "finding",
  );
  const [sourceCollectionStageSyncUntilMs, setSourceCollectionStageSyncUntilMs] = useState(0);
  const [sourceCollectionPendingStageTaskIds, setSourceCollectionPendingStageTaskIds] = useState<Partial<Record<SourceCollectionStageModuleId, string[]>>>({});
  const [sourceCollectionResultPageByStage, setSourceCollectionResultPageByStage] = useState<Record<SourceCollectionStageModuleId, number>>({
    finding: 1,
    extraction: 1,
    relations: 1,
    ingestion: 1,
  });
  const [sourceCollectionExpandedPanelId, setSourceCollectionExpandedPanelId] = useState("");
  const [sourceCollectionFocusedPanelId, setSourceCollectionFocusedPanelId] = useState("");
  const [sourceCollectionSourceFilter, setSourceCollectionSourceFilter] = useState<SourceCollectionSourceFilter>("all");
  const [selectedSourceCollectionCandidateId, setSelectedSourceCollectionCandidateId] = useState("");
  const [nodePositionDrafts, setNodePositionDrafts] = useState<Record<string, { x: number; y: number }>>({});
  const [canvasFrameSize, setCanvasFrameSize] = useState<CanvasFrameSize>({ width: CANVAS_VIEWPORT_WIDTH, height: CANVAS_VIEWPORT_HEIGHT });
  const [lockedCanvasViewportStyle, setLockedCanvasViewportStyle] = useState<CanvasViewportStyle | null>(null);
  const sourceCollectionControlPanelRef = useRef<HTMLElement | null>(null);
  const canvasFrameRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<NodeDragState | null>(null);
  const dragFrameRef = useRef(0);

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
  const selectedVisibleTeamId = selectedTeamId && visibleTeamIds.has(selectedTeamId) ? selectedTeamId : "";
  const fallbackVisibleTeamId = visibleTeams[0]?.teamId ?? "";
  const effectiveTeamId = resolveTeamsRouteEffectiveTeamId({
    forcedTeamId,
    selectedTeamId: selectedVisibleTeamId,
    requestedTeamId,
    requestedAgentTeamId,
    visibleTeamIds,
    fallbackTeamId: fallbackVisibleTeamId,
  });
  useEffect(() => {
    setPreferredExperimentMethod("");
  }, [effectiveTeamId]);
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
  const aiSearchScopeTeamSelected = isAiSearchScopeTeam(selectedTeam);
  const researchCanvasReadOnly = researchWorkflowTeamSelected && researchWorkspaceView === "canvas";
  const sourceCollectionWorkspaceSelected =
    researchWorkflowTeamSelected && (sourceCollectionStandalone || researchWorkspaceView === "source_collection" || researchWorkspaceView === "knowledge_collection");
  const teamCanvasQueryEnabled = resolveTeamCanvasQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
  });
  const teamCanvasQuery = useQuery({
    queryKey: queryKeys.teamCanvas(effectiveTeamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamOrganizationCanvas>(`/api/teams/${encodeURIComponent(effectiveTeamId)}/canvas`, { signal }),
    enabled: teamCanvasQueryEnabled,
    staleTime: 10_000,
  });
  const sourceCollectionNeedsCandidateList =
    sourceCollectionWorkspaceSelected && selectedSourceCollectionStageId !== "finding";
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
  const sourceCollectionStageWritebackSyncActive = sourceCollectionStageSyncUntilMs > Date.now();
  const sourceCollectionPendingStageTaskIdList = useMemo(
    () => Object.values(sourceCollectionPendingStageTaskIds).flat().filter((taskId): taskId is string => Boolean(taskId)),
    [sourceCollectionPendingStageTaskIds],
  );
  const sourceCollectionStageWritebackAwaitingTask = sourceCollectionStageWritebackSyncActive && sourceCollectionPendingStageTaskIdList.length > 0;
  const aiSearchRunsQuery = useQuery({
    queryKey: queryKeys.teamAiSearchRuns(effectiveTeamId || "none", AI_SEARCH_RUN_PREVIEW_LIMIT),
    queryFn: ({ signal }) =>
      fetchJson<AiSearchRunListPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/ai-search-runs?limit=${AI_SEARCH_RUN_PREVIEW_LIMIT}`,
        { signal },
      ),
    enabled: Boolean(effectiveTeamId && aiSearchScopeTeamSelected),
  });

  useEffect(() => {
    if (forcedResearchWorkspaceView) {
      setResearchWorkspaceView(forcedResearchWorkspaceView);
      return;
    }
    if (requestedResearchWorkspaceView) {
      setResearchWorkspaceView(requestedResearchWorkspaceView);
    }
  }, [forcedResearchWorkspaceView, requestedResearchWorkspaceView]);
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
  });
  const experimentPlanningStatusQuery = useQuery({
    queryKey: experimentPlanningStatusQueryKey(effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ExperimentPlanningStatusPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/experiments/status`,
        { signal },
      ),
    enabled: researchSecondaryStatusQueryEnabled,
  });
  const experimentMethodCatalogQuery = useQuery({
    queryKey: experimentMethodCatalogQueryKey(effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ExperimentMethodCatalogPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/experiments/methods`,
        { signal },
      ),
    enabled: Boolean(
      effectiveTeamId
      && researchWorkflowTeamSelected
      && ["overview", "experiment"].includes(researchWorkspaceView)
      && !sourceCollectionStandalone
    ),
  });
  const researchLoopTemplatesQuery = useQuery({
    queryKey: researchLoopTemplatesQueryKey(effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ResearchLoopTemplatesPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/research-loop/templates`,
        { signal },
      ),
    enabled: researchSecondaryStatusQueryEnabled,
  });
  const researchLoopStatusQuery = useQuery({
    queryKey: researchLoopStatusQueryKey(effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<ResearchLoopStatusPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/research-loop/status`,
        { signal },
      ),
    enabled: researchSecondaryStatusQueryEnabled,
  });
  const sourceCollectionRunsQueryEnabled = resolveSourceCollectionRunsQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    sourceCollectionWorkspaceSelected,
  });
  const sourceCollectionRunsQuery = useQuery({
    queryKey: queryKeys.teamWorkflowSourceCollectionRuns(effectiveTeamId || "none", SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
    queryFn: ({ signal }) =>
      fetchJson<DataProcessingRunListPayload>(
        `/api/data-processing/runs?limit=${SOURCE_COLLECTION_RUN_PREVIEW_LIMIT}&teamId=${encodeURIComponent(effectiveTeamId)}&startedFrom=team_workflow_source_collection`,
        { signal },
      ),
    enabled: sourceCollectionRunsQueryEnabled,
    refetchInterval: (query) => {
      const payload = query.state.data as DataProcessingRunListPayload | undefined;
      const hasActiveRun = (payload?.runs ?? []).some((run) => ["collecting", "processing"].includes(String(run.status || "").toLowerCase()));
      return resolvePollingInterval(pageVisible, hasActiveRun ? 1500 : false);
    },
  });
  const linkedChatRoomId = selectedTeam?.linkedChatRoomId ?? "";
  const linkedRoomStatusForPolling = String(selectedTeam?.linkedChatRoom?.status || "").toLowerCase();
  const linkedChatRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(linkedChatRoomId || "none"),
    queryFn: ({ signal }) => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(linkedChatRoomId)}`, { signal }),
    enabled: Boolean(linkedChatRoomId && teamDetailQuery.data),
    refetchInterval: (query) => {
      const detail = query.state.data as ChatRoomDetail | undefined;
      return linkedRoomRefetchInterval(pageVisible, detail?.status || linkedRoomStatusForPolling);
    },
  });
  const durableCanvas = canvasFromTeamOrFallback(selectedTeam, teamCanvasQuery.data);
  const memberCanvas = useMemo(() => memberCanvasFromTeam(selectedTeam), [selectedTeam]);
  const knownTeamCanvas = useMemo(() => canvasFromKnownTeamId(effectiveTeamId), [effectiveTeamId]);
  const canvas = durableCanvas ?? memberCanvas ?? knownTeamCanvas;
  const hasWritableCanvas = Boolean(durableCanvas);
  const canvasNodes = useMemo(
    () =>
      (canvas?.nodes ?? []).map((node) => ({
        ...node,
        ...(nodePositionDrafts[node.id] ?? {}),
      })),
    [canvas, nodePositionDrafts],
  );
  const organizationEdges = useMemo(() => (canvas?.edges ?? []).filter((edge) => !isCommunicationEdge(edge)), [canvas]);
  const communicationEdges = useMemo(
    () => (canvas?.edges ?? []).filter((edge) => isCommunicationEdge(edge)),
    [canvas],
  );
  const autoLayoutCanvasNodes = useMemo(
    () => autoLayoutResearchCanvasNodes(canvasNodes, organizationEdges),
    [canvasNodes, organizationEdges],
  );
  const researchCanvasAutoLayoutActive = researchCanvasReadOnly && researchCanvasLayoutMode === "auto";
  const displayCanvasNodes = researchCanvasAutoLayoutActive ? autoLayoutCanvasNodes : canvasNodes;
  const selectedNode = displayCanvasNodes.find((node) => node.id === selectedNodeId) ?? displayCanvasNodes[0] ?? null;
  const visibleCommunicationEdges = useMemo(() => {
    if (!showCommunicationEdges) {
      return [];
    }
    if (!selectedNodeId) {
      return communicationEdges;
    }
    return communicationEdges.filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId);
  }, [communicationEdges, selectedNodeId, showCommunicationEdges]);
  const visibleEdges = useMemo(
    () => [...organizationEdges, ...visibleCommunicationEdges],
    [organizationEdges, visibleCommunicationEdges],
  );
  const sourceCollectionRuns = useMemo(
    () => sourceCollectionRunsForTeam(sourceCollectionRunsQuery.data, effectiveTeamId),
    [effectiveTeamId, sourceCollectionRunsQuery.data],
  );
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
  const sourceCollectionLatestRun = sourceCollectionRuns[0] ?? null;
  const sourceCollectionHistoricalRunWithRecords = sourceCollectionRuns.find(sourceCollectionRunHasUsableRecords) ?? null;
  const selectedSourceCollectionRun = selectDefaultSourceCollectionRun(sourceCollectionRuns, selectedSourceCollectionRunId);
  const sourceCollectionLatestRunIsEmpty = Boolean(
    sourceCollectionLatestRun
    && !sourceCollectionRunHasUsableRecords(sourceCollectionLatestRun),
  );
  const sourceCollectionShowingHistoricalRunByDefault = Boolean(
    !selectedSourceCollectionRunId
    && sourceCollectionLatestRunIsEmpty
    && sourceCollectionHistoricalRunWithRecords
    && selectedSourceCollectionRun?.runId === sourceCollectionHistoricalRunWithRecords.runId
    && sourceCollectionLatestRun?.runId !== sourceCollectionHistoricalRunWithRecords.runId,
  );
  const selectedSourceCollectionRunEffectiveId = selectedSourceCollectionRun?.runId ?? "";
  const sourceCollectionSummaryQuery = useQuery({
    queryKey: sourceCollectionSummaryQueryKey(effectiveTeamId || "none", selectedSourceCollectionRunEffectiveId || "latest"),
    queryFn: ({ signal }) => {
      const params = selectedSourceCollectionRunEffectiveId
        ? `?runId=${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}`
        : "";
      return fetchJson<SourceCollectionSummaryPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/source-collection/summary${params}`,
        { signal },
      );
    },
    enabled: Boolean(effectiveTeamId && sourceCollectionWorkspaceSelected),
    refetchInterval: (query) => {
      const payload = query.state.data as SourceCollectionSummaryPayload | undefined;
      const active = payload?.status === "active";
      return active
        ? resolvePollingInterval(pageVisible, 1500)
        : sourceCollectionStageWritebackRefetchInterval(pageVisible, payload, sourceCollectionStageWritebackSyncActive);
    },
  });
  const sourceCollectionFindingDetailsVisible = Boolean(
    sourceCollectionWorkspaceSelected
    && selectedSourceCollectionRunEffectiveId
    && selectedSourceCollectionStageId === "finding",
  );
  const sourceCollectionRecordsQueryEnabled = sourceCollectionFindingDetailsVisible;
  const sourceCollectionAssignmentsQueryEnabled = sourceCollectionFindingDetailsVisible;
  const sourceCollectionRunStatusQueryEnabled = sourceCollectionRecordsQueryEnabled || sourceCollectionAssignmentsQueryEnabled;
  const runtimeSummaryQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: ({ signal }) => fetchJson<RuntimeSummary>("/api/runtime/summary", { signal }),
    enabled: Boolean(researchWorkflowTeamSelected && researchWorkspaceView === "overview"),
    refetchInterval: (query) => {
      const runtime = query.state.data as RuntimeSummary | undefined;
      const active = sourceCollectionActiveWorkRunFromRuntime(runtime, selectedSourceCollectionRunEffectiveId);
      return resolvePollingInterval(pageVisible, active ? 1500 : false);
    },
  });
  const sourceCollectionRunStatusQuery = useQuery({
    queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) => fetchJson<DataProcessingStatus>(`/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/status`, { signal }),
    enabled: sourceCollectionRunStatusQueryEnabled,
    refetchInterval: (query) => {
      const status = query.state.data as DataProcessingStatus | undefined;
      return sourceCollectionRunRefetchInterval(pageVisible, status?.runStatus || "");
    },
  });
  const sourceCollectionRecordsQuery = useQuery({
    queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<DataProcessingRecordListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/records`,
        { signal },
      ),
    enabled: sourceCollectionRecordsQueryEnabled,
    refetchInterval: () => sourceCollectionRunRefetchInterval(
      pageVisible,
      sourceCollectionRunStatusQuery.data?.runStatus || sourceCollectionSummaryQuery.data?.runStatus?.runStatus || selectedSourceCollectionRun?.status || "",
    ),
  });
  const sourceCollectionAssignmentsQuery = useQuery({
    queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<DataProcessingCollectionAssignmentListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/collection-assignments`,
        { signal },
      ),
    enabled: sourceCollectionAssignmentsQueryEnabled,
    refetchInterval: () => sourceCollectionRunRefetchInterval(
      pageVisible,
      sourceCollectionRunStatusQuery.data?.runStatus || sourceCollectionSummaryQuery.data?.runStatus?.runStatus || selectedSourceCollectionRun?.status || "",
    ),
  });
  const autoCanvasViewportStyle = useMemo(() => canvasViewStyle(displayCanvasNodes, canvasFrameSize), [canvasFrameSize, displayCanvasNodes]);
  const canvasViewportStyle = lockedCanvasViewportStyle ?? autoCanvasViewportStyle;
  const canvasScale = canvasStyleScale(canvasViewportStyle);
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, selectedTeam?.teamId),
    [projectBusQuery.data, selectedTeam?.teamId],
  );

  useEffect(() => {
    if (requestedVisibleTeamId) {
      setSelectedTeamId(requestedVisibleTeamId);
      return;
    }
    if (requestedVisibleAgentTeamId) {
      setSelectedTeamId(requestedVisibleAgentTeamId);
      return;
    }
    if (selectedTeamId && !visibleTeamIds.has(selectedTeamId)) {
      setSelectedTeamId(fallbackVisibleTeamId);
      return;
    }
    if (!selectedTeamId && fallbackVisibleTeamId) {
      setSelectedTeamId(fallbackVisibleTeamId);
    }
  }, [fallbackVisibleTeamId, requestedVisibleAgentTeamId, requestedVisibleTeamId, selectedTeamId, visibleTeamIds]);

  useEffect(() => {
    if (requestedSourceCollectionStage) {
      setSelectedSourceCollectionStageId(requestedSourceCollectionStage);
    }
  }, [requestedSourceCollectionStage]);

  useEffect(() => {
    setSourceCollectionResultPageByStage({
      finding: 1,
      extraction: 1,
      relations: 1,
      ingestion: 1,
    });
  }, [selectedSourceCollectionRunEffectiveId, sourceCollectionSourceFilter]);

  useEffect(() => {
    if (selectedNode) {
      setNodeDraft({
        label: selectedNode.label,
        role: selectedNode.role,
        purpose: selectedNode.purpose,
        agentId: selectedNode.agentId,
      });
    }
  }, [selectedNode?.id]);

  useEffect(() => {
    setNodePositionDrafts({});
    dragStateRef.current = null;
    if (dragFrameRef.current) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = 0;
    }
  }, [selectedTeam?.teamId, canvas?.updatedAt]);

  useEffect(() => {
    setLockedCanvasViewportStyle(null);
  }, [selectedTeam?.teamId]);

  useEffect(() => {
    const element = canvasFrameRef.current;
    if (!element) {
      return;
    }
    const updateFrameSize = () => {
      setCanvasFrameSize({
        width: Math.max(420, Math.round(element.clientWidth)),
        height: Math.max(360, Math.round(element.clientHeight)),
      });
    };
    updateFrameSize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateFrameSize);
      return () => window.removeEventListener("resize", updateFrameSize);
    }
    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const archiveTeamMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`, {
        method: "DELETE",
      }),
    onSuccess: (team, teamId) => {
      setSelectedTeamId("");
      setSelectedNodeId("");
      setSearchParams({});
      void chatWorkspaceCache.afterTeamArchived(teamId, team.linkedChatRoomId || team.linkedChatRoom?.roomId);
    },
  });

  const saveCanvasMutation = useMutation({
    mutationFn: (nextCanvas: TeamOrganizationCanvas) =>
      fetchJson<TeamOrganizationCanvas>(`/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextCanvas),
      }),
    onSuccess: (canvas, variables) => {
      queryClient.setQueryData(queryKeys.teamCanvas(variables.teamId), canvas);
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const sendTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; content: string; interruptMode: string }) =>
      sendTeamProjectBusMessage(payload),
    onSuccess: (_payload, variables) => {
      if (variables.teamId === selectedTeamId) {
        setTeamMessage("");
      }
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const revokeTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId: payload.eventId,
        reason: "Revoked from Agent Center team broadcast history.",
      }),
    onSuccess: (_payload, variables) => {
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const syncTeamChatRoomMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}/chat-room/sync`, {
        method: "POST",
      }),
    onSuccess: (team) => {
      queryClient.setQueryData(queryKeys.team(team.teamId, "light"), team);
      queryClient.setQueryData(queryKeys.team(team.teamId, "full"), team);
      if (team.linkedChatRoom?.roomId) {
        void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
      } else {
        void chatWorkspaceCache.afterTeamChanged(team.teamId);
      }
    },
  });

  const repairChallengeCupTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<{ team: Team }>(`/api/teams/${encodeURIComponent(teamId)}/challenge-cup-agents/repair`, {
        method: "POST",
      }),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const repairKnowledgeExpansionTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<{ team: Team }>(`/api/teams/${encodeURIComponent(teamId)}/knowledge-expansion-agents/repair`, {
        method: "POST",
      }),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const seedSourceCollectionAgentSessionContextMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; stageId: SourceCollectionStageModuleId; agentId: string; agentRole: string }) =>
      fetchJson<TeamWorkflowSourceCollectionAgentSessionContextPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/agent-session-context`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageId: payload.stageId,
            agentId: payload.agentId,
            agentRole: payload.agentRole,
          }),
        },
      ),
  });

  const startSourceCollectionStageSessionTaskMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      runId: string;
      stageId: SourceCollectionStageModuleId;
      agentId: string;
      agentRole: string;
      returnTo: string;
      returnLabel: string;
      requestedByAgent: string;
      idempotencyKey: string;
    }) =>
      fetchJson<TeamWorkflowSourceCollectionStageSessionTaskPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/stage-session-tasks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageId: payload.stageId,
            agentId: payload.agentId,
            agentRole: payload.agentRole,
            returnTo: payload.returnTo,
            returnLabel: payload.returnLabel,
            requestedByAgent: payload.requestedByAgent,
            idempotencyKey: payload.idempotencyKey,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      setSelectedSourceCollectionRunId(payload.runId);
      setSourceCollectionStageSyncUntilMs(Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS);
      if (payload.taskId) {
        setSourceCollectionPendingStageTaskIds((current) => {
          const currentStageTaskIds = current[variables.stageId] ?? [];
          if (currentStageTaskIds.includes(payload.taskId)) {
            return current;
          }
          return {
            ...current,
            [variables.stageId]: [...currentStageTaskIds, payload.taskId],
          };
        });
      }
      void chatWorkspaceCache.afterDirectTurnAccepted(payload.sessionId);
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
    },
  });

  const startTeamRoundMutation = useMutation({
    mutationFn: (payload: { roomId: string; teamId: string; topic: string; mode: string; purpose: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${payload.roomId}/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: payload.topic,
          mode: payload.mode,
          purpose: payload.purpose,
          config: {
            source: "team_workspace",
            teamId: payload.teamId,
          },
        }),
      }),
    onSuccess: (room, variables) => {
      setTeamTaskTopic("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId);
    },
  });

  const startAiSearchRunMutation = useMutation({
    mutationFn: (payload: { teamId: string; topic: string }) =>
      fetchJson<AiSearchRun>(`/api/teams/${encodeURIComponent(payload.teamId)}/ai-search-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: payload.topic.trim() || "AI 最新动态",
          sourceLimit: 8,
          maxResultsPerQuery: 3,
          includeSignals: false,
        }),
      }),
    onSuccess: (_run, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamAiSearchRuns(variables.teamId, AI_SEARCH_RUN_PREVIEW_LIMIT) });
    },
  });

  const startSourceCollectionRunMutation = useMutation({
    mutationFn: (payload: { teamId: string; draft: SourceCollectionDraft }) => {
      const querySeeds = compactSourceCollectionQuerySeeds(payload.draft.topic, payload.draft.querySeeds);
      const workflowKind = sourceCollectionWorkflowKindForTeam(selectedTeam);
      const workflowPurpose = sourceCollectionWorkflowPurposeForTeam(selectedTeam);
      const collectionMode = sourceCollectionModeForTeam(selectedTeam, payload.draft);
      return fetchJson<TeamWorkflowSourceCollectionRunStartPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: payload.draft.title.trim() || (knowledgeExpansionWorkflowTeamSelected ? "Knowledge expansion source intake" : "Challenge Cup source collection"),
            topic: payload.draft.topic.trim(),
            goal: payload.draft.goal.trim(),
            ownerAgentId: sourceCollectionOwnerAgentId,
            requestedByAgent: sourceCollectionOwnerAgentId,
            workflowPurpose,
            workflowKind,
            collectionMode,
            agentRoles: sourceCollectionAgentRolesForTeam(selectedTeam),
            agentIds: sourceCollectionAgentIds,
            inputRefs: splitDraftList(payload.draft.inputRefs, 24),
            querySeeds,
            searchLanguages: splitDraftList(payload.draft.searchLanguages, 8),
            sourceTypes: splitDraftList(payload.draft.sourceTypes, 12),
            maxResultsPerQuery: payload.draft.maxResultsPerQuery,
            localScanScope: sourceCollectionLocalScanScopeForDraft(collectionMode, payload.draft),
            promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
            scope: {
              domain: knowledgeExpansionWorkflowTeamSelected ? "team knowledge expansion" : "neuroscience-inspired algorithm discovery",
              workflowStage: "knowledge_collection",
              workflowKind,
              workflowPurpose,
              collectionMode,
              uiEntry: knowledgeExpansionWorkflowTeamSelected ? "teams_knowledge_expansion_source_collection_panel" : "teams_research_source_collection_panel",
            },
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
      setSelectedSourceCollectionRunId(payload.run.runId);
      const firstAssignmentId = payload.assignments[0]?.assignmentId ?? "";
      setSourceCollectionOutputDraft((current) => ({
        ...current,
        assignmentId: firstAssignmentId || current.assignmentId,
      }));
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const startResearchStageRoundMutation = useMutation({
    mutationFn: (payload: { teamId: string; stageType: ResearchStageType; mode?: "continue_or_start" | "new_round"; draft: SourceCollectionDraft }) => {
      const querySeeds = compactSourceCollectionQuerySeeds(payload.draft.topic, payload.draft.querySeeds);
      return fetchJson<ResearchStageRoundStartPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/stage-rounds/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageType: payload.stageType,
            mode: payload.mode || "continue_or_start",
            title: payload.draft.title.trim() || "",
            topic: payload.draft.topic.trim(),
            goal: payload.draft.goal.trim(),
            ownerAgentId: sourceCollectionOwnerAgentId,
            requestedByAgent: sourceCollectionOwnerAgentId,
            agentRoles: SOURCE_COLLECTION_DEFAULT_ROLES,
            agentIds: sourceCollectionAgentIds,
            inputRefs: splitDraftList(payload.draft.inputRefs, 24),
            querySeeds,
            searchLanguages: splitDraftList(payload.draft.searchLanguages, 8),
            sourceTypes: splitDraftList(payload.draft.sourceTypes, 12),
            maxResultsPerQuery: payload.draft.maxResultsPerQuery,
            promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
            scope: {
              domain: "neuroscience-inspired algorithm discovery",
              workflowStage: payload.stageType,
              uiEntry: "teams_research_stage_launcher",
            },
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      const sourceRunId = payload.run?.runId || payload.stageRound.sourceRunIds?.[0] || "";
      const searchExecution = payload.sourceCollectionSearchExecution;
      if (sourceRunId) {
        setSelectedSourceCollectionRunId(sourceRunId);
        const firstAssignmentId = payload.assignments?.[0]?.assignmentId ?? "";
        if (firstAssignmentId) {
          setSourceCollectionOutputDraft((current) => ({
            ...current,
            assignmentId: firstAssignmentId,
          }));
        }
        if (searchExecution?.runStatus) {
          queryClient.setQueryData(queryKeys.dataProcessingRunStatus(sourceRunId), {
            ...searchExecution.runStatus,
            summary: {
              ...searchExecution.runStatus.summary,
              ...(searchExecution.sourceCollectionSummary ?? {}),
            },
          });
        } else if (payload.run) {
          queryClient.setQueryData(queryKeys.dataProcessingRunStatus(sourceRunId), {
            schemaVersion: 1,
            runId: payload.run.runId,
            profileId: payload.run.profileId,
            runStatus: payload.run.status,
            summary: payload.run.summary ?? {
              recordCount: 0,
              assignmentCount: payload.assignmentCount ?? payload.assignments?.length ?? 0,
              openAssignmentCount: payload.continuedSourceRunRef?.openAssignmentCount ?? 0,
              searchOpenAssignmentCount: payload.continuedSourceRunRef?.searchOpenAssignmentCount ?? 0,
              collectionOpenAssignmentCount: payload.continuedSourceRunRef?.collectionOpenAssignmentCount ?? 0,
              downstreamOpenAssignmentCount: payload.continuedSourceRunRef?.downstreamOpenAssignmentCount ?? 0,
              outputCount: 0,
              recordStatusCounts: {},
              sourceTypeCounts: {},
              assignmentStatusCounts: {},
            },
            nextActions: [],
            boundaries: {
              generic: true,
              writesFormalKnowledge: false,
              writesRag: false,
              writesKnowledgeGraph: false,
              requiresDownstreamPublisher: true,
            },
          });
        }
        const stageAssignments = searchExecution?.assignments ?? payload.assignments;
        if (stageAssignments) {
          queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(sourceRunId), {
            schemaVersion: 1,
            runId: sourceRunId,
            assignments: stageAssignments,
            summary: {
              assignmentCount: stageAssignments.length,
              assignmentStatusCounts: stageAssignments.reduce<Record<string, number>>((counts, assignment) => {
                counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
                return counts;
              }, {}),
            },
          });
        }
        if (sourceCollectionStandalone) {
          setResearchWorkspaceView("knowledge_collection");
        } else {
          navigate(researchSourceCollectionRoute(variables.teamId));
        }
        void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
        void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      } else if (variables.stageType === "experiment") {
        setResearchWorkspaceView("experiment");
      } else if (variables.stageType === "iteration") {
        setResearchWorkspaceView("iteration");
      }
    },
  });

  const createExperimentPlanMutation = useMutation({
    mutationFn: (payload: { teamId: string; stageRoundId?: string; title?: string; methodRequest?: ExperimentPlanMethodRequest }) =>
      fetchJson<ExperimentPlanCreatePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageRoundId: payload.stageRoundId || "",
            title: payload.title || "",
            createdByAgent: sourceCollectionOwnerAgentId,
            ...(payload.methodRequest ?? {}),
            notes: "Created from the experiment planning workspace. No training execution was triggered.",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const freezeExperimentDesignMutation = useMutation({
    mutationFn: (payload: { teamId: string; plan: ExperimentPlanRecord }) =>
      fetchJson<ExperimentDesignFreezePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/freeze`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frozenByAgent: sourceCollectionOwnerAgentId }),
        },
      ),
    onSuccess: (payload, variables) => {
      if (payload.experimentStatus) {
        queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.experimentStatus);
      }
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentBaselineArtifactMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentBaselineArtifactDraft;
    }) =>
      fetchJson<ExperimentBaselineArtifactRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/baseline-artifact`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            registeredByAgent: sourceCollectionOwnerAgentId,
            baselineName: payload.plan.experimentPlan.baseline || payload.plan.baselineSelection.baseline || "",
            datasetRef: payload.plan.experimentPlan.dataset || "",
            metricName: payload.plan.experimentPlan.metric || "",
            metricValue: payload.draft.metricValue.trim(),
            artifactPath: payload.draft.artifactPath.trim(),
            reproductionCommand: payload.draft.reproductionCommand.trim(),
            evaluationCommand: payload.draft.evaluationCommand.trim(),
            notes: "Registered from the experiment planning workspace. No training execution was triggered.",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentSmokeResultMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentSmokeResultDraft;
    }) =>
      fetchJson<ExperimentSmokeResultRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/smoke-result`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            recordedByAgent: sourceCollectionOwnerAgentId,
            status: payload.draft.status,
            metricName: payload.plan.experimentPlan.metric || "",
            metricValue: payload.draft.metricValue.trim(),
            baselineMetricValue: payload.draft.baselineMetricValue.trim(),
            delta: payload.draft.delta.trim(),
            resultPath: payload.draft.resultPath.trim(),
            logRef: payload.draft.logRef.trim(),
            evaluationCommand: payload.draft.evaluationCommand.trim(),
            notes: payload.draft.notes.trim() || "Registered from the experiment planning workspace. No training execution was triggered.",
            metadata: {
              enteredFrom: "teams_experiment_ledger",
              noTrainingExecution: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      setExperimentSmokeResultDraft((draft) => ({
        ...draft,
        metricValue: "",
        delta: "",
        resultPath: "",
        logRef: "",
        notes: "",
      }));
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentFullRunResultMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentFullRunResultDraft;
    }) =>
      fetchJson<ExperimentFullRunResultRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/full-run-result`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            recordedByAgent: sourceCollectionOwnerAgentId,
            status: payload.draft.status,
            metricName: payload.plan.experimentPlan.metric || "",
            metricValue: payload.draft.metricValue.trim(),
            baselineMetricValue: payload.draft.baselineMetricValue.trim(),
            smokeMetricValue: payload.draft.smokeMetricValue.trim(),
            delta: payload.draft.delta.trim(),
            resultPath: payload.draft.resultPath.trim(),
            logRef: payload.draft.logRef.trim(),
            configPath: payload.draft.configPath.trim(),
            reproductionCommand: payload.draft.reproductionCommand.trim(),
            evaluationCommand: payload.draft.evaluationCommand.trim(),
            notes: payload.draft.notes.trim() || "Registered from the experiment planning workspace. No full-run execution was triggered.",
            metadata: {
              enteredFrom: "teams_experiment_ledger",
              manualFullRunResult: true,
              noTrainingExecution: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      setExperimentFullRunResultDraft((draft) => ({
        ...draft,
        metricValue: "",
        delta: "",
        resultPath: "",
        logRef: "",
        configPath: "",
        notes: "",
      }));
      setExperimentKnowledgeIngestionDraft((draft) => ({
        ...draft,
        title: payload.plan.title || draft.title,
        summary:
          payload.fullRunResult.status === "passed"
            ? `${payload.fullRunResult.metricName || payload.plan.experimentPlan.metric || "metric"} = ${payload.fullRunResult.metricValue}`
            : draft.summary,
      }));
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const requestExperimentKnowledgeIngestionMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentKnowledgeIngestionDraft;
    }) =>
      fetchJson<ExperimentResultKnowledgeIngestionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/knowledge-ingestion-request`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requestedByAgent: sourceCollectionOwnerAgentId,
            stewardAgentId: sourceCollectionIngestorAgentId,
            knowledgeBaseId: payload.draft.knowledgeBaseId.trim() || `${payload.teamId}-challenge-cup-experiments`,
            targetDomain: payload.draft.targetDomain.trim() || "挑战杯实验结果",
            wakeStewardAgent: payload.draft.wakeStewardAgent,
            title: payload.draft.title.trim() || payload.plan.title || "",
            summary: payload.draft.summary.trim(),
            notes: payload.draft.notes.trim(),
            metadata: {
              enteredFrom: "teams_experiment_ledger",
              explicitUserBoundary: true,
              stewardReviewRequired: true,
              rawLogsStayReferenced: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
    },
  });

  const createResearchLoopMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord | null;
      templateId: string;
      draft: ResearchLoopCreateDraft;
    }) => {
      const selectedHypothesisIds = payload.plan?.hypothesisCandidateIds?.length
        ? payload.plan.hypothesisCandidateIds
        : payload.plan?.selectedHypotheses.map((candidate) => candidate.candidateId) ?? [];
      return fetchJson<ResearchLoopCreatePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            templateId: payload.templateId,
            title: payload.plan?.title || "",
            researchQuestion:
              payload.draft.researchQuestion.trim()
              || payload.plan?.goal
              || payload.plan?.topic
              || sourceCollectionDraft.goal,
            stageRoundId: payload.plan?.stageRoundId || experimentPlanningStatus?.latestExperimentRound?.stageRoundId || "",
            planId: payload.plan?.planId || "",
            targetRef: payload.plan?.planId || payload.plan?.stageRoundId || "",
            candidateIds: selectedHypothesisIds,
            datasetRefs: splitDraftList(payload.draft.datasetRefs, 24),
            environmentRefs: splitDraftList(payload.draft.environmentRefs, 24),
            constraints: payload.draft.constraints.trim(),
            createdByAgent: sourceCollectionOwnerAgentId,
            metadata: {
              enteredFrom: "teams_research_loop_panel",
              noSandboxRunner: true,
              noTrainingExecution: true,
            },
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      setResearchLoopEvidenceDraft((draft) => ({
        ...draft,
        evidenceType: payload.loop.readiness.missingEvidenceTypes[0] || payload.loop.readiness.requiredEvidenceTypes[0] || draft.evidenceType,
        metricName: variables.plan?.experimentPlan.metric || draft.metricName,
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
    },
  });

  const recordResearchLoopEvidenceMutation = useMutation({
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopEvidenceDraft; evidenceType: string }) =>
      fetchJson<ResearchLoopEvidencePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/evidence`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            evidenceType: payload.evidenceType,
            status: payload.draft.status,
            summary: payload.draft.summary.trim(),
            metricName: payload.draft.metricName.trim(),
            metricValue: payload.draft.metricValue.trim(),
            baselineMetricValue: payload.draft.baselineMetricValue.trim(),
            delta: payload.draft.delta.trim(),
            artifactRefs: payload.draft.artifactRef.trim() ? [{ path: payload.draft.artifactRef.trim() }] : [],
            datasetRefs: splitDraftList(payload.draft.datasetRefs, 24),
            environmentRefs: splitDraftList(payload.draft.environmentRefs, 24),
            logRefs: splitDraftList(payload.draft.logRefs, 24),
            commandPreview: payload.draft.commandPreview.trim(),
            recordedByAgent: sourceCollectionOwnerAgentId,
            metadata: {
              enteredFrom: "teams_research_loop_panel",
              commandPreviewOnly: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      const nextMissing = payload.loop.readiness.missingEvidenceTypes.find((item) => item !== variables.evidenceType) || "";
      setResearchLoopEvidenceDraft((draft) => ({
        ...draft,
        evidenceType: nextMissing || draft.evidenceType,
        summary: "",
        metricValue: "",
        delta: "",
        artifactRef: "",
        logRefs: "",
        commandPreview: "",
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
    },
  });

  const recordResearchLoopDecisionMutation = useMutation({
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopDecisionDraft; nextTemplateId: string }) =>
      fetchJson<ResearchLoopDecisionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: payload.draft.decision,
            rationale: payload.draft.rationale.trim(),
            nextTemplateId: payload.nextTemplateId,
            nextActions: splitDraftList(payload.draft.nextActions, 24),
            decidedByAgent: sourceCollectionOwnerAgentId,
            createNextDesignDraft:
              payload.draft.decision === "promote_to_iteration"
              || payload.draft.decision === "repair_and_repeat",
            idempotencyKey: `${payload.loop.loopId}:${payload.loop.updatedAt}:${payload.draft.decision}`,
            metadata: {
              enteredFrom: "teams_research_loop_panel",
              noAutomaticIterationExecution: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      setResearchLoopDecisionDraft((draft) => ({
        ...draft,
        rationale: "",
        nextActions: "",
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      if (payload.nextDesignDraft) {
        void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      }
    },
  });

  const materializeResearchLoopIterationDesignMutation = useMutation({
    mutationFn: (payload: { teamId: string; loopId: string; proposalId: string }) =>
      fetchJson<ResearchLoopDecisionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loopId)}/proposals/${encodeURIComponent(payload.proposalId)}/design-draft`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ createdByAgent: sourceCollectionOwnerAgentId }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
    },
  });

  const recordSourceCollectionOutputMutation = useMutation({
    mutationFn: async (payload: { teamId: string; runId: string; draft: SourceCollectionOutputDraft }) => {
      const output = await fetchJson<DataProcessingCollectionOutputPayload>(
        `/api/data-processing/runs/${encodeURIComponent(payload.runId)}/collection-assignments/${encodeURIComponent(payload.draft.assignmentId)}/outputs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "completed",
            notes: payload.draft.notes.trim(),
            records: [
              {
                sourceType: payload.draft.sourceType,
                title: payload.draft.title.trim(),
                sourceRef: payload.draft.sourceRef.trim(),
                rawLocation: payload.draft.rawLocation.trim(),
                summary: payload.draft.summary.trim(),
                status: "collected",
                metadata: {
                  allowedForAnalysis: true,
                  enteredFrom: "teams_research_source_collection_panel",
                },
                qualitySignals: {
                  manualEntry: true,
                  needsIntakeReview: true,
                },
              },
            ],
          }),
        },
      );
      const imported = await Promise.all(
        output.createdRecords.map((record) =>
          fetchJson<TeamWorkflowDataRecordSourceCandidateImportPayload>(
            `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/data-processing/runs/${encodeURIComponent(payload.runId)}/records/${encodeURIComponent(record.recordId)}/source-candidate`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                createdByAgent: sourceCollectionOwnerAgentId,
                tags: ["source_collection", "manual_writeback"],
                metadata: {
                  sourceCollectionPanel: true,
                  assignmentId: payload.draft.assignmentId,
                },
              }),
            },
          ),
        ),
      );
      return { output, imported };
    },
    onSuccess: (payload, variables) => {
      setSourceCollectionOutputDraft((current) => ({
        ...current,
        title: "",
        sourceRef: "",
        rawLocation: "",
        summary: "",
        notes: "",
      }));
      if (payload.imported[0]?.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.imported[0].workflow);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const executeSourceCollectionSearchMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; assignmentId?: string; maxQueries?: number; maxResultsPerQuery?: number }) =>
      fetchJson<TeamWorkflowSourceCollectionSearchExecutionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/search/execute`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assignmentIds: payload.assignmentId ? [payload.assignmentId] : [],
            maxQueries: payload.maxQueries ?? 4,
            maxResultsPerQuery: payload.maxResultsPerQuery ?? 2,
            provider: "crossref_rest_api",
            backgroundExecution: true,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      setSelectedSourceCollectionRunId(payload.runId);
      queryClient.setQueryData(queryKeys.dataProcessingRunStatus(payload.runId), {
        ...payload.runStatus,
        summary: {
          ...payload.runStatus.summary,
          ...(payload.sourceCollectionSummary ?? {}),
        },
      });
      queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(payload.runId), {
        schemaVersion: payload.schemaVersion,
        runId: payload.runId,
        assignments: payload.assignments,
        summary: {
          assignmentCount: payload.assignments.length,
          assignmentStatusCounts: payload.assignments.reduce<Record<string, number>>((counts, assignment) => {
            counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
            return counts;
          }, {}),
        },
      } satisfies DataProcessingCollectionAssignmentListPayload);
      if (payload.imported[0]?.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.imported[0].workflow);
      }
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const extractSourceCollectionCandidatesMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; extractionAgentId: string; maxRecords?: number; force?: boolean; notes?: string }) =>
      fetchJson<TeamWorkflowSourceCollectionExtractionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/knowledge-collection/extract`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runId: payload.runId,
            extractionAgentId: payload.extractionAgentId,
            maxRecords: payload.maxRecords ?? 100,
            force: payload.force ?? false,
            notes: payload.notes ?? "",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      setSelectedSourceCollectionRunId(payload.runId);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(queryKeys.dataProcessingRunStatus(payload.runId), {
        ...payload.runStatus,
        summary: {
          ...payload.runStatus.summary,
          ...(payload.sourceCollectionSummary ?? {}),
        },
      });
      queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(payload.runId), {
        schemaVersion: payload.schemaVersion,
        runId: payload.runId,
        assignments: payload.assignments,
        summary: {
          assignmentCount: payload.assignments.length,
          assignmentStatusCounts: payload.assignments.reduce<Record<string, number>>((counts, assignment) => {
            counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
            return counts;
          }, {}),
        },
      } satisfies DataProcessingCollectionAssignmentListPayload);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const openSourceCollectionStorageMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; target: SourceCollectionStorageOpenTarget }) =>
      fetchJson<TeamWorkflowSourceCollectionStorageOpenPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/storage/open`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: payload.target }),
        },
      ),
  });

  const assessSourceQualityMutation = useMutation({
    mutationFn: (payload: { teamId: string; candidateId: string; decision: "approved" | "needs_revision" }) =>
      fetchJson<TeamWorkflowSourceQualityAssessmentPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/candidates/${encodeURIComponent(payload.candidateId)}/source-quality/assess`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assessedByAgent: sourceCollectionExtractorAgentId,
            decision: payload.decision,
            notes: payload.decision === "approved"
              ? "Source Extractor Agent approved this source for downstream paper_note extraction."
              : "Source Extractor Agent returned this source for repair before downstream extraction.",
            requiredFixes: payload.decision === "needs_revision"
              ? ["补充来源路径/权限/sha256/摘要/页码锚点或相关性说明后重新筛选。"]
              : [],
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(sourceQualityStatusQueryKey(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const assessSourceQualityBatchMutation = useMutation({
    mutationFn: (payload: { teamId: string; assessedByAgent: string; maxCandidates?: number; force?: boolean; notes?: string }) =>
      fetchJson<TeamWorkflowSourceQualityBatchAssessmentPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-quality/assess-batch`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assessedByAgent: payload.assessedByAgent,
            maxCandidates: payload.maxCandidates ?? 100,
            force: payload.force ?? false,
            notes: payload.notes ?? "",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(sourceQualityStatusQueryKey(variables.teamId), payload.sourceQualityStatus);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
      scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
    },
  });

  const planPaperNoteChunksMutation = useMutation({
    mutationFn: (payload: { teamId: string; candidateId: string }) =>
      fetchJson<TeamWorkflowPaperNoteChunkPlanPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/candidates/${encodeURIComponent(payload.candidateId)}/paper-note-chunks/plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            createdByAgent: sourceCollectionOwnerAgentId,
            maxPagesPerChunk: 4,
            maxCharsPerChunk: 12000,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const buildCandidateGraphMutation = useMutation({
    mutationFn: (variables: {
      teamId: string;
      title?: string;
      createdByAgent?: string;
      sourceQualityAgentId?: string;
      curationMode?: string;
      maxCandidates?: number;
      forceReview?: boolean;
      forceRebuild?: boolean;
    }) =>
      fetchJson<TeamWorkflowCandidateGraphBuildPayload>(`/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/candidate-graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: variables.title || "Agent curated candidate graph",
          createdByAgent: variables.createdByAgent || sourceCollectionRelationMapperAgentId,
          sourceQualityAgentId: variables.sourceQualityAgentId || sourceCollectionExtractorAgentId,
          curationMode: variables.curationMode || "",
          maxCandidates: variables.maxCandidates || 80,
          forceReview: variables.forceReview ?? false,
          forceRebuild: variables.forceRebuild ?? false,
        }),
      }),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidateGraph(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
    },
  });

  const runKnowledgeIngestionPrecheckMutation = useMutation({
    mutationFn: (variables: { teamId: string; stewardAgentId: string; targetDomain?: string; maxCandidates?: number }) =>
      fetchJson<TeamWorkflowKnowledgeIngestionPrecheckPayload>(
        `/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/knowledge-ingestion/precheck`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stewardAgentId: variables.stewardAgentId,
            targetDomain: variables.targetDomain || sourceCollectionDraft.topic || "神经机制启发神经网络算法",
            maxCandidates: variables.maxCandidates || 32,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
    },
  });

  const runKnowledgeCollectionCompletionMutation = useMutation({
    mutationFn: (variables: {
      teamId: string;
      runId?: string;
      extractionAgentId?: string;
      sourceQualityAgentId: string;
      candidateGraphAgentId: string;
      stewardAgentId: string;
      knowledgeBaseId?: string;
      targetDomain?: string;
      maxCandidates?: number;
      maxSearchBatches?: number;
      maxQueriesPerBatch?: number;
      maxResultsPerQuery?: number;
      maxRecords?: number;
      forceReview?: boolean;
      forceRebuild?: boolean;
    }) =>
      fetchJson<TeamWorkflowKnowledgeCollectionIngestionPayload>(
        `/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/knowledge-collection/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runId: variables.runId || "",
            extractionAgentId: variables.extractionAgentId || "",
            sourceQualityAgentId: variables.sourceQualityAgentId,
            candidateGraphAgentId: variables.candidateGraphAgentId,
            stewardAgentId: variables.stewardAgentId,
            knowledgeBaseId: variables.knowledgeBaseId || "",
            targetDomain: variables.targetDomain || sourceCollectionDraft.topic || "神经机制启发神经网络算法",
            maxCandidates: variables.maxCandidates || 80,
            maxSearchBatches: variables.maxSearchBatches ?? 20,
            maxQueriesPerBatch: variables.maxQueriesPerBatch ?? 4,
            maxResultsPerQuery: variables.maxResultsPerQuery || Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 3)),
            maxRecords: variables.maxRecords ?? 500,
            forceReview: variables.forceReview ?? false,
            forceRebuild: variables.forceRebuild ?? false,
            autoCreateKnowledgeBase: true,
            // 一键入库走同步闭环：提交→来源审核→知识提案→审批→正式 KnowledgeItem。
            // 职责分离：steward 提案，由后端解析的 coordinator/lead 审批，不再依赖唤醒 agent 的异步交接。
            autoSubmit: true,
            autoReviewSource: true,
            autoApprove: true,
            notifyStewardAgent: false,
            wakeStewardAgent: false,
            // 首次入库需现场生成 steward pack（分钟级）；后台执行让点击立即返回，状态由 activeWorkRun 轮询。
            backgroundExecution: true,
            requesterAgentId: sourceCollectionOwnerAgentId,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      // 后台执行时响应是 accepted（无 workflow/statusSnapshot）：只失效查询，让 activeWorkRun 轮询接管。
      if (payload.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      }
      if (payload.statusSnapshot) {
        queryClient.setQueryData(queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId), payload.statusSnapshot);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidateGraph(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
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

  function selectTeamRecord(team: Team) {
    setSelectedTeamId(team.teamId);
    setSelectedNodeId("");
    if (isResearchWorkflowTeam(team)) {
      setResearchWorkspaceView("overview");
    }
    setSearchParams({ team: team.teamId });
  }

  function launchResearchStage(stageType: ResearchStageType, mode: "continue_or_start" | "new_round" = "continue_or_start") {
    if (!selectedTeam?.teamId || selectedTeamStartResearchStagePending) {
      return;
    }
    if (stageType === "knowledge_collection" && !researchStageCanLaunch) {
      return;
    }
    startResearchStageRoundMutation.mutate({
      teamId: selectedTeam.teamId,
      stageType,
      mode,
      draft: sourceCollectionDraft,
    });
  }

  function createExperimentPlanFromWorkspace(methodRequest?: ExperimentPlanMethodRequest) {
    if (!selectedTeam?.teamId || selectedTeamCreateExperimentPlanPending) {
      return;
    }
    const experimentPhase = researchStagePhases.find((phase) => phase.stageType === "experiment");
    const stageRoundId = experimentPhase?.activeRoundId || experimentPhase?.latestRound?.stageRoundId || experimentPlanningStatus?.latestExperimentRound?.stageRoundId || "";
    createExperimentPlanMutation.mutate({
      teamId: selectedTeam.teamId,
      stageRoundId,
      title: sourceCollectionDraft.title.trim() || experimentPhase?.latestRound?.title || "",
      methodRequest,
    });
  }

  function registerExperimentBaselineArtifactFromWorkspace(plan: ExperimentPlanRecord) {
    if (!selectedTeam?.teamId || selectedTeamRegisterExperimentBaselineArtifactPending) {
      return;
    }
    registerExperimentBaselineArtifactMutation.mutate({
      teamId: selectedTeam.teamId,
      plan,
      draft: experimentBaselineArtifactDraft,
    });
  }

  function freezeExperimentDesignFromWorkspace(plan: ExperimentPlanRecord) {
    if (!selectedTeam?.teamId || selectedTeamFreezeExperimentDesignPending) {
      return;
    }
    freezeExperimentDesignMutation.mutate({ teamId: selectedTeam.teamId, plan });
  }

  function registerExperimentSmokeResultFromWorkspace(plan: ExperimentPlanRecord) {
    if (!selectedTeam?.teamId || selectedTeamRegisterExperimentSmokeResultPending) {
      return;
    }
    registerExperimentSmokeResultMutation.mutate({
      teamId: selectedTeam.teamId,
      plan,
      draft: experimentSmokeResultDraft,
    });
  }

  function registerExperimentFullRunResultFromWorkspace(plan: ExperimentPlanRecord) {
    if (!selectedTeam?.teamId || selectedTeamRegisterExperimentFullRunResultPending) {
      return;
    }
    registerExperimentFullRunResultMutation.mutate({
      teamId: selectedTeam.teamId,
      plan,
      draft: experimentFullRunResultDraft,
    });
  }

  function requestExperimentKnowledgeIngestionFromWorkspace(plan: ExperimentPlanRecord) {
    if (!selectedTeam?.teamId || selectedTeamRequestExperimentKnowledgeIngestionPending) {
      return;
    }
    requestExperimentKnowledgeIngestionMutation.mutate({
      teamId: selectedTeam.teamId,
      plan,
      draft: experimentKnowledgeIngestionDraft,
    });
  }

  function createResearchLoopFromWorkspace(plan: ExperimentPlanRecord | null) {
    if (!selectedTeam?.teamId || selectedTeamCreateResearchLoopPending) {
      return;
    }
    const templates = researchLoopTemplatesPayload?.templates ?? researchLoopStatus?.templates ?? [];
    const templateId = selectedResearchLoopTemplateId || researchLoopTemplatesPayload?.defaultTemplateId || templates[0]?.templateId || "algorithm_model_experiment";
    const researchQuestion = researchLoopCreateDraft.researchQuestion.trim() || plan?.goal || plan?.topic || sourceCollectionDraft.goal;
    if (!researchQuestion.trim()) {
      return;
    }
    createResearchLoopMutation.mutate({
      teamId: selectedTeam.teamId,
      plan,
      templateId,
      draft: researchLoopCreateDraft,
    });
  }

  function recordResearchLoopEvidenceFromWorkspace(loop: ResearchLoopRecord) {
    if (!selectedTeam?.teamId || selectedTeamRecordResearchLoopEvidencePending) {
      return;
    }
    const evidenceType =
      researchLoopEvidenceDraft.evidenceType
      || loop.readiness.missingEvidenceTypes[0]
      || loop.readiness.requiredEvidenceTypes[0]
      || "";
    const hasEvidencePayload = Boolean(
      researchLoopEvidenceDraft.summary.trim()
      || researchLoopEvidenceDraft.metricValue.trim()
      || researchLoopEvidenceDraft.artifactRef.trim()
      || researchLoopEvidenceDraft.datasetRefs.trim()
      || researchLoopEvidenceDraft.environmentRefs.trim()
      || researchLoopEvidenceDraft.logRefs.trim()
      || researchLoopEvidenceDraft.commandPreview.trim(),
    );
    if (!evidenceType || !hasEvidencePayload) {
      return;
    }
    recordResearchLoopEvidenceMutation.mutate({
      teamId: selectedTeam.teamId,
      loop,
      draft: researchLoopEvidenceDraft,
      evidenceType,
    });
  }

  function recordResearchLoopDecisionFromWorkspace(loop: ResearchLoopRecord) {
    if (!selectedTeam?.teamId || selectedTeamRecordResearchLoopDecisionPending || !researchLoopDecisionDraft.rationale.trim()) {
      return;
    }
    const templates = researchLoopTemplatesPayload?.templates ?? researchLoopStatus?.templates ?? [];
    const nextTemplateId =
      researchLoopDecisionDraft.nextTemplateId
      || selectedResearchLoopTemplateId
      || loop.templateId
      || templates[0]?.templateId
      || "algorithm_model_experiment";
    recordResearchLoopDecisionMutation.mutate({
      teamId: selectedTeam.teamId,
      loop,
      draft: researchLoopDecisionDraft,
      nextTemplateId,
    });
  }

  function renderResearchStageAgentSummary(stageType: ResearchStageType) {
    const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
    const agentDirectoryHydrating = bindings.some((binding) => binding.agentId && !binding.agent)
      && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching);
    return (
      <TeamResearchStageAgentSummary
        lang={lang}
        bindings={bindings}
        agentDirectoryHydrating={agentDirectoryHydrating}
      />
    );
  }

  function renderResearchStageAgentPanel(stageType: ResearchStageType, variant: "compact" | "page" = "page") {
    const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
    return (
      <TeamResearchStageAgentPanel
        lang={lang}
        stageType={stageType}
        bindings={bindings}
        variant={variant}
      />
    );
  }

  function sourceCollectionStageAgentBindings(stageId: SourceCollectionStageModuleId) {
    const targetKeys = SOURCE_COLLECTION_STAGE_AGENT_KEYS[stageId];
    const priorityByKey = new Map(targetKeys.map((key, index) => [key, index]));
    return (researchStageAgentBindingsByStage.knowledge_collection ?? [])
      .filter((binding) => priorityByKey.has(binding.key))
      .sort((left, right) => (priorityByKey.get(left.key) ?? 99) - (priorityByKey.get(right.key) ?? 99));
  }

  function sourceCollectionStagePrimaryAgentBinding(stageId: SourceCollectionStageModuleId) {
    const bindings = sourceCollectionStageAgentBindings(stageId);
    return bindings.find((binding) => researchStageAgentDirectChatRoute(binding.agent)) ?? bindings[0] ?? null;
  }

  function sourceCollectionStageAgentChatState(stageId: SourceCollectionStageModuleId): {
    binding: ReturnType<typeof sourceCollectionStagePrimaryAgentBinding>;
    route: string;
    status: SourceCollectionStageAgentChatStatus;
  } {
    const binding = sourceCollectionStagePrimaryAgentBinding(stageId);
    const route = researchStageAgentDirectChatRoute(
      binding?.agent,
      sourceCollectionStageReturnRoute(stageId),
      sourceCollectionStageChatReturnLabel(stageId),
    );
    if (route) {
      return { binding, route, status: "ready" };
    }
    const hasBoundAgentId = Boolean(String(binding?.agentId || "").trim());
    if (hasBoundAgentId && !binding?.agent && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching)) {
      return { binding, route, status: "loading" };
    }
    if (hasBoundAgentId && !binding?.agent && agentSummaryQuery.isError) {
      return { binding, route, status: "error" };
    }
    return { binding, route, status: "repair" };
  }

  function sourceCollectionStageReturnRoute(stageId: SourceCollectionStageModuleId) {
    return `${researchSourceCollectionRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}&collectionStage=${stageId}`;
  }

  function sourceCollectionStageChatReturnLabel(stageId: SourceCollectionStageModuleId) {
    return `${lang === "zh" ? "返回" : "Back to"} ${SOURCE_COLLECTION_STAGE_CHAT_LABELS[stageId][lang]}`;
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
    if (chatState.status === "ready" && chatState.route) {
      const teamId = selectedTeam?.teamId || RESEARCH_TEAM_ID;
      const runId = selectedSourceCollectionRunEffectiveId;
      const agentId = String(binding?.agent?.agentId || binding?.agentId || "").trim();
      if (teamId && runId && agentId) {
        try {
          await seedSourceCollectionAgentSessionContextMutation.mutateAsync({
            teamId,
            runId,
            stageId,
            agentId,
            agentRole: binding?.key || "",
          });
        } catch (error) {
          console.warn("Failed to seed source collection Agent session context before navigation.", error);
        }
      }
      navigate(chatState.route);
      return;
    }
    if (chatState.status === "repair") {
      repairSelectedWorkflowTeamAgentsIfNeeded();
    }
  }

  function renderTeamMemoryIndex() {
    if (!selectedTeam) {
      return null;
    }
    return (
      <TeamMemoryIndexPanel
        lang={lang}
        members={selectedTeamMemoryMembers}
        knowledgeRoute={selectedTeamKnowledgeRoute}
        graphRoute={selectedTeamGraphRoute}
      />
    );
  }

  async function startSourceCollectionStageSessionTask(stageId: SourceCollectionStageModuleId) {
    if (!selectedTeam?.teamId || startSourceCollectionStageSessionTaskMutation.isPending) {
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
    if (chatState.status !== "ready" || !agentId || !binding?.agent?.directSessionId) {
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
      });
      navigate(payload.chatRoute || chatState.route);
    } catch {
      return;
    }
  }

  function renderSourceCollectionStageAgents(stageId: SourceCollectionStageModuleId) {
    const bindings = sourceCollectionStageAgentBindings(stageId);
    if (!bindings.length) {
      return null;
    }
    const agentCards: TeamSourceCollectionStageAgentCard[] = bindings.map((binding) => {
      const agentHydrationPending = Boolean(
        binding.agentId
        && !binding.agent
        && (agentSummaryQuery.isPending || agentSummaryQuery.isFetching),
      );
      const tone: TeamSourceCollectionStageAgentTone = binding.agent
        ? researchStageAgentConfigTone(binding.agent)
        : binding.agentId
          ? "blocked"
          : "missing";
      const info = agentDisplayInfo(binding.agent, lang, {
        name: binding.bindingLabel || (lang === "zh" ? binding.zh : binding.en),
      });
      const agentName = binding.agent
        ? info.name
        : binding.agentId
          ? binding.agentId
          : (lang === "zh" ? "未绑定" : "Not bound");
      const statusLabel = binding.agent
        ? researchStageAgentConfigStatusLabel(binding.agent, lang)
        : binding.agentId
          ? agentHydrationPending
            ? (lang === "zh" ? "加载中" : "loading")
            : agentSummaryQuery.isError
              ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
              : (lang === "zh" ? "引用失效" : "missing reference")
          : (lang === "zh" ? "待绑定" : "missing");
      const agentMemoryRoute = binding.agentId
        ? agentCenterMemoryRoute({
            agentId: binding.agentId,
            teamId: selectedTeam?.teamId,
            view: "agents",
            returnLabel: "teams",
            returnTo: selectedTeamReturnRoute,
          })
        : "";
      return {
        id: `source-step-${stageId}-${binding.key}`,
        tone,
        roleLabel: lang === "zh" ? binding.zh : binding.en,
        agentName,
        modelLabel: researchStageAgentModelLabel(binding.agent, lang),
        statusLabel,
        memoryRoute: agentMemoryRoute,
        configRoute: binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents",
        configLabel: binding.agent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind"),
      };
    });
    return (
      <TeamSourceCollectionStageAgentsPanel
        lang={lang}
        agents={agentCards}
      />
    );
  }

  function renderSourceCollectionFilterBar(
    counts: Record<SourceCollectionSourceFilter, number>,
    label: string,
    loading = false,
  ) {
    const sourceCollectionFilterLoadingCount = (filter: SourceCollectionSourceFilter) =>
      filter === "all" ? sourceCollectionLoadingText : "...";
    const options: Array<TeamSourceCollectionFilterOption<SourceCollectionSourceFilter>> = SOURCE_COLLECTION_SOURCE_FILTERS.map((filter) => ({
      key: filter,
      label: sourceCollectionSourceFilterLabel(filter, lang),
      count: loading ? sourceCollectionFilterLoadingCount(filter) : counts[filter] ?? 0,
      selected: sourceCollectionSourceFilter === filter,
    }));

    return (
      <TeamSourceCollectionFilterBar
        ariaLabel={label}
        options={options}
        onSelect={setSourceCollectionSourceFilter}
      />
    );
  }

  function sourceCollectionPageItems<T>(stageId: SourceCollectionStageModuleId, items: T[]) {
    const pageCount = Math.max(1, Math.ceil(items.length / SOURCE_COLLECTION_RESULT_PAGE_SIZE));
    const page = Math.min(Math.max(1, sourceCollectionResultPageByStage[stageId] ?? 1), pageCount);
    const start = (page - 1) * SOURCE_COLLECTION_RESULT_PAGE_SIZE;
    return {
      items: items.slice(start, start + SOURCE_COLLECTION_RESULT_PAGE_SIZE),
      page,
      pageCount,
      start: items.length ? start + 1 : 0,
      end: Math.min(items.length, start + SOURCE_COLLECTION_RESULT_PAGE_SIZE),
    };
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
    const pageCount = Math.max(1, Math.ceil(total / SOURCE_COLLECTION_RESULT_PAGE_SIZE));
    if (pageCount <= 1) {
      return null;
    }
    const page = Math.min(Math.max(1, sourceCollectionResultPageByStage[stageId] ?? 1), pageCount);
    return (
      <TeamSourceCollectionPagination
        lang={lang}
        total={total}
        page={page}
        pageSize={SOURCE_COLLECTION_RESULT_PAGE_SIZE}
        onPageChange={(nextPage) => setSourceCollectionResultPage(stageId, nextPage)}
        onContain={stopSourceCollectionPaginationEvent}
      />
    );
  }

  function openSourceCollectionStage(stageId: SourceCollectionStageModuleId) {
    selectSourceCollectionStage(stageId);
    setSourceCollectionFocusedPanelId("");
  }

  function renderResearchStageLauncher() {
    return (
      <TeamResearchStageLauncherPanel
        researchWorkflowTeamSelected={researchWorkflowTeamSelected}
        challengeCupResearchTeamSelected={challengeCupResearchTeamSelected}
        knowledgeExpansionWorkflowTeamSelected={knowledgeExpansionWorkflowTeamSelected}
        experimentPlanningStatus={experimentPlanningStatus}
        selectedTeam={selectedTeam}
        selectedTeamMemoryMembers={selectedTeamMemoryMembers}
        lang={lang}
        challengeTeamSurface={challengeTeamSurface}
        sourceCollectionDraft={sourceCollectionDraft}
        setSourceCollectionDraft={setSourceCollectionDraft}
        preferredExperimentMethod={preferredExperimentMethod}
        setPreferredExperimentMethod={setPreferredExperimentMethod}
        experimentPlanningStatusQuery={experimentPlanningStatusQuery}
        sourceCollectionDisplayState={sourceCollectionDisplayState}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionSearchOpenAssignmentCount={sourceCollectionSearchOpenAssignmentCount}
        selectedTeamExecuteSourceCollectionSearchPending={selectedTeamExecuteSourceCollectionSearchPending}
        sourceCollectionAcceptedBackgroundActive={sourceCollectionAcceptedBackgroundActive}
        sourceCollectionDownstreamOpenAssignmentCount={sourceCollectionDownstreamOpenAssignmentCount}
        sourceCollectionRunPendingScreeningCount={sourceCollectionRunPendingScreeningCount}
        selectedTeamStartSourceCollectionPending={selectedTeamStartSourceCollectionPending}
        sourceCollectionCanStart={sourceCollectionCanStart}
        selectedTeamStartResearchStagePending={selectedTeamStartResearchStagePending}
        researchStageCanLaunch={researchStageCanLaunch}
        sourceCollectionSearchActionReadiness={sourceCollectionSearchActionReadiness}
        sourceCollectionActionInitialDataPending={sourceCollectionActionInitialDataPending}
        sourceCollectionActionDataError={sourceCollectionActionDataError}
        sourceCollectionActionBusyReason={sourceCollectionActionBusyReason}
        sourceCollectionActionNoInputReason={sourceCollectionActionNoInputReason}
        sourceCollectionActionLoadingReason={sourceCollectionActionLoadingReason}
        sourceCollectionActionErrorReason={sourceCollectionActionErrorReason}
        sourceCollectionActionReadiness={sourceCollectionActionReadiness}
        selectedSourceCollectionAssignment={selectedSourceCollectionAssignment}
        executeSourceCollectionSearchMutation={executeSourceCollectionSearchMutation}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        startSourceCollectionRunMutation={startSourceCollectionRunMutation}
        launchResearchStage={launchResearchStage}
        navigate={navigate}
        researchStageRoundStatus={researchStageRoundStatus}
        researchStageRoundStatusQuery={researchStageRoundStatusQuery}
        researchStagePhases={researchStagePhases}
        searchParams={searchParams}
        experimentMethodCatalogQuery={experimentMethodCatalogQuery}
        researchTeamDetailDegraded={researchTeamDetailDegraded}
        selectedTeamDetailLoading={selectedTeamDetailLoading}
        teamDetailQuery={teamDetailQuery}
        sourceCollectionSearchOpenAssignmentCountText={sourceCollectionSearchOpenAssignmentCountText}
        sourceCollectionDownstreamOpenAssignmentCountText={sourceCollectionDownstreamOpenAssignmentCountText}
        sourceCollectionCollectedCountText={sourceCollectionCollectedCountText}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionQueryCountText={sourceCollectionQueryCountText}
        renderResearchStageAgentSummary={renderResearchStageAgentSummary}
        runKnowledgeCollectionLoopAction={runKnowledgeCollectionLoopAction}
        sourceCollectionLoopActionDisabled={sourceCollectionLoopActionDisabled}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionLoopActionReadiness={sourceCollectionLoopActionReadiness}
        sourceCollectionLoopActionLabel={sourceCollectionLoopActionLabel}
        sourceCollectionLoopStartsNewRun={sourceCollectionLoopStartsNewRun}
        selectedTeamStartResearchStageError={selectedTeamStartResearchStageError}
        selectedTeamStartResearchStageResult={selectedTeamStartResearchStageResult}
        researchStageStartFeedbackText={researchStageStartFeedbackText}
      />
    );
  }

  function renderResearchCanvasReadOnlyPanel() {
    const node = selectedNode;
    const agent = node?.agentId ? activeAgents.find((item) => item.agentId === node.agentId) : null;
    const display = agent ? agentDisplayInfo(agent, lang) : null;
    const functionLabel = node ? teamNodeFunctionLabel(node, display?.functionLabel, lang) : "";
    return (
      <section className={styles.canvasReadOnlyPanel} aria-label={lang === "zh" ? "只读组织画布详情" : "Read-only organization canvas details"}>
        <div className={styles.canvasReadOnlyNotice}>
          <Eye size={15} />
          <div>
            <strong>{lang === "zh" ? "只读组织画布" : "Read-only canvas"}</strong>
            <span>{lang === "zh" ? "这里仅展示科研团队节点关系，不写回画布配置。" : "This view shows research-team relationships without writing canvas config."}</span>
          </div>
        </div>
        {node ? (
          <div className={styles.canvasReadOnlyNode}>
            <div>
              <span>{lang === "zh" ? "节点" : "Node"}</span>
              <strong>{node.label}</strong>
            </div>
            <div>
              <span>{lang === "zh" ? "职责" : "Role"}</span>
              <strong>{functionLabel || node.role || node.type}</strong>
            </div>
            <div>
              <span>Agent</span>
              <strong>{display?.name || node.agentName || node.agentCode || (lang === "zh" ? "未绑定" : "unbound")}</strong>
            </div>
            <div>
              <span>{lang === "zh" ? "状态" : "Status"}</span>
              <strong>{canvasNodeStatusLabel(node, lang)}</strong>
            </div>
            <div className={styles.canvasReadOnlyNodeWide}>
              <span>{lang === "zh" ? "目的" : "Purpose"}</span>
              <strong>{node.purpose || (lang === "zh" ? "暂无说明" : "No purpose yet")}</strong>
            </div>
          </div>
        ) : (
          <div className={styles.empty}>{lang === "zh" ? "选择一个节点查看详情。" : "Select a node to inspect details."}</div>
        )}
        <div className={styles.issueList}>
          {(validation?.issues ?? []).length ? (
            validation?.issues.map((issue) => (
              <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={styles.issue}>
                <strong>{issue.code}</strong>
                <span>{issue.message}</span>
              </div>
            ))
          ) : (
            <span>{lang === "zh" ? "画布校验通过" : "Canvas validation passed"}</span>
          )}
        </div>
      </section>
    );
  }

  function renderKnowledgeCollectionCompletionFlowPanel() {
    return (
      <TeamKnowledgeCollectionCompletionFlowPanel
        lang={lang}
        researchWorkflowTeamSelected={researchWorkflowTeamSelected}
        researchCanvasReadOnly={researchCanvasReadOnly}
        selectedTeamKnowledgeCollectionWorkRun={selectedTeamKnowledgeCollectionWorkRun}
        sourceCollectionCompletionFlow={sourceCollectionCompletionFlow}
        sourceCollectionCompletionFlowNodes={sourceCollectionCompletionFlowNodes}
        sourceCollectionStageModules={sourceCollectionStageModules}
        workflowIngestionTone={workflowIngestionTone}
        parseSourceCollectionStageModuleId={parseSourceCollectionStageModuleId}
        sourceCollectionStagePrimaryAgentBinding={sourceCollectionStagePrimaryAgentBinding}
        sourceCollectionStageReturnRoute={sourceCollectionStageReturnRoute}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        sourceCollectionStepClassName={sourceCollectionStepClassName}
        runKnowledgeCollectionCompletionAction={runKnowledgeCollectionCompletionAction}
        sourceCollectionCompletionActionDisabled={sourceCollectionCompletionActionDisabled}
        selectedTeamKnowledgeCollectionIngestPending={selectedTeamKnowledgeCollectionIngestPending}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionCompletionActionReadiness={sourceCollectionCompletionActionReadiness}
      />
    );
  }

  function renderAiSearchSourceScopePanel() {
    return (
      <TeamAiSearchWorkspacePanel
        lang={lang}
        scope={selectedTeam?.sourceScope ?? null}
        teamDetailPending={teamDetailQuery.isPending}
        runs={aiSearchRuns}
        runsPending={aiSearchRunsQuery.isPending}
        runsFetching={aiSearchRunsQuery.isFetching}
        visibleRunCount={aiSearchRunsQuery.data?.summary.visibleRunCount ?? aiSearchRuns.length}
        totalRunCount={aiSearchRunsQuery.data?.summary.runCount ?? aiSearchRuns.length}
        latestRun={latestAiSearchRun}
        topic={aiSearchRunTopic}
        onTopicChange={setAiSearchRunTopic}
        canStart={aiSearchRunCanStart}
        startPending={selectedTeamStartAiSearchPending}
        startErrorMessage={selectedTeamStartAiSearchError?.message ?? null}
        onStart={(payload) => startAiSearchRunMutation.mutate(payload)}
        teamId={selectedTeam?.teamId}
      />
    );
  }

  function renderSourceCollectionRunSwitcher() {
    if (!sourceCollectionRuns.length) {
      return null;
    }
    const selectedRecordCount = sourceCollectionRunRecordCount(selectedSourceCollectionRun);
    const selectedCandidateCount = sourceCollectionRunCandidateMetric(selectedSourceCollectionRun);
    const selectedRunIsEmpty = Boolean(
      selectedSourceCollectionRun
      && !sourceCollectionRunHasUsableRecords(selectedSourceCollectionRun),
    );
    const canSwitchToHistoricalRun = Boolean(
      sourceCollectionHistoricalRunWithRecords
      && sourceCollectionHistoricalRunWithRecords.runId !== selectedSourceCollectionRun?.runId,
    );
    const runOptions: TeamSourceCollectionRunSwitcherRun[] = sourceCollectionRuns.map((run) => ({
      runId: run.runId,
      label: sourceCollectionRunOptionLabel(run, lang),
    }));
    const hint = sourceCollectionRecordsDataLoading
      ? (lang === "zh" ? "正在读取当前批次资料。" : "Loading the selected run.")
      : sourceCollectionShowingHistoricalRunByDefault
        ? (lang === "zh" ? "最新批次暂无资料，已显示上一轮有资料的批次。" : "The latest run is empty, so the latest run with records is shown.")
      : selectedRunIsEmpty && canSwitchToHistoricalRun
        ? (lang === "zh" ? "当前批次暂无资料，上一轮有资料；可切换查看。" : "This run is empty; another run has records.")
      : (lang === "zh" ? "可切换批次查看历史搜索结果。" : "Switch runs to inspect previous search results.");
    return (
      <TeamSourceCollectionRunSwitcherPanel
        lang={lang}
        runs={runOptions}
        selectedRunId={selectedSourceCollectionRunEffectiveId}
        hint={hint}
        recordMetric={sourceCollectionRecordsDataLoading ? sourceCollectionLoadingText : selectedRecordCount}
        candidateMetric={sourceCollectionRecordsDataLoading ? sourceCollectionLoadingText : selectedCandidateCount}
        statusLabel={sourceCollectionStatusLabel(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status, lang)}
        canSwitchToHistoricalRun={selectedRunIsEmpty && canSwitchToHistoricalRun && Boolean(sourceCollectionHistoricalRunWithRecords)}
        onRunChange={setSelectedSourceCollectionRunId}
        onSwitchToHistoricalRun={() => {
          if (sourceCollectionHistoricalRunWithRecords) {
            setSelectedSourceCollectionRunId(sourceCollectionHistoricalRunWithRecords.runId);
          }
        }}
      />
    );
  }

  function renderSourceCollectionConversation() {
    return (
      <TeamSourceCollectionConversationWorkspacePanel
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
    if (!selectedSourceCollectionStorageArtifacts || !selectedSourceCollectionRunEffectiveId) {
      return null;
    }
    const detailActions: SourceCollectionStorageOpenTarget[] = [
      "search_plan",
      "search_events",
      "records",
      "candidates",
      "candidate_store",
    ];
    const primaryAction: TeamSourceCollectionStorageAction = {
      target: "run_directory",
      label: sourceCollectionStorageTargetLabel("run_directory", lang),
    };
    const storageActions: TeamSourceCollectionStorageAction[] = detailActions.map((target) => ({
      target,
      label: sourceCollectionStorageTargetLabel(target, lang),
    }));
    return (
      <TeamSourceCollectionStorageActionsPanel
        lang={lang}
        runDirectory={selectedSourceCollectionStorageArtifacts.runDirectory}
        primaryAction={primaryAction}
        detailActions={storageActions}
        pending={selectedSourceCollectionStorageOpenPending}
        openedPath={selectedSourceCollectionStorageOpenResult?.openedPath ?? ""}
        errorMessage={selectedSourceCollectionStorageOpenError?.message ?? ""}
        onOpenTarget={(target) => openSourceCollectionStorageTarget(target as SourceCollectionStorageOpenTarget)}
      />
    );
  }

  function renderSourceCollectionSelectedSourcePanel() {
    if (!selectedSourceCollectionCandidate) {
      return null;
    }
    const provenance = sourceCollectionCandidateProvenance(selectedSourceCollectionCandidate, lang);
    const trace = selectedSourceCollectionCandidateTrace ?? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate);
    const sourceQualitySummary = candidateSourceQualityAssessmentSummary(selectedSourceCollectionCandidate);
    const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(selectedSourceCollectionCandidate);
    const runId = trace.runId || selectedSourceCollectionRunEffectiveId;
    const fileStorageTarget = provenance.kind === "file" && selectedSourceCollectionCandidateStorageArtifacts
      ? sourceCollectionStorageTargetForRef(provenance.value, selectedSourceCollectionCandidateStorageArtifacts)
      : null;
    const hasReadableSource = Boolean(provenance.href || fileStorageTarget);
    const hasSearchEvidence = Boolean(trace.searchUrl || trace.query || trace.searchProvider || trace.queryId || trace.assignmentId);
    const storageTargets: SourceCollectionStorageOpenTarget[] = ["run_directory", "search_events", "records", "candidates"];
    const readableLinks: TeamSourceCollectionSourceDetailLink[] = provenance.href
      ? [{
          id: "source",
          href: provenance.href,
          title: provenance.href,
          label: sourceCollectionCandidateOpenLabel(provenance, lang),
        }]
      : [];
    const sourceActions: TeamSourceCollectionSourceDetailAction[] = fileStorageTarget
      ? [{
          id: `file-${fileStorageTarget}`,
          target: fileStorageTarget,
          runId,
          label: sourceCollectionStorageTargetLabel(fileStorageTarget, lang),
          title: provenance.value,
        }]
      : [];
    const storageActions: TeamSourceCollectionSourceDetailAction[] = runId
      ? storageTargets.map((target) => ({
          id: `${selectedSourceCollectionCandidate.candidateId}-${target}`,
          target,
          runId,
          label: sourceCollectionStorageTargetLabel(target, lang),
        }))
      : [];
    const noticeMessage = hasReadableSource
      ? ""
      : provenance.kind === "search_evidence"
        ? (lang === "zh" ? "仅有搜索记录，缺少可读来源" : "Only search evidence is available")
        : (lang === "zh" ? "缺少可读来源" : "Readable source missing");
    const searchEvidence: TeamSourceCollectionSourceDetailEvidence[] = [
      trace.query
        ? {
            id: "query",
            label: lang === "zh" ? "搜索问题" : "Search query",
            value: translateResearchPhrase(trace.query, lang),
            title: trace.query,
          }
        : null,
      trace.searchProvider
        ? {
            id: "provider",
            label: lang === "zh" ? "搜索源" : "Provider",
            value: trace.searchProvider,
            title: trace.searchProvider,
          }
        : null,
      trace.searchUrl
        ? {
            id: "api",
            label: lang === "zh" ? "API 证据" : "API evidence",
            value: lang === "zh" ? "打开 API 原文" : "Open raw API",
            title: trace.searchUrl,
            href: trace.searchUrl,
          }
        : null,
    ].filter((item): item is TeamSourceCollectionSourceDetailEvidence => Boolean(item));
    const facts: TeamSourceCollectionSourceDetailFact[] = [
      [lang === "zh" ? "类型" : "Type", sourceCollectionSourceTypeLabel(selectedSourceCollectionCandidate.sourceKind || selectedSourceCollectionCandidate.candidateType, lang)],
      [lang === "zh" ? "来源" : "Source", provenance.value],
      [lang === "zh" ? "查询" : "Query", trace.query ? translateResearchPhrase(trace.query, lang) : ""],
      [lang === "zh" ? "资料记录" : "Record", trace.recordId],
      [lang === "zh" ? "批次" : "Run", runId ? sourceCollectionRunLabel(runId) : ""],
      [lang === "zh" ? "分工" : "Assignment", trace.assignmentId],
      [lang === "zh" ? "搜索源" : "Provider", trace.searchProvider],
      [
        "Evidence Ledger",
        evidenceLedgerSummary
          ? sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang)
          : "",
      ],
    ]
      .filter(([, value]) => Boolean(value))
      .map(([label, value]) => ({ label: String(label), value: String(value) }));
    const statusLabel = sourceQualitySummary
      ? `${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100`
      : workflowStateLabel(selectedSourceCollectionCandidate.currentState, lang);
    return (
      <TeamSourceCollectionSourceDetailPanel
        lang={lang}
        title={selectedSourceCollectionCandidate.title || selectedSourceCollectionCandidate.candidateId}
        candidateId={selectedSourceCollectionCandidate.candidateId}
        statusLabel={statusLabel}
        statusToneClassName={workflowQualityTone(selectedSourceCollectionCandidate.qualityStatus)}
        readableLinks={readableLinks}
        actions={[...sourceActions, ...storageActions]}
        noticeMessage={noticeMessage}
        searchEvidence={hasSearchEvidence ? searchEvidence : []}
        evidenceLedger={evidenceLedgerSummary ? sourceCollectionEvidenceLedgerDetailItems(evidenceLedgerSummary, lang) : []}
        facts={facts}
        pending={selectedSourceCollectionStorageOpenPending}
        onOpenTarget={(target, targetRunId) => openSourceCollectionStorageTarget(target as SourceCollectionStorageOpenTarget, targetRunId)}
      />
    );
  }

  function renderSourceCollectionScreeningPanel() {
    return (
      <TeamSourceCollectionScreeningWorkspacePanel
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
        openSourceCollectionScreeningPanel={openSourceCollectionScreeningPanel}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        teamWorkflowSourceQualityStatus={teamWorkflowSourceQualityStatus}
        teamWorkflowSourceQualityStatusQuery={teamWorkflowSourceQualityStatusQuery}
        workflowIngestionTone={workflowIngestionTone}
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

  function renderSourceCollectionExtractionRecoveryPanel(
    candidateProjection: SourceCollectionStageCardProjection | null | undefined,
  ) {
    return (
      <TeamSourceCollectionExtractionRecoveryWorkspacePanel
        candidateProjection={candidateProjection}
        lang={lang}
        sourceCollectionRawRecordCount={sourceCollectionRawRecordCount}
        sourceCollectionRunApprovedCount={sourceCollectionRunApprovedCount}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionLoadingText={sourceCollectionLoadingText}
        sourceCollectionCandidateStepState={sourceCollectionCandidateStepState}
        sourceCollectionExtractionExcludedRecoveryState={sourceCollectionExtractionExcludedRecoveryState}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        startSourceCollectionStageSessionTask={startSourceCollectionStageSessionTask}
        runSourceCollectionCandidateExtractionAction={runSourceCollectionCandidateExtractionAction}
        sourceCollectionCandidateExtractionActionReadiness={sourceCollectionCandidateExtractionActionReadiness}
        runSourceCollectionScreeningAction={runSourceCollectionScreeningAction}
        sourceCollectionScreeningActionReadiness={sourceCollectionScreeningActionReadiness}
        sourceCollectionScreeningButtonText={sourceCollectionScreeningButtonText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
      />
    );
  }

  function renderSourceCollectionCandidatePanel() {
    return (
      <TeamSourceCollectionCandidateWorkspacePanel
        lang={lang}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionCandidateProjection={sourceCollectionCandidateProjection}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionCountText={sourceCollectionCountText}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionDataSyncText={sourceCollectionDataSyncText}
        sourceCollectionRunCandidateCount={sourceCollectionRunCandidateCount}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionExtractionDefaultPanelId={sourceCollectionExtractionDefaultPanelId}
        sourceCollectionCandidateStepState={sourceCollectionCandidateStepState}
        sourceCollectionDisplayedCandidateFilterCounts={sourceCollectionDisplayedCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionProjectedAssessedCountText={sourceCollectionProjectedAssessedCountText}
        sourceCollectionProjectedApprovedCountText={sourceCollectionProjectedApprovedCountText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
        sourceCollectionEvidenceReadyCandidateCount={sourceCollectionEvidenceReadyCandidateCount}
        sourceCollectionMissingEvidenceAnchorCount={sourceCollectionMissingEvidenceAnchorCount}
        sourceCollectionProjectedCollectedCount={sourceCollectionProjectedCollectedCount}
        renderSourceCollectionExtractionRecoveryPanel={renderSourceCollectionExtractionRecoveryPanel}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

  function renderSourceCollectionGraphPanel() {
    return (
      <TeamSourceCollectionGraphWorkspacePanel
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
      <TeamSourceCollectionMemoryWorkspacePanel
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
        workflowIngestionTone={workflowIngestionTone}
        teamWorkflowKnowledgeIngestionStatusQuery={teamWorkflowKnowledgeIngestionStatusQuery}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

  function renderSourceCollectionModeFields() {
    if (!knowledgeExpansionWorkflowTeamSelected) {
      return null;
    }
    const mode = sourceCollectionDraft.collectionMode || "mixed";
    return (
      <>
        <label>
          <span>{lang === "zh" ? "来源模式" : "Source mode"}</span>
          <VNativeSelect
            value={mode}
            onChange={(event) =>
              setSourceCollectionDraft((current) => ({
                ...current,
                collectionMode: event.target.value as SourceCollectionMode,
              }))
            }
          >
            {(["mixed", "web_search", "local_workspace"] as SourceCollectionMode[]).map((item) => (
              <option key={item} value={item}>
                {sourceCollectionCollectionModeLabel(item, lang)}
              </option>
            ))}
          </VNativeSelect>
        </label>
        {mode !== "web_search" ? (
          <label>
            <span>{lang === "zh" ? "本地根目录" : "Local roots"}</span>
            <VNativeInput
              value={sourceCollectionDraft.localScanRoots}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, localScanRoots: event.target.value }))}
              placeholder={SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS}
            />
          </label>
        ) : null}
      </>
    );
  }

  function renderSourceCollectionManualWritebackPanel(options?: {
    title?: string;
    description?: string;
    wrapInDetails?: boolean;
  }) {
    return (
      <TeamSourceCollectionManualWritebackPanel
        lang={lang}
        draft={sourceCollectionOutputDraft}
        assignmentValue={sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId || ""}
        assignments={sourceCollectionAssignments.map((assignment) => ({
          id: assignment.assignmentId,
          label: `${sourceCollectionAgentRoleLabel(assignment.agentRole, lang)} · ${sourceCollectionStatusLabel(assignment.status, lang)}`,
        }))}
        sourceTypes={["paper", "url", "dataset", "file", "note", "manual"]}
        canSubmit={canRecordSourceCollectionOutput}
        pending={selectedTeamRecordSourceCollectionOutputPending}
        onDraftChange={(patch) => setSourceCollectionOutputDraft((current) => ({ ...current, ...patch }))}
        onSubmit={(event) => {
          event.preventDefault();
          const assignmentId = sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId || "";
          if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !assignmentId || !sourceCollectionOutputHasRecord) {
            return;
          }
          recordSourceCollectionOutputMutation.mutate({
            teamId: selectedTeam.teamId,
            runId: selectedSourceCollectionRunEffectiveId,
            draft: { ...sourceCollectionOutputDraft, assignmentId },
          });
        }}
        sourceTypeLabel={(sourceType) => sourceCollectionSourceTypeLabel(sourceType, lang)}
        title={options?.title}
        description={options?.description}
        wrapInDetails={options?.wrapInDetails}
      />
    );
  }

  function renderSourceCollectionControlsPanel() {
    const activeModule =
      sourceCollectionStageModules.find((module) => module.id === selectedSourceCollectionStageId)
      ?? sourceCollectionStageModules[0];
    return (
      <TeamSourceCollectionControlsPanel
        ref={sourceCollectionControlPanelRef}
        lang={lang}
        activeRunText={
          selectedSourceCollectionRun
            ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionStageFocusLabel}`
            : lang === "zh" ? "等待启动搜集批次" : "Waiting for a collection run"
        }
        statusClassName={workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}
        statusLabel={sourceCollectionStatusLabel(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "pending", lang)}
        selectedSourcePanel={renderSourceCollectionSelectedSourcePanel()}
      >
        {selectedSourceCollectionStageId === "finding" ? (
        <>
        <TeamSourceCollectionRunSettingsPanel
          lang={lang}
          draft={sourceCollectionDraft}
          modeFields={renderSourceCollectionModeFields()}
          open={!selectedSourceCollectionRun}
          canStart={sourceCollectionCanStart}
          startPending={selectedTeamStartSourceCollectionPending}
          onDraftChange={(patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch }))}
          onSubmit={() => {
            if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
              return;
            }
            startSourceCollectionRunMutation.mutate({
              teamId: selectedTeam.teamId,
              draft: sourceCollectionDraft,
            });
          }}
        />
        <TeamSourceCollectionFindingDetailsPanel
          lang={lang}
          selectedRunId={selectedSourceCollectionRunEffectiveId}
          runs={sourceCollectionFindingRunOptions}
          assignments={sourceCollectionFindingAssignments}
          queries={sourceCollectionFindingQueries}
          storageActions={renderSourceCollectionStorageActions()}
          onRunChange={setSelectedSourceCollectionRunId}
          onAssignmentSelect={(assignmentId) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId }))}
        />
        {renderSourceCollectionManualWritebackPanel()}
        </>
        ) : null}
        {selectedSourceCollectionStageId === "extraction" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "本轮候选" : "run candidates"} <strong>{sourceCollectionDisplayedCandidateCountText}</strong></span>
            <span>{lang === "zh" ? "已审查" : "reviewed"} <strong>{sourceCollectionProjectedAssessedCountText}</strong></span>
            <span>{lang === "zh" ? "通过" : "approved"} <strong>{sourceCollectionProjectedApprovedCountText}</strong></span>
            <span>{lang === "zh" ? "待 Agent 复核" : "pending agent review"} <strong>{sourceCollectionRunPendingScreeningCountText}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "extraction" ? renderSourceCollectionStorageActions() : null}
        {selectedSourceCollectionStageId === "relations" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "节点" : "nodes"} <strong>{candidateGraphNodeCount}</strong></span>
            <span>{lang === "zh" ? "边" : "edges"} <strong>{candidateGraphEdgeCount}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "ingestion" ? (
          <>
            <div className={styles.workflowSourceQualityStats}>
              <span>{lang === "zh" ? "通过资料" : "approved sources"} <strong>{sourceCollectionPrecheckCandidateCount}</strong></span>
              <span>{lang === "zh" ? "待入库" : "pending"} <strong>{knowledgePendingReviewCount}</strong></span>
              <span>{lang === "zh" ? "正式知识" : "formal items"} <strong>{formalKnowledgeItemCount}</strong></span>
              <span>{lang === "zh" ? "关系节点" : "map nodes"} <strong>{candidateGraphNodeCount}</strong></span>
            </div>
            {selectedTeamKnowledgeCollectionIngestResult ? (
              <div className={styles.messageResult}>
                <strong>
                  {selectedTeamKnowledgeCollectionIngestResult.status === "completed"
                    ? (lang === "zh" ? "资料已写入团队知识库" : "Sources ingested into Team Knowledge")
                    : selectedTeamKnowledgeCollectionIngestResult.status === "agent_notified"
                      ? (lang === "zh" ? "已通知资料入库 Agent" : "Source ingestion Agent notified")
                    : selectedTeamKnowledgeCollectionIngestResult.status === "agent_wake_pending"
                      ? (lang === "zh" ? "已发送，等待唤醒 Agent" : "Sent; waiting to wake Agent")
                    : sourceCollectionStatusLabel(selectedTeamKnowledgeCollectionIngestResult.status, lang)}
                </strong>
                <span>
                  {selectedTeamKnowledgeCollectionIngestResult.status === "completed"
                    ? (lang === "zh"
                        ? `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} 条资料通过审查，${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} 条正式知识可用于后续实验。`
                        : `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} sources approved; ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} formal items are ready for experiments.`)
                    : (lang === "zh"
                        ? `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} 条资料通过审查，待入库知识包已发送给资料入库 Agent；当前正式知识 ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} 条。`
                        : `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} sources approved; the ingestion pack was sent to the steward Agent. Current formal items: ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount}.`)}
                </span>
              </div>
            ) : null}
            {selectedTeamKnowledgeCollectionIngestError ? (
              <div className={styles.messageError}>{selectedTeamKnowledgeCollectionIngestError.message}</div>
            ) : null}
          </>
        ) : null}
        {selectedSourceCollectionStageId === "finding" ? (
          <>
            {selectedTeamStartSourceCollectionError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionError.message}</div>
            ) : null}
            {selectedTeamRecordSourceCollectionOutputError ? (
              <div className={styles.messageError}>{selectedTeamRecordSourceCollectionOutputError.message}</div>
            ) : null}
            {selectedTeamExecuteSourceCollectionSearchError ? (
              <div className={styles.messageError}>{selectedTeamExecuteSourceCollectionSearchError.message}</div>
            ) : null}
            {selectedTeamStartSourceCollectionStageTaskError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionStageTaskError.message}</div>
            ) : null}
            {selectedTeamExecuteSourceCollectionSearchResult ? (
              <div className={styles.messageResult}>
                <strong>
                  {selectedTeamExecuteSourceCollectionSearchResult.accepted
                    ? (lang === "zh" ? "搜索已转后台" : "Search queued in background")
                    : (lang === "zh" ? "搜索执行已回写" : "Search execution written")}
                </strong>
                {selectedTeamExecuteSourceCollectionSearchResult.accepted ? (
                  <span>{lang === "zh" ? "页面可继续操作，结果会自动刷新。" : "You can keep working; results will refresh automatically."}</span>
                ) : (
                  <span>
                    {selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} {lang === "zh" ? "条搜索" : "queries"} / {selectedTeamExecuteSourceCollectionSearchResult.recordCount} {lang === "zh" ? "条资料记录" : "DataRecord"} / {selectedTeamExecuteSourceCollectionSearchResult.importedCount} {lang === "zh" ? "个候选" : "candidate"}{selectedTeamExecuteSourceCollectionSearchResult.skippedDuplicateCount ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.skippedDuplicateCount} ${lang === "zh" ? "条重复跳过" : "duplicates skipped"}` : ""}{selectedTeamExecuteSourceCollectionSearchResult.filteredExcludedCount ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.filteredExcludedCount} ${lang === "zh" ? "条无效来源已过滤" : "excluded sources filtered"}` : ""}{selectedTeamExecuteSourceCollectionSearchResult.hasMore ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.remainingQueryCount ?? 0} ${lang === "zh" ? "条待继续" : "remaining"}` : ""}
                  </span>
                )}
              </div>
            ) : null}
            {selectedTeamRecordSourceCollectionOutputResult ? (
              <div className={styles.messageResult}>
                <strong>{lang === "zh" ? "已回写" : "Written"}</strong>
                <span>
                  {selectedTeamRecordSourceCollectionOutputResult.output.createdRecords.length} {lang === "zh" ? "条资料记录" : "DataRecord"} / {selectedTeamRecordSourceCollectionOutputResult.imported.length} {lang === "zh" ? "个候选" : "candidate"}
                </span>
              </div>
            ) : null}
          </>
        ) : null}
        {renderSourceCollectionStageAgents(activeModule.id)}
      </TeamSourceCollectionControlsPanel>
    );
  }

  function renderSourceCollectionActiveStagePanel() {
    const activeModule =
      sourceCollectionStageModules.find((module) => module.id === selectedSourceCollectionStageId)
      ?? sourceCollectionStageModules[0];
    const primaryStageAgentChatState = sourceCollectionStageAgentChatState(activeModule.id);
    const primaryStageAgentChatRoute = primaryStageAgentChatState.route;
    const primaryStageAgentChatLoading = primaryStageAgentChatState.status === "loading";
    const primaryStageAgentChatError = primaryStageAgentChatState.status === "error";
    const primaryStageAgentRepairPending =
      primaryStageAgentChatState.status === "repair" && repairChallengeCupTeamAgentsMutation.isPending;
    const primaryStageAgentFallbackTitle = primaryStageAgentChatLoading
      ? (lang === "zh" ? "正在加载 Agent 配置，请稍候" : "Loading Agent configuration")
      : primaryStageAgentChatError
        ? (lang === "zh" ? "Agent 配置加载失败，请刷新后重试" : "Agent configuration failed to load")
        : (lang === "zh" ? "当前步骤缺少可用私聊，请先修复团队 Agent 绑定" : "No usable direct chat for this step");
    const primaryStageAgentFallbackLabel = primaryStageAgentChatLoading
      ? (lang === "zh" ? "加载 Agent..." : "Loading Agent...")
      : primaryStageAgentChatError
        ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
        : primaryStageAgentRepairPending
          ? (lang === "zh" ? "修复中" : "Repairing")
          : (lang === "zh" ? "修复团队 Agent" : "Repair Team Agents");
    const primaryStageAgentBinding = sourceCollectionStagePrimaryAgentBinding(activeModule.id);
    const primaryStageAgentConfigRoute = primaryStageAgentBinding?.agentId
      ? researchStageAgentManagementRoute(primaryStageAgentBinding.agentId)
      : "/agents";
    const primaryStageAgentConfigLabel = primaryStageAgentBinding?.agent
      ? (lang === "zh" ? "配置 Agent" : "Configure Agent")
      : (lang === "zh" ? "绑定 Agent" : "Bind Agent");
    const sourceCollectionActiveStageCompact =
      activeModule.id === "finding" && sourceCollectionFindingStageCompact;
    return (
      <TeamSourceCollectionActiveStagePanel
        lang={lang}
        stageId={selectedSourceCollectionStageId}
        compact={sourceCollectionActiveStageCompact}
        title={activeModule.label}
        status={activeModule.status}
        inputLabel={activeModule.inputLabel}
        outputLabel={activeModule.outputLabel}
        nextLabel={activeModule.nextLabel}
        primaryAction={{
          tone: activeModule.actionTone,
          disabled: activeModule.actionDisabled,
          onAction: activeModule.onAction,
          title: sourceCollectionActionDisabledTitle(sourceCollectionStageActionReadinessFor(activeModule.id), activeModule.actionLabel),
          icon: activeModule.actionIcon,
          label: activeModule.actionLabel,
        }}
        agentChatAction={primaryStageAgentChatRoute ? (
          <Link
            to={primaryStageAgentChatRoute}
            title={SOURCE_COLLECTION_STAGE_CHAT_LABELS[activeModule.id][lang]}
          >
            <MessageSquare size={13} />
            {lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"}
          </Link>
        ) : (
          <VNativeButton
            type="button"
            title={primaryStageAgentFallbackTitle}
            onClick={() => openSourceCollectionStageAgentChat(activeModule.id)}
            disabled={primaryStageAgentChatLoading || primaryStageAgentChatError || primaryStageAgentRepairPending}
          >
            <MessageSquare size={13} />
            {primaryStageAgentFallbackLabel}
          </VNativeButton>
        )}
        agentConfigAction={(
          <VTooltip content={lang === "zh" ? "当前阶段 Agent 配置" : "Current stage Agent configuration"}>
            <Link to={primaryStageAgentConfigRoute}>
              <Link2 size={13} />
              {primaryStageAgentConfigLabel}
            </Link>
          </VTooltip>
        )}
        errors={(
          <>
            {repairChallengeCupTeamAgentsMutation.error instanceof Error ? (
              <div className={styles.messageError}>{repairChallengeCupTeamAgentsMutation.error.message}</div>
            ) : null}
            {selectedTeamStartSourceCollectionStageTaskError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionStageTaskError.message}</div>
            ) : null}
          </>
        )}
        renderConversationPanel={renderSourceCollectionConversation}
        renderCandidatePanel={renderSourceCollectionCandidatePanel}
        renderScreeningPanel={renderSourceCollectionScreeningPanel}
        renderGraphPanel={renderSourceCollectionGraphPanel}
        renderMemoryPanel={renderSourceCollectionMemoryPanel}
      />
    );
  }

  function renderResearchLoopPanel(activePlan: ExperimentPlanRecord | null, variant: "experiment" | "iteration" = "experiment") {
    return (
      <TeamResearchLoopPanel
        activePlan={activePlan}
        variant={variant}
        lang={lang}
        selectedTeam={selectedTeam}
        researchLoopStatus={researchLoopStatus}
        researchLoopTemplatesPayload={researchLoopTemplatesPayload}
        selectedResearchLoopTemplateId={selectedResearchLoopTemplateId}
        setSelectedResearchLoopTemplateId={setSelectedResearchLoopTemplateId}
        researchLoopCreateDraft={researchLoopCreateDraft}
        setResearchLoopCreateDraft={setResearchLoopCreateDraft}
        researchLoopEvidenceDraft={researchLoopEvidenceDraft}
        setResearchLoopEvidenceDraft={setResearchLoopEvidenceDraft}
        researchLoopDecisionDraft={researchLoopDecisionDraft}
        setResearchLoopDecisionDraft={setResearchLoopDecisionDraft}
        sourceCollectionDraft={sourceCollectionDraft}
        researchLoopStatusQuery={researchLoopStatusQuery}
        selectedTeamCreateResearchLoopPending={selectedTeamCreateResearchLoopPending}
        selectedTeamCreateResearchLoopError={selectedTeamCreateResearchLoopError}
        selectedTeamCreateResearchLoopResult={selectedTeamCreateResearchLoopResult}
        selectedTeamRecordResearchLoopEvidencePending={selectedTeamRecordResearchLoopEvidencePending}
        selectedTeamRecordResearchLoopEvidenceError={selectedTeamRecordResearchLoopEvidenceError}
        selectedTeamRecordResearchLoopEvidenceResult={selectedTeamRecordResearchLoopEvidenceResult}
        selectedTeamRecordResearchLoopDecisionPending={selectedTeamRecordResearchLoopDecisionPending}
        selectedTeamRecordResearchLoopDecisionError={selectedTeamRecordResearchLoopDecisionError}
        selectedTeamRecordResearchLoopDecisionResult={selectedTeamRecordResearchLoopDecisionResult}
        materializeResearchLoopIterationDesignMutation={materializeResearchLoopIterationDesignMutation}
        createResearchLoopFromWorkspace={createResearchLoopFromWorkspace}
        recordResearchLoopEvidenceFromWorkspace={recordResearchLoopEvidenceFromWorkspace}
        recordResearchLoopDecisionFromWorkspace={recordResearchLoopDecisionFromWorkspace}
      />
    );
  }

  function renderExperimentPlanningLedgerPanel() {
    return (
      <TeamExperimentPlanningLedgerPanel
        lang={lang}
        selectedTeam={selectedTeam}
        experimentPlanningStatus={experimentPlanningStatus}
        experimentPlanningStatusQuery={experimentPlanningStatusQuery}
        experimentMethodCatalogQuery={experimentMethodCatalogQuery}
        preferredExperimentMethod={preferredExperimentMethod}
        searchParams={searchParams}
        experimentBaselineArtifactDraft={experimentBaselineArtifactDraft}
        setExperimentBaselineArtifactDraft={setExperimentBaselineArtifactDraft}
        experimentSmokeResultDraft={experimentSmokeResultDraft}
        setExperimentSmokeResultDraft={setExperimentSmokeResultDraft}
        experimentFullRunResultDraft={experimentFullRunResultDraft}
        setExperimentFullRunResultDraft={setExperimentFullRunResultDraft}
        experimentKnowledgeIngestionDraft={experimentKnowledgeIngestionDraft}
        setExperimentKnowledgeIngestionDraft={setExperimentKnowledgeIngestionDraft}
        selectedTeamCreateExperimentPlanPending={selectedTeamCreateExperimentPlanPending}
        selectedTeamCreateExperimentPlanError={selectedTeamCreateExperimentPlanError}
        selectedTeamCreateExperimentPlanResult={selectedTeamCreateExperimentPlanResult}
        selectedTeamFreezeExperimentDesignPending={selectedTeamFreezeExperimentDesignPending}
        selectedTeamFreezeExperimentDesignError={selectedTeamFreezeExperimentDesignError}
        selectedTeamFreezeExperimentDesignResult={selectedTeamFreezeExperimentDesignResult}
        selectedTeamRegisterExperimentBaselineArtifactPending={selectedTeamRegisterExperimentBaselineArtifactPending}
        selectedTeamRegisterExperimentBaselineArtifactError={selectedTeamRegisterExperimentBaselineArtifactError}
        selectedTeamRegisterExperimentBaselineArtifactResult={selectedTeamRegisterExperimentBaselineArtifactResult}
        selectedTeamRegisterExperimentSmokeResultPending={selectedTeamRegisterExperimentSmokeResultPending}
        selectedTeamRegisterExperimentSmokeResultError={selectedTeamRegisterExperimentSmokeResultError}
        selectedTeamRegisterExperimentSmokeResultResult={selectedTeamRegisterExperimentSmokeResultResult}
        selectedTeamRegisterExperimentFullRunResultPending={selectedTeamRegisterExperimentFullRunResultPending}
        selectedTeamRegisterExperimentFullRunResultError={selectedTeamRegisterExperimentFullRunResultError}
        selectedTeamRegisterExperimentFullRunResultResult={selectedTeamRegisterExperimentFullRunResultResult}
        selectedTeamRequestExperimentKnowledgeIngestionPending={selectedTeamRequestExperimentKnowledgeIngestionPending}
        selectedTeamRequestExperimentKnowledgeIngestionError={selectedTeamRequestExperimentKnowledgeIngestionError}
        selectedTeamRequestExperimentKnowledgeIngestionResult={selectedTeamRequestExperimentKnowledgeIngestionResult}
        createExperimentPlanFromWorkspace={createExperimentPlanFromWorkspace}
        freezeExperimentDesignFromWorkspace={freezeExperimentDesignFromWorkspace}
        registerExperimentBaselineArtifactFromWorkspace={registerExperimentBaselineArtifactFromWorkspace}
        registerExperimentSmokeResultFromWorkspace={registerExperimentSmokeResultFromWorkspace}
        registerExperimentFullRunResultFromWorkspace={registerExperimentFullRunResultFromWorkspace}
        requestExperimentKnowledgeIngestionFromWorkspace={requestExperimentKnowledgeIngestionFromWorkspace}
        renderResearchLoopPanel={renderResearchLoopPanel}
      />
    );
  }

  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">) {
    return (
      <TeamResearchStageStandalonePagePanel
        stageView={stageView}
        lang={lang}
        researchStagePhases={researchStagePhases}
        experimentPlanningStatus={experimentPlanningStatus}
        selectedTeam={selectedTeam}
        selectedTeamStartResearchStagePending={selectedTeamStartResearchStagePending}
        linkedChatRoomId={linkedChatRoomId || ""}
        syncTeamChatRoomMutation={syncTeamChatRoomMutation}
        activeTeamMemberCount={activeTeamMemberCount}
        selectedTeamSyncPending={selectedTeamSyncPending}
        researchStageRoundStatusQuery={researchStageRoundStatusQuery}
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
  const sourceCollectionStageRound = useMemo(() => {
    const knowledgePhase = researchStagePhases.find((phase) => phase.stageType === "knowledge_collection");
    const candidateRounds = [
      sourceCollectionSummaryStageRound,
      knowledgePhase?.latestRound ?? null,
      researchStageRoundStatus?.latestRound ?? null,
      ...(researchStageRoundStatus?.activeRounds ?? []),
    ].filter((round): round is ResearchStageRound => Boolean(round && round.stageType === "knowledge_collection"));
    const dedupedRounds = new Map<string, ResearchStageRound>();
    candidateRounds.forEach((round) => {
      dedupedRounds.set(round.stageRoundId || `${round.stageType}-${round.roundNumber}`, round);
    });
    const rounds = [...dedupedRounds.values()];
    if (!selectedSourceCollectionRunEffectiveId) {
      return rounds[0] ?? null;
    }
    const matchingRound = rounds.find((round) => (round.sourceRunIds ?? []).includes(selectedSourceCollectionRunEffectiveId));
    return matchingRound ?? null;
  }, [
    researchStagePhases,
    researchStageRoundStatus?.activeRounds,
    researchStageRoundStatus?.latestRound,
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
  const selectedTeamStartResearchStagePending =
    startResearchStageRoundMutation.isPending && startResearchStageRoundMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartResearchStageError =
    startResearchStageRoundMutation.variables?.teamId === selectedTeam?.teamId && startResearchStageRoundMutation.error instanceof Error
      ? startResearchStageRoundMutation.error
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
    Number(sourceCollectionRecordsQuery.data?.summary?.recordCount ?? sourceCollectionSummaryCounts.recordCount ?? sourceCollectionRunSummary?.recordCount ?? sourceCollectionRecords.length) || 0;
  const sourceCollectionRecordClickableSourceCount = sourceCollectionRecordProvenances.filter((item) => item.href).length;
  const sourceCollectionRecordLocalFileCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "file").length;
  const sourceCollectionRecordMissingSourceCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "missing").length;
  const sourceCollectionRunCandidateCount = sourceCollectionRunCandidates.length;
  const sourceCollectionRecordFilterCounts = sourceCollectionFilterCounts(sourceCollectionRecordSourceCategories);
  const sourceCollectionCandidateFilterCounts = sourceCollectionFilterCounts(sourceCollectionRunCandidateSourceCategories);
  const sourceCollectionRunAssessedCount = sourceCollectionRunCandidates.filter((candidate) => sourceCollectionCandidateQualityState(candidate).assessed).length;
  const sourceCollectionRunApprovedCount = sourceCollectionRunCandidates.filter((candidate) => sourceCollectionCandidateQualityState(candidate).approved).length;
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
    sourceCollectionRecordsQueryEnabled
    && !sourceCollectionRecordsQuery.data
    && !sourceCollectionSummaryHasRecordCount
    && !sourceCollectionRunSummaryHasRecordCount
    && (
      sourceCollectionRecordsQuery.isPending
      || sourceCollectionRunStatusQuery.isPending
    ),
  );
  const sourceCollectionAssignmentsDataLoading = Boolean(
    sourceCollectionAssignmentsQueryEnabled
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
  const sourceCollectionProjectedAssessedCount = sourceCollectionStageProjectionCount(
    sourceCollectionScreeningProjection,
    "artifact",
    sourceCollectionRunAssessedCount,
  );
  const sourceCollectionProjectedApprovedCount = sourceCollectionStageProjectionCount(
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
          || (sourceCollectionSummaryQuery.isPending && sourceCollectionWorkspaceSelected && !sourceCollectionSummaryQuery.data)
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
  const sourceCollectionRunPendingScreeningCount = Math.max(0, sourceCollectionProjectedCandidateCount - sourceCollectionProjectedAssessedCount);
  const sourceCollectionRunPendingScreeningCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionRunPendingScreeningCount);
  const sourceCollectionPendingCandidateImportCount = Math.max(0, sourceCollectionRawRecordCount - sourceCollectionDisplayedCandidateCount);
  const sourceCollectionExtractionRecoveryCoverage = sourceCollectionCandidateProjection?.currentCoverageSummary?.complete === false
    ? sourceCollectionCandidateProjection.currentCoverageSummary
    : sourceCollectionCandidateProjection?.latestTask?.coverageSummary;
  const sourceCollectionExtractionRecoveryClosure = sourceCollectionCandidateProjection?.latestTask?.closureSummary;
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
  const sourceCollectionScreeningButtonText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "Agent 复核中" : "Agent reviewing")
    : sourceCollectionRunPendingScreeningCount > 0
      ? (lang === "zh" ? "Agent 提炼复核" : "Agent review")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "Agent 重新提炼复核" : "Agent re-review")
        : (lang === "zh" ? "资料提炼复核" : "Review");
  const sourceCollectionScreeningStatusText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "进行中" : "running")
    : sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingText
    : sourceCollectionRunPendingScreeningCount > 0
      ? `${sourceCollectionRunPendingScreeningCountText} ${lang === "zh" ? "待 Agent 复核" : "pending agent review"}`
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
    if (panelId === "source-collection-candidates-panel") {
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
        ? "Source Extractor Agent re-screened already assessed source_manifest candidates on user request."
        : "Source Extractor Agent screened pending source_manifest candidates.",
    });
  };
  const openSourceCollectionCandidatePanel = () => {
    if (!selectedTeam?.teamId) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-candidates-panel");
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
    if (sourceCollectionStageSessionTaskPendingStageId === stageId) {
      return true;
    }
    const pendingTaskIds = sourceCollectionPendingStageTaskIds[stageId] ?? [];
    if (!sourceCollectionStageWritebackSyncActive || pendingTaskIds.length <= 0) {
      return false;
    }
    const projection = sourceCollectionStageCardById.get(stageId);
    const latestTaskId = projection?.latestTask?.taskId || "";
    if (latestTaskId && pendingTaskIds.includes(latestTaskId)) {
      const latestTaskStatus = String(projection?.latestTask?.status || "").toLowerCase();
      const projectionStatus = String(projection?.status || "").toLowerCase();
      return !SOURCE_COLLECTION_STAGE_TERMINAL_TASK_STATUSES.has(latestTaskStatus)
        && !SOURCE_COLLECTION_STAGE_TERMINAL_PROJECTION_STATUSES.has(projectionStatus);
    }
    return true;
  }
  function sourceCollectionStageLaunchSummary(stageId: SourceCollectionStageModuleId) {
    if (sourceCollectionStageSessionTaskPendingStageId === stageId) {
      return lang === "zh"
        ? "Agent 已启动，正在进入私聊并准备执行本阶段任务。"
        : "Agent started and the private chat is opening for this stage.";
    }
    return lang === "zh"
      ? "等待 Agent 回写。团队页正在同步本阶段结果。"
      : "Waiting for Agent writeback. The team page is syncing this stage result.";
  }
  function sourceCollectionStageDisplayState(stageId: SourceCollectionStageModuleId, fallback: SourceCollectionStepState) {
    return sourceCollectionStageLaunchActive(stageId) ? "active" : fallback;
  }
  function sourceCollectionStageDisplayStatus(stageId: SourceCollectionStageModuleId, fallback: string) {
    if (!sourceCollectionStageLaunchActive(stageId)) {
      return fallback;
    }
    return sourceCollectionStageSessionTaskPendingStageId === stageId
      ? (lang === "zh" ? "Agent 已启动" : "Agent started")
      : (lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback");
  }
  function sourceCollectionStageDisplaySummary(stageId: SourceCollectionStageModuleId, fallback: string) {
    return sourceCollectionStageLaunchActive(stageId) ? sourceCollectionStageLaunchSummary(stageId) : fallback;
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
  const sourceCollectionExtractionDefaultPanelId =
    sourceCollectionRunPendingScreeningCount > 0
    || sourceCollectionScreeningStepState === "active"
    || sourceCollectionScreeningStepState === "pending"
      ? "source-collection-screening-panel"
      : "source-collection-candidates-panel";
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
  const sourceCollectionExtractionLoadingOutputLabel = sourceCollectionProjectedCandidateCount > 0 || sourceCollectionProjectedApprovedCount > 0
    ? (lang === "zh"
      ? `${sourceCollectionProjectedApprovedCount} 条保留 / ${sourceCollectionRunPendingScreeningCount} 条待处理 · ${sourceCollectionDataSyncText}`
      : `${sourceCollectionProjectedApprovedCount} kept / ${sourceCollectionRunPendingScreeningCount} pending · ${sourceCollectionDataSyncText}`)
    : (lang === "zh" ? "提炼结果加载中" : "extraction result loading");
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
        : (lang === "zh" ? `已处理 ${sourceCollectionProjectedAssessedCountText}/${sourceCollectionProjectedCandidateCountText}` : `${sourceCollectionProjectedAssessedCountText}/${sourceCollectionProjectedCandidateCountText} processed`),
      summary: sourceCollectionStageLaunchActive("extraction")
        ? sourceCollectionStageLaunchSummary("extraction")
        : sourceCollectionExtractionDisplayLoading
        ? sourceCollectionLoadingSummary
        : sourceCollectionExtractionCanProceedAfterExclusions
        ? sourceCollectionExtractionProceedableSummary
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
          : (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条保留 / ${sourceCollectionRunPendingScreeningCountText} 条待处理` : `${sourceCollectionProjectedApprovedCountText} kept / ${sourceCollectionRunPendingScreeningCountText} pending`),
      nextLabel: sourceCollectionRunPendingScreeningCount > 0
        ? (lang === "zh" ? "Agent 继续提炼" : "Agent continues extraction")
        : (lang === "zh" ? "进入资料关系整理" : "Move to relation mapping"),
      state: sourceCollectionStageDisplayState("extraction", sourceCollectionExtractionCanProceedAfterExclusions ? "done" : sourceCollectionExtractionDisplayState),
      status: sourceCollectionStageDisplayStatus(
        "extraction",
        sourceCollectionExtractionDisplayLoading
          ? sourceCollectionCandidateSyncStatusText
          : sourceCollectionExtractionCanProceedAfterExclusions
            ? sourceCollectionExtractionExcludedRecoveryState.statusLabel
            : sourceCollectionStepStatusText(sourceCollectionExtractionStepState),
      ),
      detailLabel: lang === "zh" ? "查看提炼结果" : "View extraction details",
      actionLabel: sourceCollectionExtractionCanProceedAfterExclusions
        ? sourceCollectionExtractionExcludedRecoveryState.primaryActionText
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
      nextLabel: sourceCollectionProjectedFormalKnowledgeCount > 0
        ? (lang === "zh" ? "进入实验规划" : "Move to experiment planning")
        : sourceCollectionProjectedStewardPackCount > 0
          ? (lang === "zh" ? "等待入库完成" : "Wait for ingestion")
          : (lang === "zh" ? "Agent 入库资料" : "Agent ingest sources"),
      state: sourceCollectionStageDisplayState("ingestion", sourceCollectionIngestionDisplayState),
      status: sourceCollectionStageDisplayStatus("ingestion", sourceCollectionIngestionDisplayLoading ? sourceCollectionDataSyncText : sourceCollectionStepStatusText(sourceCollectionMemoryStepState)),
      detailLabel: lang === "zh" ? "查看入库详情" : "View ingestion details",
      actionLabel: sourceCollectionStageActionLabelFor("ingestion", sourceCollectionMemoryActionLabel),
      actionDisabled: sourceCollectionStageActionReadinessFor("ingestion").disabled,
      actionTone: "primary",
      actionIcon: "check",
      projection: sourceCollectionMemoryProjection,
      onAction: () => void startSourceCollectionStageSessionTask("ingestion"),
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
  const researchCanvasVisible = researchCanvasReadOnly;
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
    researchWorkflowTeamSelected && !researchCanvasVisible ? styles.workspaceResearch : "",
    researchCanvasVisible ? styles.workspaceResearchCanvas : "",
    challengeCupResearchTeamSelected && !researchCanvasVisible ? styles.challengeWorkspaceLayout : "",
  ].filter(Boolean).join(" ");
  const canvasPanelClassName = [
    styles.canvasPanel,
    researchWorkflowTeamSelected && !researchCanvasVisible ? styles.researchCanvasPanelHidden : "",
  ].filter(Boolean).join(" ");
  const inspectorClassName = [
    styles.inspector,
    researchWorkflowTeamSelected ? styles.researchInspector : "",
    challengeCupResearchTeamSelected && !researchCanvasVisible ? styles.challengeWorkspaceInspector : "",
  ].filter(Boolean).join(" ");
  const showNodeBindingPanel = !researchWorkflowTeamSelected || (researchCanvasVisible && !researchCanvasReadOnly);
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
            ? [{ key: "decision", label: lang === "zh" ? "待提炼复核" : "pending extraction review" }]
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
            <p>{lang === "zh" ? "挑战杯ai科研团队 / 知识搜集阶段" : "Challenge Cup AI research team / knowledge collection stage"}</p>
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
            commandTitle={sourceCollectionRunTitleLabel(selectedSourceCollectionRun?.title || sourceCollectionDraft.title, lang)}
            commandSubtitle={sourceCollectionDecisionText}
            commandStats={[
              { key: "status", label: lang === "zh" ? "当前" : "status", value: sourceCollectionConsoleStatusText },
              { key: "next", label: lang === "zh" ? "下一步" : "next", value: sourceCollectionBoardNextStepLabel },
              { key: "sources", label: lang === "zh" ? "资料" : "sources", value: sourceCollectionCollectedCountLabel },
            ]}
            runSwitcher={renderSourceCollectionRunSwitcher()}
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

  return (
    <VDenseOpsPage
      className={styles.route}
      headerClassName={challengeCupResearchTeamSelected && !researchCanvasVisible ? styles.challengeWorkspaceContextHidden : styles.teamContextBar}
      data-vui-domain-recipe="teams-organization-workbench"
      ariaLabel={selectedTeamContextTitle}
      eyebrow={lang === "zh" ? "团队工作台 / 组织画布" : "Team Workspace / Canvas"}
      title={lang === "zh" ? "团队组织画布" : "Team Organization Canvas"}
      meta={teamContextMeta}
      actions={(
          <div className={styles.teamContextActions}>
            <div className={styles.teamSelectField}>
              <span className={styles.teamSelectPrefix}>{lang === "zh" ? "团队" : "Team"}</span>
              <VSelect
                aria-label={lang === "zh" ? "选择团队" : "Select team"}
                className={styles.teamSelectControl}
                selectedKey={selectedTeam?.teamId ?? effectiveTeamId}
                options={visibleTeamOptions}
                placeholder={selectedTeam?.name ?? (lang === "zh" ? "选择团队" : "Select team")}
                isDisabled={!visibleTeams.length}
                onSelectionChange={(key) => {
                  const nextTeam = visibleTeams.find((team) => team.teamId === String(key));
                  if (nextTeam) {
                    selectTeamRecord(nextTeam);
                  }
                }}
              />
            </div>
            <VIconButton
              className={styles.teamRefreshButton}
              label={lang === "zh" ? "刷新团队" : "Refresh teams"}
              icon={<RefreshCw size={15} />}
              onPress={() => void teamsQuery.refetch()}
            />
          </div>
      )}
    >
      {challengeCupResearchTeamSelected && !researchCanvasVisible ? null : (
        <VStatusStrip
          className={styles.teamContextChips}
          aria-label={lang === "zh" ? "团队概况" : "Team summary"}
          items={teamSummaryStatusItems}
        />
      )}
      {showTeamInitialLoadingSurface ? (
        <main className={styles.teamUnavailableSurface} aria-label={teamInitialLoadingTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
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
      ) : showTeamDetailUnavailableSurface ? (
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
      ) : (
      <div
        ref={teamsLayoutRef}
        className={workspaceClassName}
        style={teamsLayoutStyle}
        data-vui-recipe="teams-organization-workbench"
        data-vui-layout-id={TEAMS_LAYOUT_ID}
      >
        <VSurface
          as="main"
          className={canvasPanelClassName}
          elevation="panel"
          padding="none"
          tone="rail"
          id="research-organization-canvas"
          data-vui-region="teams-canvas"
        >
          <div className={styles.canvasToolbar}>
            <div>
              <strong>{selectedTeam?.name ?? (lang === "zh" ? "暂无团队" : "No team")}</strong>
              <span>{canvas ? `${canvas.path} · ${TEAM_ORGANIZATION_CANVAS_KIND}` : "workspace/teams"}</span>
              {canvas ? (
                <small className={styles.edgeLayerLine}>
                  {lang === "zh" ? "组织线" : "Org lines"} {organizationEdges.length}
                  {" · "}
                  {lang === "zh" ? "信息线" : "Info lines"} {communicationEdges.length}
                </small>
              ) : null}
              {selectedTeam?.linkedChatRoom ? (
                <small className={styles.linkedRoomLine}>
                  {lang === "zh" ? "已衔接群聊" : "Linked room"}
                  {" · "}
                  {selectedTeam.linkedChatRoom.title}
                  {" · "}
                  {selectedTeam.linkedChatRoom.participantCount} agents
                  {" · "}
                  {teamConversationStatusLabel(conversationProjection?.status || "linked", lang)}
                </small>
              ) : selectedTeam ? (
                <small className={styles.linkedRoomLine}>
                  {researchCanvasReadOnly
                    ? (lang === "zh" ? "只读关系图：不会同步群聊或修改节点。" : "Read-only graph: room sync and node edits are disabled.")
                    : conversationProjection?.status === "agent_missing"
                    ? (lang === "zh" ? `成员缺失 ${conversationProjection.missingAgentCount} 个，请先修复 Agent 引用。` : `${conversationProjection.missingAgentCount} missing agents. Repair Agent references first.`)
                    : activeTeamMemberCount > 0
                    ? (lang === "zh" ? "尚未衔接群聊，可同步创建。" : "No linked room yet. Sync to create one.")
                    : (lang === "zh" ? "绑定 active Agent 后可衔接群聊。" : "Bind active agents before linking a room.")}
                </small>
              ) : null}
            </div>
            <VActionGroup
              className={styles.toolbarActions}
              ariaLabel={lang === "zh" ? "团队画布操作" : "Team canvas actions"}
            >
              {researchCanvasReadOnly ? (
                <span className={styles.canvasReadOnlyBadge}>{lang === "zh" ? "只读" : "Read only"}</span>
              ) : saveLabel ? (
                <span className={styles.saveState}>{saveLabel}</span>
              ) : null}
              {researchCanvasReadOnly ? (
                <div className={styles.canvasLayoutModeSwitch} role="group" aria-label={lang === "zh" ? "画布排版模式" : "Canvas layout mode"}>
                  <VTooltip content={lang === "zh" ? "自动排版只改变当前显示，不保存坐标" : "Auto layout only changes the current view and does not save coordinates"}>
                    <VNativeButton
                      type="button"
                      className={researchCanvasAutoLayoutActive ? styles.layerButtonActive : ""}
                      onClick={() => setResearchCanvasLayoutMode("auto")}
                    >
                      <RefreshCw size={14} />
                      {lang === "zh" ? "自动排版" : "Auto layout"}
                    </VNativeButton>
                  </VTooltip>
                  <VTooltip content={lang === "zh" ? "显示画布文件中的原始坐标" : "Show the original coordinates from the canvas file"}>
                    <VNativeButton
                      type="button"
                      className={!researchCanvasAutoLayoutActive ? styles.layerButtonActive : ""}
                      onClick={() => setResearchCanvasLayoutMode("source")}
                    >
                      {lang === "zh" ? "原始坐标" : "Original"}
                    </VNativeButton>
                  </VTooltip>
                </div>
              ) : null}
              <VTooltip content={communicationEdgeHint}>
                <VNativeButton
                  type="button"
                  className={showCommunicationEdges ? styles.layerButtonActive : ""}
                  onClick={() => setShowCommunicationEdges((current) => !current)}
                  disabled={!canvas || communicationEdges.length === 0}
                >
                  <Link2 size={14} />
                  {communicationEdgeButtonLabel}
                </VNativeButton>
              </VTooltip>
              {researchCanvasReadOnly ? (
                <Link className={styles.toolbarLink} to={teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
                  <ArrowLeft size={14} />
                  {lang === "zh" ? "返回三阶段" : "Back to stages"}
                </Link>
              ) : (
                <>
                  {linkedChatRoomId ? (
                    <Link className={styles.toolbarLink} to={teamChatRoomRoute(linkedChatRoomId, teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID), lang === "zh" ? "返回团队页面" : "Back to team")}>
                      {lang === "zh" ? "打开群聊" : "Open room"}
                    </Link>
                  ) : (
                    <VNativeButton
                      type="button"
                      onClick={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
                      disabled={!selectedTeam || activeTeamMemberCount === 0 || selectedTeamSyncPending}
                    >
                      <Link2 size={14} />
                      {selectedTeamSyncPending
                        ? (lang === "zh" ? "同步中" : "Syncing")
                        : (lang === "zh" ? "同步群聊" : "Sync room")}
                    </VNativeButton>
                  )}
                  <VNativeButton type="button" onClick={addNode} disabled={!hasWritableCanvas}>
                    <Plus size={14} />
                    {lang === "zh" ? "节点" : "Node"}
                  </VNativeButton>
                  <VNativeButton
                    type="button"
                    className={styles.dangerButton}
                    onClick={() => selectedTeam?.teamId && archiveTeamMutation.mutate(selectedTeam.teamId)}
                    disabled={!selectedTeam || selectedTeamArchivePending || Boolean(selectedTeamArchiveDisabledReason)}
                    title={selectedTeamArchiveDisabledReason || (lang === "zh" ? "归档当前团队" : "Archive this team")}
                  >
                    <Archive size={14} />
                    {lang === "zh" ? "归档" : "Archive"}
                  </VNativeButton>
                </>
              )}
            </VActionGroup>
          </div>
          {showTeamLoadingSurface ? (
            <VStateSurface
              className={styles.teamLoadingInlineSurface}
              icon={<RefreshCw size={15} />}
              role="status"
              skeletonLines
              title={teamWorkspaceLoadingTitle}
              tone="loading"
              facts={[
                { key: "team", label: lang === "zh" ? "团队" : "Team", value: selectedTeamReference?.name ?? effectiveTeamId },
                { key: "detail", label: lang === "zh" ? "详情" : "Details", value: teamDetailLoadMode },
                { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Team detail API" },
              ]}
            >
              {teamWorkspaceLoadingMessage}
            </VStateSurface>
          ) : null}
          {renderKnowledgeCollectionCompletionFlowPanel()}
          {canvas ? (
            <div className={styles.canvas} ref={canvasFrameRef}>
              <div className={styles.canvasViewport} style={canvasViewportStyle}>
                <svg className={styles.edges} width="100%" height="100%" aria-hidden="true">
                  <defs>
                    <marker
                      id="team-edge-arrow"
                      viewBox="0 0 10 10"
                      refX="10"
                      refY="5"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" />
                    </marker>
                  </defs>
                  {visibleEdges.map((edge) => {
                    const line = edgeLine(edge, displayCanvasNodes, visibleEdges);
                    return line ? (
                      <path
                        key={edge.id}
                        className={isCommunicationEdge(edge) ? styles.edgeCommunication : styles.edgeOrganization}
                        d={`M ${line.x1} ${line.y1} Q ${line.cx} ${line.cy} ${line.x2} ${line.y2}`}
                      />
                    ) : null;
                  })}
                </svg>
                {displayCanvasNodes.map((node) => {
                  const agent = activeAgents.find((item) => item.agentId === node.agentId);
                  const display = agent ? agentDisplayInfo(agent, lang) : null;
                  const functionLabel = teamNodeFunctionLabel(node, display?.functionLabel, lang);
                  return (
                    <VNativeButton
                      key={node.id}
                      type="button"
                      className={[
                        styles.node,
                        nodeTone(node),
                        selectedNode?.id === node.id ? styles.nodeActive : "",
                        researchCanvasReadOnly ? styles.nodeReadOnly : "",
                      ].filter(Boolean).join(" ")}
                      style={teamCanvasNodeStyle(node)}
                      title={researchCanvasReadOnly ? (lang === "zh" ? "点击查看节点详情" : "Click to inspect node") : (lang === "zh" ? "拖动调整节点位置" : "Drag to reposition")}
                      onPointerDown={researchCanvasReadOnly ? undefined : (event) => startNodeDrag(event, node)}
                      onPointerMove={researchCanvasReadOnly ? undefined : moveNodeDrag}
                      onPointerUp={researchCanvasReadOnly ? undefined : finishNodeDrag}
                      onPointerCancel={researchCanvasReadOnly ? undefined : finishNodeDrag}
                      onClick={() => setSelectedNodeId(node.id)}
                    >
                      <span className={styles.nodeIcon}>{node.agentId ? <Bot size={15} /> : <Users size={15} />}</span>
                      <strong>{node.label}</strong>
                      <span className={`${styles.nodeRoleBadge} ${roleBadgeTone(node, display?.tone)}`}>{functionLabel}</span>
                      <small>{node.agentCode || node.status}</small>
                    </VNativeButton>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className={styles.emptyCanvasPanel} ref={canvasFrameRef}>
              <div className={styles.emptyCanvasContent}>
                <span className={styles.emptyCanvasKicker}>{lang === "zh" ? "组织画布" : "Organization canvas"}</span>
                <strong>
                  {teamDetailQuery.isPending || teamCanvasQuery.isPending
                    ? (lang === "zh" ? "正在读取画布" : "Loading canvas")
                    : (lang === "zh" ? "暂无画布数据" : "No canvas data")}
                </strong>
                <p>
                  {lang === "zh"
                    ? "刷新团队数据后会自动恢复。"
                    : "Refresh team data to restore the canvas."}
                </p>
                <div className={styles.emptyCanvasSteps}>
                  <span>{lang === "zh" ? "团队" : "Team"}</span>
                  <span>{selectedTeam?.name ?? (lang === "zh" ? "未选择" : "Not selected")}</span>
                  <span>{teamDetailQuery.isError || teamCanvasQuery.isError ? (lang === "zh" ? "读取失败" : "Failed") : (lang === "zh" ? "等待数据" : "Waiting")}</span>
                </div>
              </div>
            </div>
          )}
        </VSurface>

        {!researchWorkflowTeamSelected || researchCanvasVisible ? (
          <PaneResizeHandle
            label={lang === "zh" ? "调整团队侧栏宽度" : "Resize team inspector"}
            valueNow={teamsInspectorWidth}
            valueMin={TEAMS_INSPECTOR_PANE.minWidth}
            valueMax={TEAMS_INSPECTOR_PANE.maxWidth}
            active={teamsDraggingPaneId === "inspector"}
            className={styles.inspectorResizeHandle}
            onPointerDown={(event) => startTeamsInspectorResize("inspector", event, { direction: -1 })}
            onKeyDown={(event) => onTeamsInspectorResizeKeyDown("inspector", event, { direction: -1 })}
          />
        ) : null}

        <aside className={inspectorClassName} data-vui-region="teams-inspector">
          {challengeCupResearchTeamSelected && !researchCanvasVisible ? null : (
          <div className={styles.inspectorHeader}>
            <strong>
              {researchWorkflowTeamSelected && !researchCanvasVisible
                ? `${lang === "zh" ? "挑战杯ai科研团队" : "Challenge Cup AI research team"} · ${researchWorkspaceViewLabel(researchWorkspaceView, lang)}`
                : researchCanvasReadOnly
                ? (lang === "zh" ? "组织画布" : "Organization canvas")
                : (lang === "zh" ? "节点绑定" : "Node binding")}
            </strong>
            {validation && !validation.valid ? <AlertTriangle size={16} /> : researchCanvasReadOnly ? <Eye size={16} /> : <Link2 size={16} />}
          </div>
          )}
          <div className={challengeCupResearchTeamSelected && !researchCanvasVisible ? styles.challengeWorkspaceBody : styles.inspectorBody}>
            {challengeCupResearchTeamSelected && !researchCanvasVisible ? (
              <nav className={styles.challengeSurfaceSwitch} aria-label={lang === "zh" ? "挑战杯平台视图" : "Challenge Cup platform view"}>
                <VTooltip content={lang === "zh" ? "三阶段流程、实验方式与 Agent 操作" : "Three stages, experiment modes, and Agent operations"}>
                  <VNativeButton
                    type="button"
                    className={challengeTeamSurface === "workspace" ? styles.challengeSurfaceSwitchActive : ""}
                    aria-current={challengeTeamSurface === "workspace" ? "page" : undefined}
                    onClick={() => setChallengeTeamSurface("workspace")}
                  >
                    <strong>{lang === "zh" ? "科研工作台" : "Research workspace"}</strong>
                  </VNativeButton>
                </VTooltip>
                <VTooltip content={lang === "zh" ? "挑战杯任务、验收门禁与交付状态" : "Challenge task, acceptance gates, and delivery"}>
                  <VNativeButton
                    type="button"
                    className={challengeTeamSurface === "progress" ? styles.challengeSurfaceSwitchActive : ""}
                    aria-current={challengeTeamSurface === "progress" ? "page" : undefined}
                    onClick={() => setChallengeTeamSurface("progress")}
                  >
                    <strong>{lang === "zh" ? "项目进展" : "Program progress"}</strong>
                  </VNativeButton>
                </VTooltip>
              </nav>
            ) : null}
            {researchWorkflowTeamSelected && !researchCanvasVisible ? (
              <>
                {renderResearchStageLauncher()}
              </>
            ) : null}
            {selectedTeam && !challengeCupResearchTeamSelected ? renderTeamMemoryIndex() : null}
            {researchCanvasReadOnly ? renderResearchCanvasReadOnlyPanel() : null}
            {showNodeBindingPanel && !selectedTeam ? (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`}>
                <div className={styles.empty}>
                  {lang === "zh"
                    ? "暂无可用团队。请确认 AI 搜索范围团队和 挑战杯ai科研团队 已初始化。"
                    : "No available team. Confirm the AI search scope team and Challenge Cup AI research team are initialized."}
                </div>
              </section>
            ) : showNodeBindingPanel && selectedNode ? (
              <section className={styles.nodeBindingSection}>
              {selectedNode.agentId ? (
                <div className={styles.nodeSourceAuthority}>
                  <div>
                    <strong>{lang === "zh" ? "Agent 身份只读投影" : "Read-only Agent identity"}</strong>
                    <span>{selectedNode.agentSourceRef?.owner || "AgentDirectory"} · {selectedNode.agentCode || selectedNode.agentName || selectedNode.agentId}</span>
                  </div>
                  <VTooltip content={lang === "zh" ? "到 AgentDirectory 源配置修改" : "Edit in the AgentDirectory source"}>
                    <Link to={teamCanvasNodeAgentSourceRoute(selectedNode)}>
                      <Link2 size={14} />
                      {lang === "zh" ? "源配置" : "Source"}
                    </Link>
                  </VTooltip>
                </div>
              ) : null}
              <label>
                <span>{lang === "zh" ? "节点名称" : "Node label"}</span>
                <VNativeInput value={nodeDraft.label} onChange={(event) => setNodeDraft((current) => ({ ...current, label: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "组织角色" : "Role"}</span>
                <VNativeInput value={nodeDraft.role} onChange={(event) => setNodeDraft((current) => ({ ...current, role: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "绑定 Agent" : "Bound Agent"}</span>
                <VNativeSelect value={nodeDraft.agentId} onChange={(event) => setNodeDraft((current) => ({ ...current, agentId: event.target.value }))}>
                  <option value="">{lang === "zh" ? "不绑定" : "Unbound"}</option>
                  {activeAgents.map((agent) => {
                    const display = agentDisplayInfo(agent, lang);
                    const membership = agentTeamMembership.get(agent.agentId);
                    const ownedByOtherTeam = Boolean(membership && membership.teamId !== selectedTeam?.teamId);
                    return (
                      <option key={agent.agentId} value={agent.agentId} disabled={ownedByOtherTeam}>
                        {display.name} · {agent.agentCode}
                        {ownedByOtherTeam
                          ? ` · ${lang === "zh" ? "已属于" : "belongs to"} ${membership?.teamName}`
                          : ""}
                      </option>
                    );
                  })}
                </VNativeSelect>
              </label>
              <label>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <VNativeTextarea value={nodeDraft.purpose} onChange={(event) => setNodeDraft((current) => ({ ...current, purpose: event.target.value }))} />
              </label>
              <div className={styles.actionRow}>
                <VNativeButton type="button" onClick={applyNodeDraft} disabled={!hasWritableCanvas || selectedTeamSaveCanvasPending}>
                  <Save size={14} />
                  {lang === "zh" ? "保存节点" : "Save node"}
                </VNativeButton>
                <VNativeButton type="button" onClick={connectFromLead} disabled={!hasWritableCanvas || !selectedNode || durableCanvas?.nodes[0]?.id === selectedNode.id}>
                  <Link2 size={14} />
                  {lang === "zh" ? "接入主干" : "Connect"}
                </VNativeButton>
                <VNativeButton type="button" onClick={unbindSelectedNode} disabled={!hasWritableCanvas || !selectedNode?.agentId || selectedTeamSaveCanvasPending}>
                  <Unlink size={14} />
                  {lang === "zh" ? "解绑节点" : "Unbind"}
                </VNativeButton>
                <VNativeButton
                  type="button"
                  className={styles.dangerButton}
                  onClick={deleteSelectedNode}
                  disabled={!hasWritableCanvas || !selectedNode || (durableCanvas?.nodes.length ?? 0) <= 1 || selectedTeamSaveCanvasPending}
                >
                  <Trash2 size={14} />
                  {lang === "zh" ? "删除节点" : "Delete"}
                </VNativeButton>
              </div>
              <div className={styles.issueList}>
                {(validation?.issues ?? []).length ? (
                  validation?.issues.map((issue) => (
                    <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={styles.issue}>
                      <strong>{issue.code}</strong>
                      <span>{issue.message}</span>
                    </div>
                  ))
                ) : (
                  <span>{lang === "zh" ? "画布校验通过" : "Canvas validation passed"}</span>
                )}
              </div>
              </section>
            ) : showNodeBindingPanel ? (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`} aria-busy={teamDetailQuery.isPending || agentSummaryQuery.isPending}>
                <div className={styles.empty}>
                  {teamDetailQuery.isPending || agentSummaryQuery.isPending
                    ? (lang === "zh" ? "正在读取团队节点..." : "Loading team nodes...")
                    : (lang === "zh" ? "创建或选择一个团队节点。" : "Create or select a team node.")}
                </div>
              </section>
            ) : null}
            {showAiSearchScopePanel ? renderAiSearchSourceScopePanel() : null}
            {showWorkflowPanel ? (
              <section className={styles.workflowPanel} id="research-workflow-overview">
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "科研流程" : "Research workflow"}</strong>
                  <span>
                    {researchWorkflowTeamSelected
                      ? teamWorkflow?.status || (teamWorkflowQuery.isPending ? (lang === "zh" ? "读取中" : "loading") : (lang === "zh" ? "待初始化" : "not initialized"))
                      : (lang === "zh" ? "非科研团队" : "not research")}
                  </span>
                </div>
                {researchWorkflowTeamSelected ? (
                  teamWorkflowQuery.isPending ? (
                    <div className={styles.empty}>{lang === "zh" ? "正在读取 TeamWorkflowOrchestration..." : "Loading TeamWorkflowOrchestration..."}</div>
                  ) : teamWorkflow ? (
                    <>
                      {showResearchOverview ? (
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
                            <span>{teamWorkflow.ownerAgentId}</span>
                            <span>{teamWorkflow.candidateStore.storagePath}</span>
                          </div>
                          <TeamWorkflowModelEvidenceStatusPanel
                            lang={lang}
                            status={teamWorkflowOfficialModelEvidenceStatus}
                            loading={teamWorkflowOfficialModelEvidenceStatusQuery.isPending}
                            errorMessages={teamWorkflowOfficialModelEvidenceStatusQuery.error instanceof Error ? [teamWorkflowOfficialModelEvidenceStatusQuery.error.message] : []}
                            statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
                          />
                        </>
                      ) : null}
                      {showResearchSourceCollection ? (
                      <TeamsSourceCollectionPanel
                        lang={lang}
                        title={lang === "zh" ? "资料搜索执行" : "Source collection"}
                        summary={sourceCollectionOverviewSummary}
                        statusLabel={sourceCollectionOverviewStatus || (lang === "zh" ? "未启动" : "not started")}
                        statusClassName={workflowIngestionTone(sourceCollectionOverviewStatus)}
                        draft={sourceCollectionDraft}
                        modeFields={renderSourceCollectionModeFields()}
                        canStart={sourceCollectionCanStart}
                        startPending={selectedTeamStartSourceCollectionPending}
                        selectedRunId={selectedSourceCollectionRunEffectiveId}
                        runs={sourceCollectionFindingRunOptions}
                        stats={sourceCollectionOverviewStats}
                        assignments={sourceCollectionFindingAssignments}
                        assignmentEmptyMessage={sourceCollectionOverviewAssignmentEmptyMessage}
                        queries={sourceCollectionFindingQueries}
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
                            onOpenStage={selectSourceCollectionStage}
                          />
                        )}
                        storageActions={renderSourceCollectionStorageActions()}
                        plan={sourceCollectionOverviewPlan}
                        manualWriteback={renderSourceCollectionManualWritebackPanel({
                          title: lang === "zh" ? "手工回写一条搜集结果" : "Manual result writeback",
                          description: lang === "zh" ? "写 DataRecord 后自动导入 source_manifest 候选" : "Writes DataRecord, then imports source_manifest candidate",
                          wrapInDetails: false,
                        })}
                        boundaryItems={sourceCollectionOverviewBoundaryItems}
                        errorMessages={sourceCollectionOverviewErrors}
                        result={sourceCollectionOverviewResult}
                        onDraftChange={(patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch }))}
                        onStart={() => {
                          if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
                            return;
                          }
                          startSourceCollectionRunMutation.mutate({
                            teamId: selectedTeam.teamId,
                            draft: sourceCollectionDraft,
                          });
                        }}
                        onRunChange={setSelectedSourceCollectionRunId}
                        onAssignmentSelect={(assignmentId) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId }))}
                      />
                      ) : null}
                      {showResearchCoordination ? (
                      <TeamWorkflowCoordinationStatusPanel
                        lang={lang}
                        status={teamWorkflowCoordinationStatus}
                        loading={teamWorkflowCoordinationStatusQuery.isPending}
                        errorMessages={teamWorkflowCoordinationStatusQuery.error instanceof Error ? [teamWorkflowCoordinationStatusQuery.error.message] : []}
                        statusLabel={(value) => workflowCoordinationStatusLabel(value, lang)}
                        channelLabel={(value) => workflowCoordinationChannelLabel(value, lang)}
                        stateLabel={(value) => workflowStateLabel(value, lang)}
                      />
                      ) : null}
                      {showResearchIngestion ? (
                      <TeamWorkflowKnowledgeIngestionStatusPanel
                        lang={lang}
                        status={teamWorkflowKnowledgeIngestionStatus}
                        loading={teamWorkflowKnowledgeIngestionStatusQuery.isPending}
                        errorMessages={teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error ? [teamWorkflowKnowledgeIngestionStatusQuery.error.message] : []}
                        statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
                      />
                      ) : null}
                      {showResearchOverview ? (
                        <>
                      <div className={styles.workflowStageList}>
                        {teamWorkflow.stateMachine.nodes.map((node) => (
                          <span
                            key={node.nodeId}
                            className={node.nodeId === teamWorkflow.stateMachine.currentStage ? styles.workflowStageActive : ""}
                          >
                            {workflowStateLabel(node.nodeId || node.label, lang)}
                          </span>
                        ))}
                      </div>
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
                        <div className={styles.empty}>{lang === "zh" ? "候选校验已延后，需要时打开校验接口。" : "Candidate validation is deferred until requested."}</div>
                      ) : teamWorkflowCandidatesQuery.isPending ? (
                        <div className={styles.empty}>{lang === "zh" ? "正在读取候选校验摘要..." : "Loading candidate validation summary..."}</div>
                      ) : null}
                        </>
                      ) : null}
                      {showResearchGraph ? (
                      <TeamWorkflowCandidateGraphStatusPanel
                        lang={lang}
                        graph={teamWorkflowCandidateGraph}
                        layout={teamWorkflowCandidateGraphLayout}
                        loading={teamWorkflowCandidateGraphQuery.isPending}
                        errorMessages={[
                          ...(teamWorkflowCandidateGraphQuery.error instanceof Error ? [teamWorkflowCandidateGraphQuery.error.message] : []),
                          ...(selectedTeamBuildCandidateGraphError ? [selectedTeamBuildCandidateGraphError.message] : []),
                        ]}
                        actionLabel={sourceCollectionGraphActionLabel}
                        actionDisabled={sourceCollectionGraphActionDisabled}
                        actionTitle={sourceCollectionActionDisabledTitle(sourceCollectionGraphActionReadiness, sourceCollectionGraphActionLabel)}
                        stateLabel={(value) => workflowStateLabel(value, lang)}
                        onAction={runSourceCollectionGraphAction}
                      />
                      ) : null}
                      {showResearchCandidates ? (
                        <>
                      <TeamWorkflowSourceQualityStatusPanel
                        lang={lang}
                        status={teamWorkflowSourceQualityStatus}
                        loading={teamWorkflowSourceQualityStatusQuery.isPending}
                        errorMessages={[
                          ...(teamWorkflowSourceQualityStatusQuery.error instanceof Error ? [teamWorkflowSourceQualityStatusQuery.error.message] : []),
                          ...(selectedTeamSourceQualityError ? [selectedTeamSourceQualityError.message] : []),
                        ]}
                        statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
                      />
                      <TeamWorkflowPaperNoteChunkStatusPanel
                        lang={lang}
                        status={teamWorkflowPaperNoteChunkStatus}
                        loading={teamWorkflowPaperNoteChunkStatusQuery.isPending}
                        errorMessages={[
                          ...(teamWorkflowPaperNoteChunkStatusQuery.error instanceof Error ? [teamWorkflowPaperNoteChunkStatusQuery.error.message] : []),
                          ...(selectedTeamPlanPaperNoteChunksError ? [selectedTeamPlanPaperNoteChunksError.message] : []),
                        ]}
                        statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
                      />
                      <TeamWorkflowCandidatePreviewPanel
                        lang={lang}
                        items={teamWorkflowCandidatePreviewItems}
                        canOpenLibrary={Boolean(selectedTeam?.teamId)}
                        reviewDisabled={sourceCollectionScreeningDisabled}
                        reviewTitle={sourceCollectionActionDisabledTitle(sourceCollectionScreeningActionReadiness, lang === "zh" ? "进入资料提炼复核" : "Open review")}
                        listNeedsScrollHint={teamWorkflowCandidates.length > SOURCE_COLLECTION_RESULT_PAGE_SIZE}
                        emptyMessage={lang === "zh" ? "候选仓库还没有资料、笔记或机制候选。" : "No sources, notes, or mechanism candidates yet."}
                        onOpenLibrary={openSourceCollectionCandidatePanel}
                        onOpenReview={openSourceCollectionScreeningPanel}
                      />
                        </>
                      ) : null}
                    </>
                  ) : (
                    <div className={styles.empty}>{lang === "zh" ? "科研流程尚未初始化。" : "Research workflow is not initialized yet."}</div>
                  )
                ) : (
                  <div className={styles.empty}>
                    {lang === "zh" ? "选择 research-team / 挑战杯ai科研团队 后显示挑战杯科研流程。" : "Select research-team to view the Challenge Cup workflow."}
                  </div>
                )}
                {teamWorkflowQuery.error instanceof Error ? (
                  <div className={styles.messageError}>{teamWorkflowQuery.error.message}</div>
                ) : null}
                {teamWorkflowCandidatesQuery.error instanceof Error ? (
                  <div className={styles.messageError}>{teamWorkflowCandidatesQuery.error.message}</div>
                ) : null}
              </section>
            ) : null}
            {showTeamCommunicationPanel ? (
              <div className={styles.researchDiscussionPanel} id="research-workflow-discussion">
              <form
                className={styles.teamTaskForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedTeam?.teamId || !linkedChatRoomId || !teamTaskTopic.trim() || linkedRoomBusy) {
                    return;
                  }
                  startTeamRoundMutation.mutate({
                    roomId: linkedChatRoomId,
                    teamId: selectedTeam.teamId,
                    topic: teamTaskTopic.trim(),
                    mode: linkedRoomDetail?.mode || selectedTeam.linkedChatRoom?.mode || "round_robin",
                    purpose: linkedRoomDetail?.purpose || selectedTeam.linkedChatRoom?.purpose || "discussion",
                  });
                }}
              >
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "团队任务" : "Team task"}</strong>
                  <span>
                    {selectedTeam?.linkedChatRoomId
                      ? linkedRoomBusy
                        ? (lang === "zh" ? "群聊运行中" : "room running")
                        : (lang === "zh" ? "发送到群聊 round" : "starts a room round")
                      : (lang === "zh" ? "需要先同步群聊" : "sync room first")}
                  </span>
                </div>
                <VNativeTextarea
                  value={teamTaskTopic}
                  onChange={(event) => setTeamTaskTopic(event.target.value)}
                  placeholder={lang === "zh" ? "输入团队要协作处理的议题或任务" : "Enter a topic or task for this team"}
                />
                <VNativeButton
                  type="submit"
                  disabled={!canStartTeamRound || selectedTeamStartRoundPending}
                >
                  <Play size={14} />
                  {selectedTeamStartRoundPending
                    ? (lang === "zh" ? "启动中" : "Starting")
                    : (lang === "zh" ? "启动团队讨论" : "Start team round")}
                </VNativeButton>
                {selectedTeamStartRoundResult ? (
                  <div className={styles.messageResult}>
                    <strong>{selectedTeamStartRoundResult.rounds.length}</strong>
                    <span>{lang === "zh" ? "轮讨论已写入关联群聊" : "rounds now recorded in the linked room"}</span>
                    <Link to={teamChatRoomRoute(selectedTeamStartRoundResult.roomId, teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID), lang === "zh" ? "返回团队页面" : "Back to team")}>
                      {lang === "zh" ? "打开群聊" : "Open room"}
                    </Link>
                  </div>
                ) : null}
                {selectedTeamStartRoundError ? (
                  <div className={styles.messageError}>{selectedTeamStartRoundError.message}</div>
                ) : null}
                <section className={styles.teamRoundPanel}>
                  <div className={styles.sectionTitle}>
                    <strong>{lang === "zh" ? "最近团队任务" : "Latest team task"}</strong>
                    <span>{linkedRoomDetail ? chatRoomStatusLabel(linkedRoomDetail.status, lang) : (lang === "zh" ? "未读取" : "not loaded")}</span>
                  </div>
                  {linkedChatRoomQuery.isPending && linkedChatRoomId ? (
                    <div className={styles.empty}>{lang === "zh" ? "正在读取关联群聊..." : "Loading linked room..."}</div>
                  ) : latestTeamRound ? (
                    <article className={styles.teamRoundCard}>
                      <div className={styles.teamRoundHeader}>
                        <strong>{latestTeamRound.topic || (lang === "zh" ? "未命名任务" : "Untitled task")}</strong>
                        <span>{latestTeamRound.status}</span>
                      </div>
                      <p>{latestTeamRound.summary || (lang === "zh" ? "任务仍在等待成员输出。" : "Waiting for participant output.")}</p>
                      <div className={styles.teamRoundMeta}>
                        <span>{latestTeamRound.messages.length} messages</span>
                        <span>{latestTeamRound.mode}</span>
                        <span>{formatTime(latestTeamRound.updatedAt || latestTeamRound.startedAt, lang)}</span>
                      </div>
                      <Link to={teamChatRoomRoute(latestTeamRound.roomId, teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID), lang === "zh" ? "返回团队页面" : "Back to team")}>
                        {lang === "zh" ? "查看完整群聊" : "View full room"}
                      </Link>
                    </article>
                  ) : (
                    <div className={styles.empty}>
                      {linkedChatRoomId
                        ? (lang === "zh" ? "关联群聊还没有团队任务记录。" : "No team task rounds in the linked room yet.")
                        : (lang === "zh" ? "同步群聊后可查看团队任务状态。" : "Sync a room to view team task status.")}
                    </div>
                  )}
                  {linkedChatRoomQuery.error instanceof Error ? (
                    <div className={styles.messageError}>{linkedChatRoomQuery.error.message}</div>
                  ) : null}
                </section>
              </form>
              <form
                className={styles.teamMessageForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedTeam?.teamId || !teamMessage.trim()) {
                    return;
                  }
                  sendTeamMessageMutation.mutate({
                    teamId: selectedTeam.teamId,
                    content: teamMessage.trim(),
                    interruptMode: teamInterrupt ? "interrupt_targets" : "none",
                  });
                }}
              >
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "团队广播" : "Team broadcast"}</strong>
                  <span>{activeTeamMemberCount} active agents</span>
                </div>
                <VNativeTextarea
                  value={teamMessage}
                  onChange={(event) => setTeamMessage(event.target.value)}
                  placeholder={lang === "zh" ? "发送给当前团队 active 成员" : "Send to active members of this team"}
                />
                <label className={styles.inlineToggle}>
                  <VNativeInput type="checkbox" checked={teamInterrupt} onChange={(event) => setTeamInterrupt(event.target.checked)} />
                  <span>{lang === "zh" ? "打断正在直聊中的目标 Agent" : "Interrupt targeted running direct sessions"}</span>
                </label>
                <VNativeButton
                  type="submit"
                  disabled={!selectedTeam || !teamMessage.trim() || activeTeamMemberCount === 0 || selectedTeamMessagePending}
                >
                  <Send size={14} />
                  {lang === "zh" ? "发送给团队" : "Send to team"}
                </VNativeButton>
                {selectedTeamMessageResult ? (
                  <div className={styles.messageResult}>
                    <strong>{selectedTeamMessageResult.deliveries.length}</strong>
                    <span>{lang === "zh" ? "条投递已进入项目总群" : "deliveries recorded in project bus"}</span>
                    {selectedTeamMessageResult.kernel?.taskId ? (
                      <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(selectedTeamMessageResult.kernel.taskId)}>
                        {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
                      </Link>
                    ) : null}
                  </div>
                ) : null}
                {selectedTeamMessageError ? (
                  <div className={styles.messageError}>{selectedTeamMessageError.message}</div>
                ) : null}
              </form>
              <section className={styles.teamHistoryPanel}>
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "最近团队广播" : "Recent team broadcasts"}</strong>
                  <span>{teamBusEvents.length} events</span>
                </div>
                {projectBusQuery.isPending ? (
                  <div className={styles.empty}>{lang === "zh" ? "正在读取项目总群..." : "Loading project bus..."}</div>
                ) : teamBusEvents.length ? (
                  <div className={styles.teamHistoryList}>
                    {teamBusEvents.map((event) => {
                      const revoked = isProjectAgentBusEventRevoked(event);
                      const revokePending =
                        revokeTeamMessageMutation.isPending
                        && revokeTeamMessageMutation.variables?.eventId === event.eventId;
                      return (
                        <article key={event.eventId} className={revoked ? `${styles.teamHistoryItem} ${styles.teamHistoryItemRevoked}` : styles.teamHistoryItem}>
                          <div className={styles.teamHistoryHeader}>
                            <strong>{event.summary || event.content}</strong>
                            <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                          </div>
                          <p>{revoked ? (lang === "zh" ? "这条团队广播已撤回，目标 Agent 已请求停止。" : "This team broadcast was revoked and target agents were asked to stop.") : event.content}</p>
                          <div className={styles.teamHistoryMeta}>
                            <span>{formatTime(event.createdAt, lang)}</span>
                            <span>{event.deliveries.length} deliveries</span>
                            <span>{event.interruptions.length} interrupts</span>
                            {event.kernel?.taskId ? (
                              <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(event.kernel.taskId)}>
                                {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
                              </Link>
                            ) : null}
                          </div>
                          <div className={styles.deliveryList}>
                            {event.deliveries.map((delivery) => (
                              <span key={`${event.eventId}-${delivery.targetAgentId}-${delivery.inboxMessageId}`}>
                                {delivery.targetAgentCode || delivery.targetAgentName || delivery.targetAgentId}: {delivery.revoked ? "revoked" : delivery.wake?.wakeStatus || delivery.status}
                              </span>
                            ))}
                          </div>
                          {event.createdBy === "user" && !revoked ? (
                            <VNativeButton
                              type="button"
                              className={styles.revokeButton}
                              disabled={revokePending}
                              onClick={() => selectedTeam?.teamId && revokeTeamMessageMutation.mutate({ teamId: selectedTeam.teamId, eventId: event.eventId })}
                            >
                              {revokePending ? (lang === "zh" ? "撤回中" : "Revoking") : (lang === "zh" ? "撤回" : "Revoke")}
                            </VNativeButton>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className={styles.empty}>{lang === "zh" ? "当前团队还没有广播记录。" : "No team broadcasts yet."}</div>
                )}
                {revokeTeamMessageMutation.error instanceof Error ? (
                  <div className={styles.messageError}>{revokeTeamMessageMutation.error.message}</div>
                ) : null}
              </section>
              </div>
            ) : null}
            </div>
        </aside>
      </div>
      )}
    </VDenseOpsPage>
  );
}
