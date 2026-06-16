import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, ArrowLeft, Bot, CheckCircle2, Eye, Link2, Play, Plus, RefreshCw, Save, Search, Send, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
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
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AiSearchRun,
  AiSearchRunListPayload,
  AiSearchRunSummary,
  ChatRoomDetail,
  DataProcessingCollectionAssignmentListPayload,
  DataProcessingCollectionOutputPayload,
  DataProcessingRunListPayload,
  DataProcessingStatus,
  Team,
  TeamCanvasNode,
  TeamListPayload,
  TeamOrganizationCanvas,
  TeamWorkflowCandidate,
  TeamWorkflowCandidateGraphBuildPayload,
  TeamWorkflowCandidateGraphPayload,
  TeamWorkflowCandidateGraphNode,
  TeamWorkflowCoordinationStatus,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowSourceCollectionPromptCachePolicy,
  TeamWorkflowSourceCollectionPromptCachePolicyRef,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
  TeamWorkflowCandidateListPayload,
  TeamWorkflowOrchestration,
} from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { agentDisplayInfo } from "./agentDisplay";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import styles from "./TeamsRoute.module.css";

const NODE_WIDTH = 172;
const NODE_HEIGHT = 92;
const CANVAS_VIEWPORT_WIDTH = 1180;
const CANVAS_VIEWPORT_HEIGHT = 760;
const TEAM_ORGANIZATION_CANVAS_KIND = "team_organization_canvas";
const RESEARCH_TEAM_ID = "research-team";
const AI_SEARCH_TEAM_ID = "ai-search-team";
const TEAM_PICKER_TEAM_IDS = [AI_SEARCH_TEAM_ID, RESEARCH_TEAM_ID] as const;
const EVOLUTION_SYSTEM_TEAM_IDS = new Set(["self-evolution-team", "supervised-evolution-team"]);
const LINKED_ROOM_ACTIVE_REFETCH_MS = 5_000;
const LINKED_ROOM_IDLE_REFETCH_MS = 30_000;
const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 8;
const TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT = 20;
const AI_SEARCH_RUN_PREVIEW_LIMIT = 6;
const WORKFLOW_GRAPH_WIDTH = 620;
const WORKFLOW_GRAPH_MIN_HEIGHT = 170;
const WORKFLOW_GRAPH_NODE_WIDTH = 124;
const WORKFLOW_GRAPH_NODE_HEIGHT = 42;
const WORKFLOW_GRAPH_NODE_GAP = 18;
const WORKFLOW_GRAPH_MARGIN_X = 22;
const WORKFLOW_GRAPH_MARGIN_Y = 28;
const SOURCE_COLLECTION_RUN_PREVIEW_LIMIT = 20;
const SOURCE_COLLECTION_DEFAULT_ROLES = ["data_discovery", "source_acquisition", "content_extraction", "source_quality"];
const SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES = new Set(["data_discovery", "source_acquisition"]);
const SOURCE_COLLECTION_PROMPT_CACHE_POLICY = {
  requirement: "required_for_llm_execution",
};
const SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL = "configured prompt-cache model";

const researchStageRoundStatusQueryKey = (id: string) => ["teams", id, "workflow-orchestration", "stage-rounds", "status"] as const;
const officialModelEvidenceStatusQueryKey = (id: string) => ["teams", id, "workflow-orchestration", "official-model-evidence", "status"] as const;
const paperNoteChunkStatusQueryKey = (id: string) => ["teams", id, "workflow-orchestration", "paper-note-chunks", "status"] as const;
const sourceQualityStatusQueryKey = (id: string) => ["teams", id, "workflow-orchestration", "source-quality", "status"] as const;

type ResearchStageWorkspaceView = "knowledge_collection" | "experiment" | "iteration";
type ResearchLegacyWorkspaceView = "source_collection" | "coordination" | "ingestion" | "graph" | "candidates" | "discussion" | "canvas";
type ResearchWorkspaceView = "overview" | ResearchStageWorkspaceView | ResearchLegacyWorkspaceView;

type TeamsRouteProps = {
  forcedTeamId?: string;
  forcedResearchWorkspaceView?: ResearchWorkspaceView;
  sourceCollectionStandalone?: boolean;
};

const RESEARCH_WORKSPACE_NAV_ITEMS: Array<{
  view: ResearchStageWorkspaceView;
  zh: string;
  en: string;
  zhDetail: string;
  enDetail: string;
  zhModules: string;
  enModules: string;
}> = [
  {
    view: "knowledge_collection",
    zh: "知识搜集",
    en: "Knowledge collection",
    zhDetail: "搜集、筛选、候选与入库边界",
    enDetail: "Collection, screening, candidates, and boundary",
    zhModules: "资料搜集 / 资料筛选 / 知识入库 / 候选图谱",
    enModules: "Source collection / screening / ingestion / graph",
  },
  {
    view: "experiment",
    zh: "实验",
    en: "Experiment",
    zhDetail: "规划、执行、指标与结果对比",
    enDetail: "Planning, execution, metrics, and comparison",
    zhModules: "实验规划 / Baseline / 指标 / 结果记录",
    enModules: "Experiment plan / baseline / metrics / results",
  },
  {
    view: "iteration",
    zh: "迭代",
    en: "Iteration",
    zhDetail: "复盘、版本、优化与交付",
    enDetail: "Review, versions, optimization, and delivery",
    zhModules: "复盘 / 版本化 / 改进计划 / 交付门禁",
    enModules: "Review / versioning / improvements / delivery gate",
  },
];

const RESEARCH_WORKSPACE_LABELS: Record<ResearchWorkspaceView, { zh: string; en: string }> = {
  overview: { zh: "科研总览", en: "Overview" },
  knowledge_collection: { zh: "知识搜集", en: "Knowledge collection" },
  experiment: { zh: "实验", en: "Experiment" },
  iteration: { zh: "迭代", en: "Iteration" },
  source_collection: { zh: "资料搜集", en: "Source collection" },
  coordination: { zh: "团队协调", en: "Coordination" },
  ingestion: { zh: "知识入库", en: "Ingestion" },
  graph: { zh: "候选图谱", en: "Candidate graph" },
  candidates: { zh: "候选资料", en: "Candidates" },
  discussion: { zh: "团队沟通", en: "Team discussion" },
  canvas: { zh: "组织画布", en: "Canvas" },
};

function researchWorkspaceAnchorId(view: ResearchWorkspaceView) {
  const ids: Record<ResearchWorkspaceView, string> = {
    overview: "research-workflow-overview",
    knowledge_collection: "research-workflow-knowledge-collection",
    experiment: "research-workflow-experiment",
    iteration: "research-workflow-iteration",
    source_collection: "research-workflow-source-collection",
    coordination: "research-workflow-coordination",
    ingestion: "research-workflow-ingestion",
    graph: "research-workflow-graph",
    candidates: "research-workflow-candidates",
    discussion: "research-workflow-discussion",
    canvas: "research-organization-canvas",
  };
  return ids[view];
}

function researchWorkspaceViewLabel(view: ResearchWorkspaceView, lang: "zh" | "en") {
  const item = RESEARCH_WORKSPACE_LABELS[view];
  return item ? item[lang] : view;
}

function parseResearchWorkspaceView(value: string | null): ResearchWorkspaceView | null {
  if (!value) {
    return null;
  }
  if (value === "source_collection") {
    return "knowledge_collection";
  }
  return value in RESEARCH_WORKSPACE_LABELS ? (value as ResearchWorkspaceView) : null;
}

function researchWorkspaceStageRoute(teamId = RESEARCH_TEAM_ID, view: ResearchStageWorkspaceView = "knowledge_collection") {
  return `/teams?team=${encodeURIComponent(teamId)}&researchView=${encodeURIComponent(view)}`;
}

function researchSourceCollectionRoute(teamId = RESEARCH_TEAM_ID) {
  return researchWorkspaceStageRoute(teamId, "knowledge_collection");
}

function teamWorkspaceRoute(teamId = RESEARCH_TEAM_ID) {
  return `/teams?team=${encodeURIComponent(teamId)}`;
}

type NodeDraft = {
  label: string;
  role: string;
  purpose: string;
  agentId: string;
};

type SourceCollectionDraft = {
  title: string;
  topic: string;
  goal: string;
  querySeeds: string;
  inputRefs: string;
  searchLanguages: string;
  sourceTypes: string;
  maxResultsPerQuery: number;
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

type SourceCollectionTraceMessage = {
  id: string;
  agentRole: string;
  title: string;
  body: string;
  status: string;
  tone: "plan" | "cache" | "search" | "acquire" | "extract" | "quality" | "storage" | "blocked";
  refs: string[];
  storageRefs: string[];
};

type SourceCollectionStepState = "active" | "done" | "failed" | "idle" | "pending";
type SourceCollectionStageModuleId = "collection" | "screening" | "candidate" | "graph" | "memory";

type SourceCollectionCandidateWithSource = TeamWorkflowCandidate & {
  sourcePath?: string;
  sourceRef?: string;
  sourceUrl?: string;
};

type SourceCollectionCandidateProvenance = {
  kind: "doi" | "file" | "missing" | "ref" | "url";
  label: string;
  value: string;
  href: string;
};

type SourceCollectionCandidateTrace = {
  assignmentId: string;
  query: string;
  queryId: string;
  rawLocation: string;
  recordId: string;
  runId: string;
  searchProvider: string;
  searchUrl: string;
  sourceRef: string;
};

type SourceCollectionStageModule = {
  id: SourceCollectionStageModuleId;
  label: string;
  metric: string;
  summary: string;
  state: SourceCollectionStepState;
  status: string;
  detailLabel: string;
  actionLabel: string;
  actionDisabled: boolean;
  actionTone: "primary" | "secondary";
  actionIcon: "play" | "search" | "check" | "archive" | "refresh";
  onAction: () => void;
  onDetail: () => void;
};

const SOURCE_COLLECTION_STAGE_AGENT_KEYS: Record<SourceCollectionStageModuleId, string[]> = {
  collection: ["data_discovery", "source_acquisition", "content_extraction"],
  screening: ["source_quality"],
  candidate: ["source_quality"],
  graph: ["source_quality"],
  memory: ["knowledge_steward"],
};

function parseSourceCollectionStageModuleId(value: string | null): SourceCollectionStageModuleId | null {
  return value === "collection" || value === "screening" || value === "candidate" || value === "graph" || value === "memory"
    ? value
    : null;
}

type SourceCollectionStorageOpenTarget =
  | "run_directory"
  | "artifacts_directory"
  | "search_plan"
  | "search_events"
  | "records"
  | "candidates"
  | "candidate_store"
  | "data_processing_run"
  | "data_processing_records";

type SourceCollectionStorageArtifacts = {
  runDirectory: string;
  artifactsDirectory: string;
  searchPlanPath: string;
  searchEventsPath: string;
  recordsPath: string;
  candidatesPath: string;
  candidateStorePath: string;
  dataProcessingRunPath: string;
  dataProcessingRecordsPath: string;
};

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
  outputCount: number;
  importedCount: number;
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

type ResearchStageType = "knowledge_collection" | "experiment" | "iteration";

type ResearchStageAgentRoleDefinition = {
  key: string;
  roleKeys: string[];
  zh: string;
  en: string;
  zhFocus: string;
  enFocus: string;
  fallbackAgentId?: string;
};

const RESEARCH_STAGE_AGENT_ROLES: Record<ResearchStageType, ResearchStageAgentRoleDefinition[]> = {
  knowledge_collection: [
    {
      key: "research_coordination",
      roleKeys: ["research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator"],
      zh: "科研协调",
      en: "Research coordination",
      zhFocus: "阶段调度与分工",
      enFocus: "Stage coordination",
    },
    {
      key: "data_discovery",
      roleKeys: ["data_discovery"],
      zh: "资料发现",
      en: "Data discovery",
      zhFocus: "搜索问题与来源范围",
      enFocus: "Queries and scope",
    },
    {
      key: "source_acquisition",
      roleKeys: ["source_acquisition"],
      zh: "来源获取",
      en: "Source acquisition",
      zhFocus: "网页、论文和数据集元信息",
      enFocus: "Source metadata",
    },
    {
      key: "content_extraction",
      roleKeys: ["content_extraction"],
      zh: "内容提炼",
      en: "Content extraction",
      zhFocus: "摘要、页码与证据片段",
      enFocus: "Summary and anchors",
    },
    {
      key: "source_quality",
      roleKeys: ["source_quality"],
      zh: "资料质量评估",
      en: "Source quality",
      zhFocus: "筛选、复审与退回",
      enFocus: "Screen and review",
    },
    {
      key: "knowledge_steward",
      roleKeys: ["knowledge_steward", "steward", "ingestion_approval"],
      zh: "共享记忆前审",
      en: "Memory steward",
      zhFocus: "入共享记忆前门禁",
      enFocus: "Shared memory gate",
      fallbackAgentId: "agent-knowledge-steward",
    },
  ],
  experiment: [
    {
      key: "paper_note_extraction",
      roleKeys: ["paper_note_extraction", "paper_note", "source_extraction"],
      zh: "论文笔记",
      en: "Paper notes",
      zhFocus: "把资料转成可引用笔记",
      enFocus: "Citable notes",
    },
    {
      key: "neuro_mechanism",
      roleKeys: ["neuro_mechanism", "neuro_mechanism_extraction"],
      zh: "神经机制提取",
      en: "Neuro mechanism",
      zhFocus: "机制、证据和不确定性",
      enFocus: "Mechanism evidence",
    },
    {
      key: "mechanism_mapping",
      roleKeys: ["mechanism_mapping"],
      zh: "机制映射",
      en: "Mechanism mapping",
      zhFocus: "机制到计算抽象",
      enFocus: "Mechanism to computation",
    },
    {
      key: "algorithm_hypothesis",
      roleKeys: ["algorithm_hypothesis", "algorithm_hypothesis_draft"],
      zh: "算法假设",
      en: "Algorithm hypothesis",
      zhFocus: "baseline、指标与实验计划",
      enFocus: "Baseline and plan",
    },
    {
      key: "evidence_review",
      roleKeys: ["evidence_review", "review", "quality_review"],
      zh: "证据审查",
      en: "Evidence review",
      zhFocus: "可测性、风险和返工",
      enFocus: "Risk and rework",
    },
  ],
  iteration: [
    {
      key: "research_coordination",
      roleKeys: ["research_coordination", "ceo", "organization_coordinator"],
      zh: "科研协调",
      en: "Research coordination",
      zhFocus: "复盘调度与下一轮任务",
      enFocus: "Review coordination",
    },
    {
      key: "iteration_versioning",
      roleKeys: ["iteration_versioning", "versioning", "iteration"],
      zh: "迭代版本化",
      en: "Iteration versioning",
      zhFocus: "版本、参数和变更边界",
      enFocus: "Version boundaries",
    },
    {
      key: "evidence_review",
      roleKeys: ["evidence_review", "review", "quality_review"],
      zh: "结果审查",
      en: "Result review",
      zhFocus: "实验结论和保留假设",
      enFocus: "Results and hypotheses",
    },
    {
      key: "challenge_cup_delivery",
      roleKeys: ["challenge_cup_delivery", "delivery", "submission"],
      zh: "挑战杯交付",
      en: "Challenge Cup delivery",
      zhFocus: "材料、复现和交付门禁",
      enFocus: "Delivery gate",
    },
    {
      key: "knowledge_steward",
      roleKeys: ["knowledge_steward", "steward", "ingestion_approval"],
      zh: "知识治理",
      en: "Knowledge steward",
      zhFocus: "正式入库建议与审核边界",
      enFocus: "Knowledge governance",
      fallbackAgentId: "agent-knowledge-steward",
    },
  ],
};

type ResearchStageRound = {
  stageRoundId: string;
  stageType: ResearchStageType;
  roundNumber: number;
  status: string;
  topic: string;
  goal: string;
  sourceRunIds?: string[];
  querySeeds?: string[];
  promptCachePolicy?: TeamWorkflowSourceCollectionRunStartPayload["promptCachePolicy"];
  teamMemoryRecordId?: string;
  coordinationContract?: {
    linkedChatRoomId?: string;
    autoStarted?: boolean;
    expectedAction?: string;
  };
  warnings?: Array<{ code?: string; severity?: string; message?: string }>;
};

type ResearchStagePhaseStatus = {
  stageType: ResearchStageType;
  label: string;
  status: string;
  roundCount: number;
  activeRoundId: string;
  latestRound?: ResearchStageRound | null;
  primaryAction: string;
  secondaryAction: string;
  canStart: boolean;
  canContinue: boolean;
  canNewRound: boolean;
  requiresUserDecision: boolean;
  readiness?: {
    ready?: boolean;
    reason?: string;
  };
};

type ResearchStageRoundStatusPayload = {
  schemaVersion: number;
  teamId: string;
  status: string;
  currentStage: string;
  phases: ResearchStagePhaseStatus[];
  activeRounds: ResearchStageRound[];
  latestRound?: ResearchStageRound | null;
  roundCount: number;
  boundaries: {
    externalSearchTriggered: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    autoTransitionsNextStage: boolean;
    stageRecordsOnly: boolean;
  };
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

type TeamWorkflowOfficialModelEvidenceCoverage = {
  taskType: string;
  workflowNode: string;
  label: string;
  status: "covered" | "missing" | string;
  evidenceCount: number;
  providers: Record<string, number>;
  latestEvidenceId: string;
};

type TeamWorkflowOfficialModelEvidenceStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_evidence" | "ready" | string;
  summary: {
    evidenceCount: number;
    storedEvidenceCount: number;
    candidateOutputEvidenceCount: number;
    requiredNodeCount: number;
    coveredNodeCount: number;
    missingNodeCount: number;
    qwenEvidenceCount: number;
    bailianEvidenceCount: number;
    localEvidenceCount: number;
    linkedCandidateCount: number;
    linkedStageRoundCount: number;
    actionItemCount: number;
  };
  coverage: TeamWorkflowOfficialModelEvidenceCoverage[];
  providerCounts: Record<string, number>;
  evidenceKindCounts: Record<string, number>;
  recentEvidence: Array<{
    evidenceId: string;
    taskType: string;
    workflowNode: string;
    candidateId: string;
    modelProvider: string;
    modelId: string;
    evidenceKind: string;
    status: string;
    createdAt: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    workflowNode: string;
    taskType: string;
  }>;
  officialBoundary: {
    candidateOnly: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    requiresStewardApproval: boolean;
    boundary: string;
  };
  storage: {
    workflowPath: string;
    candidateStorePath: string;
    evidenceStorePath: string;
  };
  updatedAt: string;
};

type TeamWorkflowPaperNoteChunkStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_plan" | "in_progress" | "ready" | string;
  summary: {
    sourceCandidateCount: number;
    readySourceCandidateCount: number;
    plannedSourceCandidateCount: number;
    missingPlanSourceCandidateCount: number;
    planCount: number;
    chunkCount: number;
    draftedChunkCount: number;
    needsRevisionChunkCount: number;
    openChunkCount: number;
    actionItemCount: number;
  };
  plans: Array<{
    planId: string;
    status: string;
    sourceCandidateId: string;
    sourceTitle: string;
    chunkCount: number;
    draftedChunkCount: number;
    needsRevisionChunkCount: number;
    openChunkCount: number;
    pageScope: string;
    chunks: Array<{
      chunkId: string;
      chunkIndex: number;
      status: string;
      pageScope: string;
      excerptChars: number;
      paperNoteCandidateId: string;
      taskId: string;
    }>;
    createdAt: string;
    updatedAt: string;
  }>;
  missingPlanSources: Array<{
    candidateId: string;
    title: string;
    pageScope: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    candidateId: string;
  }>;
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  storage: {
    candidateStorePath: string;
  };
  updatedAt: string;
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

type TeamWorkflowSourceQualityStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_screening" | "in_progress" | "ready" | "blocked" | string;
  summary: {
    sourceCandidateCount: number;
    assessedSourceCandidateCount: number;
    approvedSourceCandidateCount: number;
    needsRevisionSourceCandidateCount: number;
    rejectedSourceCandidateCount: number;
    unassessedSourceCandidateCount: number;
    extractionReadySourceCandidateCount: number;
    actionItemCount: number;
  };
  candidates: Array<{
    candidateId: string;
    title: string;
    sourceKind: string;
    currentState: string;
    qualityStatus: string;
    bucket: string;
    decision: string;
    overallScore: number;
    scores: {
      relevance: number;
      reliability: number;
      accessibility: number;
      extractionReadiness: number;
    };
    hasReadyExtraction: boolean;
    requiredFixes: string[];
    riskFlags: string[];
    updatedAt: string;
    assessedAt: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    candidateId: string;
  }>;
  screeningContract: {
    agentRole: string;
    targetCandidateType: string;
    decisions: string[];
    writesCandidateStore: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  storage: {
    candidateStorePath: string;
  };
  updatedAt: string;
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

type CanvasViewportStyle = CSSProperties & {
  "--canvas-offset-x": string;
  "--canvas-offset-y": string;
  "--canvas-scale": string;
};

type NodePositionStyle = CSSProperties & {
  "--node-x": string;
  "--node-y": string;
};

type WorkflowGraphFrameStyle = CSSProperties & {
  "--workflow-graph-height": string;
};

type WorkflowGraphNodeStyle = CSSProperties & {
  "--workflow-graph-node-x": string;
  "--workflow-graph-node-y": string;
};

type WorkflowGraphNodeView = TeamWorkflowCandidateGraphNode & {
  x: number;
  y: number;
};

type WorkflowGraphLayout = {
  nodes: WorkflowGraphNodeView[];
  edges: TeamWorkflowCandidateGraphPayload["edges"];
  height: number;
};

type CanvasFrameSize = {
  width: number;
  height: number;
};

function formatTime(value: string, lang: "zh" | "en") {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) {
    return value || "-";
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function splitDraftList(value: string, limit = 12) {
  return value
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, limit);
}

function compactSourceCollectionQuerySeeds(topic: string, querySeeds: string) {
  const seeds = splitDraftList(querySeeds, 12);
  const normalizedTopic = topic.trim();
  if (normalizedTopic && !seeds.some((item) => item.toLowerCase() === normalizedTopic.toLowerCase())) {
    seeds.push(normalizedTopic);
  }
  return seeds.slice(0, 12);
}

function sourceCollectionRunsForTeam(payload: DataProcessingRunListPayload | undefined, teamId: string) {
  return (payload?.runs ?? []).filter(
    (run) =>
      run.metadata?.startedFrom === "team_workflow_source_collection"
      && run.metadata?.teamId === teamId,
  );
}

function sourceCollectionRunLabel(runId: string) {
  return runId ? `${runId.slice(0, 10)}...` : "-";
}

function translateResearchPhrase(value: string | undefined | null, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text || lang !== "zh") {
    return text;
  }
  const normalized = text.toLowerCase();
  const zh: Record<string, string> = {
    "neural algorithm source batch": "神经算法资料搜集批次",
    "neural predictive coding": "神经预测编码",
    "predictive coding cortical hierarchy": "预测编码皮层层级",
    "synaptic plasticity learning rule": "突触可塑性学习规则",
    "neural gating attention mechanism": "神经门控注意机制",
    "collect traceable neuroscience sources that can support neural-network algorithm hypotheses.": "搜集可追踪的神经科学资料，用来支撑神经网络算法假设。",
  };
  return zh[normalized] ?? text;
}

function sourceCollectionRunTitleLabel(title: string | undefined | null, lang: "zh" | "en") {
  return translateResearchPhrase(title, lang) || (lang === "zh" ? "资料搜集批次" : "Source collection run");
}

function sourceCollectionStatusLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    active: "进行中",
    blocked: "阻塞",
    collecting: "待继续搜集",
    completed: "已完成",
    failed: "失败",
    in_progress: "推进中",
    needs_attention: "需处理",
    open: "待执行",
    pending: "待启动",
    pending_screening: "待筛选",
    planned: "已计划",
    processing: "已搜索待筛选",
    reviewing: "待筛选",
    ready: "已就绪",
    ready_for_screening: "可筛选",
    returned: "已退回",
    satisfied: "已通过",
    waiting_for_writeback: "待回写",
  };
  const en: Record<string, string> = {
    active: "active",
    blocked: "blocked",
    collecting: "ready to continue",
    completed: "completed",
    failed: "failed",
    in_progress: "in progress",
    needs_attention: "needs attention",
    open: "open",
    pending: "pending",
    pending_screening: "pending screening",
    planned: "planned",
    processing: "ready for screening",
    reviewing: "ready for screening",
    ready: "ready",
    ready_for_screening: "ready for screening",
    returned: "returned",
    satisfied: "satisfied",
    waiting_for_writeback: "waiting for writeback",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? workflowIngestionStatusLabel(normalized, lang);
}

function sourceCollectionAgentRoleLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  if (!normalized || lang !== "zh") {
    return normalized || "-";
  }
  const zh: Record<string, string> = {
    "Research Coordination Agent": "科研协调 Agent",
    "Data Discovery Agent": "资料发现 Agent",
    "Source Collection Agent": "资料搜集 Agent",
    "Source Intake Agent": "资料入候选 Agent",
    "Source Quality Assessment Agent": "资料质量评估 Agent",
    data_discovery: "资料发现 Agent",
    source_acquisition: "来源获取 Agent",
    content_extraction: "内容提炼 Agent",
    source_quality: "资料质量评估 Agent",
  };
  return zh[normalized] ?? normalized;
}

function sourceCollectionSourceTypeLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    dataset: "数据集",
    file: "本地文件",
    manual: "手工记录",
    note: "笔记",
    paper: "论文",
    review: "综述",
    url: "网页",
  };
  const en: Record<string, string> = {
    dataset: "dataset",
    file: "file",
    manual: "manual",
    note: "note",
    paper: "paper",
    review: "review",
    url: "url",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (value || "-");
}

function metadataString(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" ? value.trim() : "";
}

function normalizedDoi(value: string | undefined | null) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const doiUrl = text.match(/^https?:\/\/(?:dx\.)?doi\.org\/(.+)$/i);
  const candidate = doiUrl ? doiUrl[1] : text.replace(/^doi:\s*/i, "");
  const match = candidate.match(/10\.\d{4,9}\/[^\s"'<>]+/i);
  return match ? match[0].replace(/[).,;]+$/, "") : "";
}

function compactSourceUrl(value: string) {
  try {
    const url = new URL(value);
    const pathname = url.pathname.length > 42 ? `${url.pathname.slice(0, 39)}...` : url.pathname;
    return `${url.hostname}${pathname}`;
  } catch {
    return value;
  }
}

function sourceCollectionCandidateProvenance(
  candidate: TeamWorkflowCandidate,
  lang: "zh" | "en",
): SourceCollectionCandidateProvenance {
  const sourceCandidate = candidate as SourceCollectionCandidateWithSource;
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const sourceUrl =
    String(sourceCandidate.sourceUrl || "").trim()
    || metadataString(metadata, "sourceUrl")
    || metadataString(metadata, "sourceRef")
    || metadataString(metadata, "url");
  const sourcePath =
    String(sourceCandidate.sourcePath || "").trim()
    || metadataString(metadata, "sourcePath")
    || metadataString(metadata, "path");
  const doi =
    normalizedDoi(metadataString(metadata, "doi"))
    || normalizedDoi(sourceCandidate.sourceRef)
    || normalizedDoi(sourceUrl);

  if (doi) {
    return {
      kind: "doi",
      label: "DOI",
      value: doi,
      href: `https://doi.org/${doi}`,
    };
  }

  if (/^https?:\/\//i.test(sourceUrl)) {
    return {
      kind: "url",
      label: lang === "zh" ? "网页链接" : "Web link",
      value: compactSourceUrl(sourceUrl),
      href: sourceUrl,
    };
  }

  if (sourcePath) {
    return {
      kind: "file",
      label: lang === "zh" ? "本地文件" : "Local file",
      value: sourcePath,
      href: "",
    };
  }

  if (sourceUrl) {
    return {
      kind: "ref",
      label: lang === "zh" ? "来源标识" : "Source ref",
      value: sourceUrl,
      href: "",
    };
  }

  return {
    kind: "missing",
    label: lang === "zh" ? "缺少来源" : "Missing source",
    value: lang === "zh" ? "没有 sourceUrl/sourcePath/DOI" : "No sourceUrl/sourcePath/DOI",
    href: "",
  };
}

function sourceCollectionCandidateOpenLabel(provenance: SourceCollectionCandidateProvenance, lang: "zh" | "en") {
  if (provenance.kind === "doi") {
    return lang === "zh" ? "打开 DOI" : "Open DOI";
  }
  if (provenance.kind === "url") {
    return lang === "zh" ? "打开网页" : "Open page";
  }
  if (provenance.kind === "file") {
    return lang === "zh" ? "查看本地路径" : "View local path";
  }
  if (provenance.kind === "missing") {
    return lang === "zh" ? "缺少来源" : "Missing source";
  }
  return lang === "zh" ? "查看来源标识" : "View source ref";
}

function sourceCollectionCandidateEvidenceRefs(candidate: TeamWorkflowCandidate) {
  const refs = (candidate as TeamWorkflowCandidate & { evidenceRefs?: unknown }).evidenceRefs;
  return Array.isArray(refs) ? refs.filter(isRecord) : [];
}

function sourceCollectionCandidateTrace(candidate: TeamWorkflowCandidate): SourceCollectionCandidateTrace {
  const sourceCandidate = candidate as SourceCollectionCandidateWithSource;
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const recordMetadata = isRecord(metadata.dataProcessingRecordMetadata) ? metadata.dataProcessingRecordMetadata : {};
  const sourceTraceFromRecord = isRecord(recordMetadata.sourceCollectionTrace) ? recordMetadata.sourceCollectionTrace : {};
  const sourceTrace = Object.keys(sourceTraceFromRecord).length
    ? sourceTraceFromRecord
    : isRecord(metadata.sourceCollectionTrace)
      ? metadata.sourceCollectionTrace
      : {};
  const importedRecord = isRecord(metadata.importedFromDataRecord) ? metadata.importedFromDataRecord : {};
  const collectionTrace = isRecord(metadata.dataProcessingCollectionTrace) ? metadata.dataProcessingCollectionTrace : {};
  const evidenceRefs = sourceCollectionCandidateEvidenceRefs(candidate);
  const dataRecordRef = evidenceRefs.find((ref) => String(ref.type || "") === "data_record");
  const runRef = evidenceRefs.find((ref) => String(ref.type || "") === "data_processing_run");
  return {
    assignmentId: String(sourceTrace.assignmentId || collectionTrace.assignmentId || ""),
    query: String(sourceTrace.query || metadata.query || ""),
    queryId: String(sourceTrace.queryId || metadata.queryId || ""),
    rawLocation: String(importedRecord.rawLocation || sourceTrace.rawLocation || sourceCandidate.sourcePath || ""),
    recordId: String(importedRecord.recordId || dataRecordRef?.id || ""),
    runId: String(sourceTrace.runId || importedRecord.runId || runRef?.id || ""),
    searchProvider: String(sourceTrace.searchProvider || recordMetadata.searchProvider || metadata.searchProvider || ""),
    searchUrl: String(sourceTrace.searchUrl || recordMetadata.searchUrl || metadata.searchUrl || ""),
    sourceRef: String(importedRecord.sourceRef || sourceCandidate.sourceRef || sourceCandidate.sourceUrl || metadataString(metadata, "sourceRef")),
  };
}

function sourceCollectionLanguageLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    en: "英文",
    zh: "中文",
    cn: "中文",
  };
  const en: Record<string, string> = {
    en: "English",
    zh: "Chinese",
    cn: "Chinese",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (value || "-");
}

function sourceCollectionStorageArtifactsForRun(teamId: string, runId: string): SourceCollectionStorageArtifacts | null {
  if (!teamId || !runId) {
    return null;
  }
  const runDirectory = `workspace/teams/${teamId}/source_collection_runs/${runId}`;
  return {
    runDirectory,
    artifactsDirectory: `${runDirectory}/artifacts`,
    searchPlanPath: `${runDirectory}/search_plan.json`,
    searchEventsPath: `${runDirectory}/search_events.jsonl`,
    recordsPath: `${runDirectory}/records.jsonl`,
    candidatesPath: `${runDirectory}/candidates.jsonl`,
    candidateStorePath: `workspace/teams/${teamId}/candidate_store/index.json`,
    dataProcessingRunPath: `workspace/data_processing/runs/${runId}/run.json`,
    dataProcessingRecordsPath: `workspace/data_processing/runs/${runId}/records.jsonl`,
  };
}

function sourceCollectionStorageTargetLabel(target: SourceCollectionStorageOpenTarget, lang: "zh" | "en") {
  const zh: Record<SourceCollectionStorageOpenTarget, string> = {
    run_directory: "打开批次目录",
    artifacts_directory: "打开附件目录",
    search_plan: "打开搜索计划",
    search_events: "打开搜索步骤",
    records: "打开搜集记录",
    candidates: "打开候选镜像",
    candidate_store: "打开候选仓库",
    data_processing_run: "打开通用运行记录",
    data_processing_records: "打开资料记录",
  };
  const en: Record<SourceCollectionStorageOpenTarget, string> = {
    run_directory: "Open run folder",
    artifacts_directory: "Open artifacts",
    search_plan: "Open search plan",
    search_events: "Open search trace",
    records: "Open records",
    candidates: "Open candidates",
    candidate_store: "Open candidate store",
    data_processing_run: "Open generic run",
    data_processing_records: "Open DataRecord",
  };
  return lang === "zh" ? zh[target] : en[target];
}

function sourceCollectionStorageTargetForRef(
  ref: string,
  artifacts: SourceCollectionStorageArtifacts | null,
): SourceCollectionStorageOpenTarget | null {
  if (!artifacts) {
    return null;
  }
  const normalizedRef = String(ref || "").trim();
  const mappings: Array<[keyof SourceCollectionStorageArtifacts, SourceCollectionStorageOpenTarget]> = [
    ["runDirectory", "run_directory"],
    ["artifactsDirectory", "artifacts_directory"],
    ["searchPlanPath", "search_plan"],
    ["searchEventsPath", "search_events"],
    ["recordsPath", "records"],
    ["candidatesPath", "candidates"],
    ["candidateStorePath", "candidate_store"],
    ["dataProcessingRunPath", "data_processing_run"],
    ["dataProcessingRecordsPath", "data_processing_records"],
  ];
  return mappings.find(([key]) => artifacts[key] === normalizedRef)?.[1] ?? null;
}

function hasSourceCollectionPromptCachePolicy(
  policy: TeamWorkflowSourceCollectionPromptCachePolicy | undefined | null,
): policy is TeamWorkflowSourceCollectionPromptCachePolicy {
  return Boolean(policy?.policyId || policy?.requirement || policy?.promptCacheMode);
}

function sourceCollectionPromptCacheStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "").toLowerCase();
  if (lang === "zh") {
    if (normalized === "satisfied") {
      return "已通过";
    }
    if (normalized === "warning") {
      return "警告";
    }
    if (normalized === "blocked") {
      return "已阻断";
    }
    if (normalized === "disabled") {
      return "已关闭";
    }
    return "待检查";
  }
  if (normalized === "satisfied") {
    return "satisfied";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "blocked") {
    return "blocked";
  }
  if (normalized === "disabled") {
    return "disabled";
  }
  return "pending";
}

function sourceCollectionTraceToneLabel(tone: SourceCollectionTraceMessage["tone"], lang: "zh" | "en") {
  if (lang === "zh") {
    return {
      plan: "计划",
      cache: "缓存",
      search: "搜索",
      acquire: "获取",
      extract: "提炼",
      quality: "质检",
      storage: "入候选",
      blocked: "需处理",
    }[tone];
  }
  return {
    plan: "Plan",
    cache: "Cache",
    search: "Search",
    acquire: "Acquire",
    extract: "Extract",
    quality: "Quality",
    storage: "Candidate",
    blocked: "Needs attention",
  }[tone];
}

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

function canvasFromTeam(team: Team | null): TeamOrganizationCanvas | null {
  if (!team || !team.canvas || !("nodes" in team.canvas)) {
    return null;
  }
  return team.canvas as TeamOrganizationCanvas;
}

function sourceCollectionAgentIdsFromCanvas(canvas: TeamOrganizationCanvas | null) {
  const agentIds: Record<string, string> = {};
  const roleSet = new Set(SOURCE_COLLECTION_DEFAULT_ROLES);
  for (const node of canvas?.nodes ?? []) {
    if (roleSet.has(node.role) && node.agentId && !agentIds[node.role]) {
      agentIds[node.role] = node.agentId;
    }
  }
  return agentIds;
}

function sourceCollectionOwnerAgentIdFromCanvas(canvas: TeamOrganizationCanvas | null) {
  const preferredRoles = ["research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator"];
  for (const role of preferredRoles) {
    const node = canvas?.nodes.find((item) => item.role === role && item.agentId);
    if (node?.agentId) {
      return node.agentId;
    }
  }
  return "";
}

function normalizeAgentRoleKey(value: string | undefined | null) {
  return String(value || "").trim().toLowerCase();
}

function researchStageAgentManagementRoute(agentId: string) {
  const params = new URLSearchParams({ pane: "config" });
  const normalized = String(agentId || "").trim();
  if (normalized) {
    params.set("agent", normalized);
  }
  return `/agents?${params.toString()}`;
}

function researchStageAgentModelLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  if (!agent) {
    return lang === "zh" ? "未绑定" : "not bound";
  }
  return agent.dialogueModel?.label
    || agent.llmBindings?.dialogue?.modelId
    || agent.llmBindings?.mentalModel?.modelId
    || (lang === "zh" ? "未配置模型" : "model missing");
}

function researchStageAgentActionableHealthIssues(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return (agent?.health ?? []).filter((issue) => issue.severity !== "info");
}

function researchStageAgentConfigStatusLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  if (!agent) {
    return lang === "zh" ? "待绑定" : "missing";
  }
  const actionableIssues = researchStageAgentActionableHealthIssues(agent);
  if (actionableIssues.some((issue) => issue.severity === "blocking")) {
    return lang === "zh" ? "需修复" : "blocked";
  }
  if (actionableIssues.length) {
    return lang === "zh" ? "需检查" : "needs check";
  }
  return lang === "zh" ? "可用" : "ready";
}

function researchStageAgentConfigTone(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "missing";
  }
  const actionableIssues = researchStageAgentActionableHealthIssues(agent);
  if (actionableIssues.some((issue) => issue.severity === "blocking")) {
    return "blocked";
  }
  if (actionableIssues.length) {
    return "warning";
  }
  return "ready";
}

function canvasViewStyle(nodes: TeamCanvasNode[], frameSize?: CanvasFrameSize): CanvasViewportStyle {
  if (!nodes.length) {
    return {
      "--canvas-offset-x": "0px",
      "--canvas-offset-y": "0px",
      "--canvas-scale": "1",
    };
  }
  const minX = Math.min(...nodes.map((node) => node.x));
  const minY = Math.min(...nodes.map((node) => node.y));
  const maxX = Math.max(...nodes.map((node) => node.x + NODE_WIDTH));
  const maxY = Math.max(...nodes.map((node) => node.y + NODE_HEIGHT));
  const boundsWidth = maxX - minX;
  const boundsHeight = maxY - minY;
  const frameWidth = Math.max(420, Math.round(frameSize?.width || CANVAS_VIEWPORT_WIDTH));
  const frameHeight = Math.max(360, Math.round(frameSize?.height || CANVAS_VIEWPORT_HEIGHT));
  const scale = Math.min(
    1,
    Math.max(
      0.58,
      Math.min((frameWidth - 72) / Math.max(boundsWidth, 1), (frameHeight - 104) / Math.max(boundsHeight, 1)),
    ),
  );
  const targetX = Math.max(40, Math.round((frameWidth / scale - boundsWidth) / 2));
  const targetY = Math.max(54, Math.round((frameHeight / scale - boundsHeight) / 2));
  return {
    "--canvas-offset-x": `${Math.round(targetX - minX)}px`,
    "--canvas-offset-y": `${Math.round(targetY - minY)}px`,
    "--canvas-scale": scale.toFixed(3),
  };
}

function canvasStyleScale(style: CanvasViewportStyle) {
  const parsed = Number(style["--canvas-scale"]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function nodeBoundaryPoint(center: { x: number; y: number }, direction: { x: number; y: number }) {
  const halfWidth = NODE_WIDTH / 2;
  const halfHeight = NODE_HEIGHT / 2;
  const scaleX = Math.abs(direction.x) > 0.0001 ? halfWidth / Math.abs(direction.x) : Number.POSITIVE_INFINITY;
  const scaleY = Math.abs(direction.y) > 0.0001 ? halfHeight / Math.abs(direction.y) : Number.POSITIVE_INFINITY;
  const distanceToRectEdge = Math.min(scaleX, scaleY);
  return {
    x: center.x + direction.x * distanceToRectEdge,
    y: center.y + direction.y * distanceToRectEdge,
  };
}

function edgeLine(
  edge: { id?: string; source: string; target: string; type?: string },
  nodes: TeamCanvasNode[],
  visiblePeerEdges: Array<{ id?: string; source: string; target: string; type?: string }> = [],
) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target) {
    return null;
  }
  const sourceCenter = {
    x: source.x + NODE_WIDTH / 2,
    y: source.y + NODE_HEIGHT / 2,
  };
  const targetCenter = {
    x: target.x + NODE_WIDTH / 2,
    y: target.y + NODE_HEIGHT / 2,
  };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const distance = Math.hypot(dx, dy) || 1;
  const unitX = dx / distance;
  const unitY = dy / distance;
  const sourcePoint = nodeBoundaryPoint(sourceCenter, { x: unitX, y: unitY });
  const targetPoint = nodeBoundaryPoint(targetCenter, { x: -unitX, y: -unitY });
  const x1 = sourcePoint.x;
  const y1 = sourcePoint.y;
  const x2 = targetPoint.x;
  const y2 = targetPoint.y;
  const normalX = -unitY;
  const normalY = unitX;
  const peerEdges = visiblePeerEdges.filter(
    (peerEdge) =>
      (peerEdge.source === edge.source && peerEdge.target === edge.target)
      || (peerEdge.source === edge.target && peerEdge.target === edge.source),
  );
  const peerIndex = Math.max(0, peerEdges.findIndex((peerEdge) => peerEdge.id === edge.id));
  const pairSpread = peerEdges.length > 1 ? (peerIndex - (peerEdges.length - 1) / 2) * 20 : 0;
  const curve = (isCommunicationEdge({ type: edge.type || "" }) ? 42 : 24) + pairSpread;
  const cx = (x1 + x2) / 2 + normalX * curve;
  const cy = (y1 + y2) / 2 + normalY * curve;
  return { x1, y1, x2, y2, cx, cy };
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

function teamConversationStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "").trim();
  const zh: Record<string, string> = {
    linked: "契约已对齐",
    unlinked: "未衔接",
    room_missing: "群聊缺失",
    agent_missing: "成员缺失",
    membership_conflict: "成员不一致",
  };
  const en: Record<string, string> = {
    linked: "contract aligned",
    unlinked: "unlinked",
    room_missing: "room missing",
    agent_missing: "agent missing",
    membership_conflict: "membership mismatch",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

export function linkedRoomRefetchInterval(pageVisible: boolean, status: string) {
  const normalized = String(status || "").toLowerCase();
  const active = normalized === "running" || normalized === "stopping";
  return resolvePollingInterval(
    pageVisible,
    active ? LINKED_ROOM_ACTIVE_REFETCH_MS : LINKED_ROOM_IDLE_REFETCH_MS,
  );
}

function sourceCollectionRunRefetchInterval(pageVisible: boolean, status: string) {
  const normalized = String(status || "").toLowerCase();
  return resolvePollingInterval(
    pageVisible,
    normalized === "collecting" || normalized === "processing" ? 1500 : false,
  );
}

function nextNodeId(nodes: TeamCanvasNode[]) {
  const ids = new Set(nodes.map((node) => node.id));
  let index = nodes.length + 1;
  let candidate = `node-${index}`;
  while (ids.has(candidate)) {
    index += 1;
    candidate = `node-${index}`;
  }
  return candidate;
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

function isCommunicationEdge(edge: { type: string }) {
  return edge.type === "communication" || edge.type === "collaborates_with";
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

function chatRoomStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "running") {
    return lang === "zh" ? "运行中" : "Running";
  }
  if (normalized === "stopping") {
    return lang === "zh" ? "停止中" : "Stopping";
  }
  if (normalized === "failed") {
    return lang === "zh" ? "失败" : "Failed";
  }
  return lang === "zh" ? "就绪" : "Ready";
}

function isResearchWorkflowTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return team.teamId === RESEARCH_TEAM_ID || team.teamSource === "research_organization" || team.teamKind === "research";
}

function isEvolutionSystemTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return (
    EVOLUTION_SYSTEM_TEAM_IDS.has(team.teamId) ||
    team.teamKind === "self_evolution" ||
    team.teamKind === "supervised_evolution" ||
    team.teamSource === "self_evolution" ||
    team.teamSource === "supervised_evolution"
  );
}

function isAiSearchScopeTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return team.teamId === AI_SEARCH_TEAM_ID || team.teamKind === "ai_search" || team.teamSource === "ai_search";
}

function aiSearchSourceRoleLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    primary: "一手证据",
    secondary: "二手索引",
    signal: "线索信号",
  };
  const en: Record<string, string> = {
    primary: "Primary evidence",
    secondary: "Secondary index",
    signal: "Signal only",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

function aiSearchSourceTierLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    tier1: "Tier 1 官方",
    tier2: "Tier 2 可信索引",
    tier3: "Tier 3 信号",
  };
  const en: Record<string, string> = {
    tier1: "Tier 1 official",
    tier2: "Tier 2 trusted",
    tier3: "Tier 3 signal",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

type AiSearchRunDisplay = AiSearchRun | AiSearchRunSummary;

function aiSearchRunCounts(run: AiSearchRunDisplay) {
  if ("summary" in run) {
    return run.summary;
  }
  return {
    cardCount: run.cardCount,
    succeededCount: run.succeededCount,
    failedCount: run.failedCount,
    degradedCount: run.degradedCount ?? 0,
    referenceCount: run.referenceCount,
  };
}

function aiSearchRunQueryCount(run: AiSearchRunDisplay) {
  return "queryPlan" in run ? run.queryPlan.queryCount : run.queryCount;
}

function aiSearchRunPath(run: AiSearchRunDisplay) {
  return "storage" in run ? run.storage.runPath : run.runPath;
}

function aiSearchRunStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    completed: "已完成",
    partial: "部分完成",
    failed: "失败",
    running: "运行中",
  };
  const en: Record<string, string> = {
    completed: "Completed",
    partial: "Partial",
    failed: "Failed",
    running: "Running",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

type AiSearchRunCardDisplay = AiSearchRun["cards"][number];

function aiSearchRunCardExtra(card: AiSearchRunCardDisplay, key: string) {
  return (card as unknown as Record<string, unknown>)[key];
}

function aiSearchRunCardExtraString(card: AiSearchRunCardDisplay, key: string) {
  const value = aiSearchRunCardExtra(card, key);
  return typeof value === "string" ? value.trim() : "";
}

function aiSearchRunCardSearchMode(card: AiSearchRunCardDisplay) {
  return aiSearchRunCardExtraString(card, "searchMode").toLowerCase();
}

function aiSearchRunCardFallbackReason(card: AiSearchRunCardDisplay) {
  return aiSearchRunCardExtraString(card, "fallbackReason");
}

function aiSearchRunCardUsesFallback(card: AiSearchRunCardDisplay) {
  const degraded = aiSearchRunCardExtra(card, "degraded") === true;
  const searchMode = aiSearchRunCardSearchMode(card);
  return degraded || Boolean(aiSearchRunCardFallbackReason(card)) || searchMode.includes("fallback") || searchMode.includes("source_page");
}

function aiSearchRunCardModeLabel(card: AiSearchRunCardDisplay, lang: "zh" | "en") {
  if (aiSearchRunCardUsesFallback(card)) {
    return lang === "zh" ? "源页扫描" : "Source page scan";
  }
  const searchMode = aiSearchRunCardSearchMode(card);
  if (searchMode.includes("web") || searchMode.includes("search")) {
    return lang === "zh" ? "搜索 API" : "Search API";
  }
  return searchMode || (lang === "zh" ? "搜索" : "Search");
}

function aiSearchRunNeedsReviewCount(run: AiSearchRunDisplay) {
  return run.cards.filter((card) => card.status === "failed" || aiSearchRunCardUsesFallback(card)).length;
}

function aiSearchRunPrimaryResultText(run: AiSearchRunDisplay, counts: ReturnType<typeof aiSearchRunCounts>, lang: "zh" | "en") {
  const needsReview = aiSearchRunNeedsReviewCount(run);
  if (counts.succeededCount > 0) {
    return lang === "zh"
      ? `本轮已产出 ${counts.succeededCount} 条可用结果，覆盖 ${counts.referenceCount} 条引用；${needsReview ? `${needsReview} 条需要人工复核。` : "暂无明显失败项。"}`
      : `This run produced ${counts.succeededCount} usable results with ${counts.referenceCount} references; ${needsReview ? `${needsReview} need review.` : "no obvious failed items."}`;
  }
  if (counts.failedCount > 0) {
    return lang === "zh"
      ? `本轮没有形成可用结果，${counts.failedCount} 个来源失败，需要调整主题、来源或网络。`
      : `No usable results were produced; ${counts.failedCount} sources failed and need topic, source, or network review.`;
  }
  return lang === "zh"
    ? "本轮尚未生成结果，先启动搜索或等待执行回写。"
    : "No results have been generated yet; start a search or wait for writeback.";
}

function aiSearchRunNextActionText(run: AiSearchRunDisplay, counts: ReturnType<typeof aiSearchRunCounts>, lang: "zh" | "en") {
  const needsReview = aiSearchRunNeedsReviewCount(run);
  if (run.status === "failed" || counts.succeededCount === 0) {
    return lang === "zh" ? "先检查失败来源，再缩小主题或换一组可信来源重搜。" : "Review failed sources first, then narrow the topic or retry with trusted sources.";
  }
  if (needsReview > 0) {
    return lang === "zh" ? "先复核备用扫描和失败项，通过后再进入资料筛选。" : "Review fallback and failed items before moving to source screening.";
  }
  return lang === "zh" ? "可进入资料筛选，也可以继续扩大主题做下一轮搜索。" : "Ready for source screening, or expand the topic for another search round.";
}

function workflowStateLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    knowledge_collection: "知识搜集",
    source_screening: "资料筛选",
    candidate_ingestion: "候选入库",
    team_memory_ready: "团队共享记忆",
    source_registered: "资料已登记",
    source_needs_confirmation: "资料待确认",
    source_needs_quality_revision: "待质检",
    source_screened: "已筛选",
    source_quality_approved: "已通过",
    source_quality_rejected: "已退回",
    paper_note_draft: "论文笔记草稿",
    paper_note_needs_revision: "论文笔记待修订",
    mechanism_candidate: "机制候选",
    mechanism_needs_revision: "机制待修订",
    mechanism_mapping_candidate: "机制映射候选",
    mapping_needs_revision: "映射待修订",
    hypothesis_candidate: "算法假设候选",
    hypothesis_needs_revision: "假设待修订",
    review_prefiltered: "预审完成",
    review_needs_revision: "预审待修订",
    steward_pack_draft: "治理包草稿",
    steward_pending_source_review: "源待审核",
    steward_pending_knowledge_review: "知识待审批",
    steward_needs_revision: "治理包待修订",
    candidate_graph_visible: "候选图谱可见",
    official_synced: "正式同步完成",
    returned_for_rework: "已退回返工",
  };
  const en: Record<string, string> = {
    knowledge_collection: "Knowledge collection",
    source_screening: "Source screening",
    candidate_ingestion: "Candidate ingestion",
    team_memory_ready: "Team memory ready",
    source_registered: "Source registered",
    source_needs_confirmation: "Source needs confirmation",
    source_needs_quality_revision: "Quality review",
    source_screened: "Screened",
    source_quality_approved: "Approved",
    source_quality_rejected: "Returned",
    paper_note_draft: "Paper note draft",
    paper_note_needs_revision: "Paper note needs revision",
    mechanism_candidate: "Mechanism candidate",
    mechanism_needs_revision: "Mechanism needs revision",
    mechanism_mapping_candidate: "Mechanism mapping candidate",
    mapping_needs_revision: "Mapping needs revision",
    hypothesis_candidate: "Hypothesis candidate",
    hypothesis_needs_revision: "Hypothesis needs revision",
    review_prefiltered: "Review prefiltered",
    review_needs_revision: "Review needs revision",
    steward_pack_draft: "Steward pack draft",
    steward_pending_source_review: "Source review pending",
    steward_pending_knowledge_review: "Knowledge review pending",
    steward_needs_revision: "Steward revision needed",
    candidate_graph_visible: "Candidate graph visible",
    official_synced: "Official sync complete",
    returned_for_rework: "Returned for rework",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (normalized || "-");
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

function workflowIngestionStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    empty: "空",
    blocked: "阻塞",
    needs_screening: "待筛选",
    needs_plan: "待规划",
    needs_revision: "需修订",
    needs_evidence: "补证据",
    needs_review: "待审核",
    in_progress: "推进中",
    pending: "待启动",
    ready: "已跑通",
    planned: "已规划",
    approved: "已通过",
    rejected: "已拒绝",
  };
  const en: Record<string, string> = {
    empty: "empty",
    blocked: "blocked",
    needs_screening: "screening",
    needs_plan: "needs plan",
    needs_revision: "revision",
    needs_evidence: "evidence",
    needs_review: "review",
    in_progress: "in progress",
    pending: "pending",
    ready: "ready",
    planned: "planned",
    approved: "approved",
    rejected: "rejected",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (normalized || "-");
}

function workflowCoordinationStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    empty: "暂无队列",
    blocked: "存在阻塞",
    needs_transfer_decision: "转移待决",
    needs_rework: "返工待处理",
    stewardship_review: "治理待审",
    in_progress: "推进中",
    pendingTransfers: "转移待决",
    needsRework: "返工队列",
    stewardship: "治理队列",
    blockedQueue: "阻塞队列",
    active: "进行中",
  };
  const en: Record<string, string> = {
    empty: "empty",
    blocked: "blocked",
    needs_transfer_decision: "transfer decision",
    needs_rework: "rework needed",
    stewardship_review: "stewardship review",
    in_progress: "in progress",
    pendingTransfers: "transfers",
    needsRework: "rework",
    stewardship: "stewardship",
    blockedQueue: "blocked",
    active: "active",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? workflowIngestionStatusLabel(normalized, lang);
}

function workflowCoordinationChannelLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    team_linked_room: "团队群聊",
    project_agent_bus: "Agent Bus",
  };
  const en: Record<string, string> = {
    team_linked_room: "team room",
    project_agent_bus: "Agent Bus",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (normalized || "-");
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function candidateSourceQualityAssessmentSummary(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const assessment = isRecord(metadata.sourceQualityAssessment) ? metadata.sourceQualityAssessment : null;
  if (!assessment) {
    return null;
  }
  const scores = isRecord(assessment.scores) ? assessment.scores : {};
  return {
    assessmentId: String(assessment.assessmentId || ""),
    decision: String(assessment.decision || ""),
    overallScore: Number(scores.overall || 0),
  };
}

function latestWorkflowCandidate(candidates: TeamWorkflowCandidate[]) {
  return [...candidates].sort((left, right) => {
    const rightTime = new Date(right.updatedAt || right.createdAt || "").getTime();
    const leftTime = new Date(left.updatedAt || left.createdAt || "").getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  })[0] ?? null;
}

function workflowGraphTypeRank(candidateType: string) {
  const order: Record<string, number> = {
    source_manifest: 0,
    paper_note: 1,
    neuro_mechanism: 2,
    mechanism_mapping: 3,
    algorithm_hypothesis: 4,
    review_record: 5,
    candidate_graph: 6,
  };
  return order[candidateType] ?? 7;
}

function workflowGraphLayout(graph: TeamWorkflowCandidateGraphPayload): WorkflowGraphLayout {
  const columns = Math.max(1, Math.floor((WORKFLOW_GRAPH_WIDTH - WORKFLOW_GRAPH_MARGIN_X * 2 + WORKFLOW_GRAPH_NODE_GAP) / (WORKFLOW_GRAPH_NODE_WIDTH + WORKFLOW_GRAPH_NODE_GAP)));
  const nodes = [...graph.nodes]
    .sort((left, right) => {
      const rankDelta = workflowGraphTypeRank(left.candidateType) - workflowGraphTypeRank(right.candidateType);
      if (rankDelta !== 0) {
        return rankDelta;
      }
      return String(left.title || left.candidateId).localeCompare(String(right.title || right.candidateId));
    })
    .map((node, index) => ({
      ...node,
      x: WORKFLOW_GRAPH_MARGIN_X + (index % columns) * (WORKFLOW_GRAPH_NODE_WIDTH + WORKFLOW_GRAPH_NODE_GAP),
      y: WORKFLOW_GRAPH_MARGIN_Y + Math.floor(index / columns) * (WORKFLOW_GRAPH_NODE_HEIGHT + WORKFLOW_GRAPH_NODE_GAP),
    }));
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  const height = Math.max(
    WORKFLOW_GRAPH_MIN_HEIGHT,
    WORKFLOW_GRAPH_MARGIN_Y * 2 + rows * WORKFLOW_GRAPH_NODE_HEIGHT + Math.max(0, rows - 1) * WORKFLOW_GRAPH_NODE_GAP,
  );
  return { nodes, edges: graph.edges, height };
}

function workflowGraphVisualEndpoints(edge: TeamWorkflowCandidateGraphPayload["edges"][number]) {
  const evidenceToCandidateRelations = new Set([
    "supported_by_paper_note",
    "maps_from_neuro_mechanism",
    "inspired_by_mapping",
    "inspired_by_neuro_mechanism",
    "reviews_candidate",
  ]);
  return evidenceToCandidateRelations.has(edge.relation)
    ? { sourceCandidateId: edge.targetCandidateId, targetCandidateId: edge.sourceCandidateId }
    : { sourceCandidateId: edge.sourceCandidateId, targetCandidateId: edge.targetCandidateId };
}

function workflowGraphEdgePath(edge: TeamWorkflowCandidateGraphPayload["edges"][number], nodes: WorkflowGraphNodeView[]) {
  const endpoints = workflowGraphVisualEndpoints(edge);
  const source = nodes.find((node) => node.candidateId === endpoints.sourceCandidateId);
  const target = nodes.find((node) => node.candidateId === endpoints.targetCandidateId);
  if (!source || !target) {
    return null;
  }
  const x1 = source.x + WORKFLOW_GRAPH_NODE_WIDTH;
  const y1 = source.y + WORKFLOW_GRAPH_NODE_HEIGHT / 2;
  const x2 = target.x;
  const y2 = target.y + WORKFLOW_GRAPH_NODE_HEIGHT / 2;
  const curve = Math.max(34, Math.abs(x2 - x1) * 0.42);
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`;
}

function workflowGraphNodeTone(node: TeamWorkflowCandidateGraphNode) {
  if (!node.valid || String(node.qualityStatus || "").includes("broken")) {
    return styles.workflowGraphNodeDanger;
  }
  if (node.requiresReview || String(node.currentState || "").includes("revision")) {
    return styles.workflowGraphNodeWarning;
  }
  if (String(node.currentState || "").includes("synced") || String(node.qualityStatus || "").includes("ready")) {
    return styles.workflowGraphNodeReady;
  }
  return styles.workflowGraphNodeNeutral;
}

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
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>({ label: "", role: "", purpose: "", agentId: "" });
  const [teamMessage, setTeamMessage] = useState("");
  const [teamInterrupt, setTeamInterrupt] = useState(false);
  const [teamTaskTopic, setTeamTaskTopic] = useState("");
  const [showCommunicationEdges, setShowCommunicationEdges] = useState(false);
  const [researchWorkspaceView, setResearchWorkspaceView] = useState<ResearchWorkspaceView>(
    forcedResearchWorkspaceView ?? requestedResearchWorkspaceView ?? "overview",
  );
  const [sourceCollectionDraft, setSourceCollectionDraft] = useState<SourceCollectionDraft>({
    title: "神经算法资料搜集批次",
    topic: "神经预测编码",
    goal: "搜集可追踪的神经科学资料，用来支撑神经网络算法假设。",
    querySeeds: "预测编码皮层层级\n突触可塑性学习规则\n神经门控注意机制",
    inputRefs: "",
    searchLanguages: "en\nzh",
    sourceTypes: "paper\nreview\ndataset",
    maxResultsPerQuery: 8,
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
  const [selectedSourceCollectionStageId, setSelectedSourceCollectionStageId] = useState<SourceCollectionStageModuleId>(
    requestedSourceCollectionStage ?? "collection",
  );
  const [sourceCollectionExpandedPanelId, setSourceCollectionExpandedPanelId] = useState("");
  const [sourceCollectionFocusedPanelId, setSourceCollectionFocusedPanelId] = useState("");
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
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
  });
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace"),
    enabled: teamsQuery.isSuccess,
  });
  const projectBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: () => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT),
  });
  const activeAgents = useMemo(
    () => (workspaceQuery.data?.agents ?? []).filter((agent) => agent.status !== "archived"),
    [workspaceQuery.data],
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
  const requestedVisibleTeamId = requestedTeamId && visibleTeamIds.has(requestedTeamId) ? requestedTeamId : "";
  const requestedVisibleAgentTeamId = requestedAgentTeamId && visibleTeamIds.has(requestedAgentTeamId) ? requestedAgentTeamId : "";
  const selectedVisibleTeamId = selectedTeamId && visibleTeamIds.has(selectedTeamId) ? selectedTeamId : "";
  const fallbackVisibleTeamId = visibleTeams[0]?.teamId ?? "";
  const effectiveTeamId = forcedTeamId || selectedVisibleTeamId || requestedVisibleTeamId || requestedVisibleAgentTeamId || fallbackVisibleTeamId;
  const teamDetailQuery = useQuery({
    queryKey: queryKeys.team(effectiveTeamId),
    queryFn: () => fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}`),
    enabled: Boolean(effectiveTeamId),
  });
  const selectedTeam = teamDetailQuery.data ?? visibleTeams.find((team) => team.teamId === effectiveTeamId) ?? null;
  const researchWorkflowTeamSelected = isResearchWorkflowTeam(selectedTeam);
  const aiSearchScopeTeamSelected = isAiSearchScopeTeam(selectedTeam);
  const aiSearchRunsQuery = useQuery({
    queryKey: queryKeys.teamAiSearchRuns(effectiveTeamId || "none", AI_SEARCH_RUN_PREVIEW_LIMIT),
    queryFn: () =>
      fetchJson<AiSearchRunListPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/ai-search-runs?limit=${AI_SEARCH_RUN_PREVIEW_LIMIT}`,
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
  const teamWorkflowQuery = useQuery({
    queryKey: queryKeys.teamWorkflow(effectiveTeamId || "none"),
    queryFn: () => fetchJson<TeamWorkflowOrchestration>(`/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration`),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected),
  });
  const teamWorkflowCandidatesQuery = useQuery({
    queryKey: queryKeys.teamWorkflowCandidates(effectiveTeamId || "none", TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT),
    queryFn: () =>
      fetchJson<TeamWorkflowCandidateListPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/candidates?limit=${TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT}`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowCandidateGraphQuery = useQuery({
    queryKey: queryKeys.teamWorkflowCandidateGraph(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowCandidateListPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/candidates?candidateType=candidate_graph&limit=${TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT}`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowCoordinationStatusQuery = useQuery({
    queryKey: queryKeys.teamWorkflowCoordinationStatus(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowCoordinationStatus>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/coordination/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowKnowledgeIngestionStatusQuery = useQuery({
    queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowKnowledgeIngestionStatus>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/knowledge-ingestion/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowOfficialModelEvidenceStatusQuery = useQuery({
    queryKey: officialModelEvidenceStatusQueryKey(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowOfficialModelEvidenceStatus>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/official-model-evidence/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowSourceQualityStatusQuery = useQuery({
    queryKey: sourceQualityStatusQueryKey(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowSourceQualityStatus>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/source-quality/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const teamWorkflowPaperNoteChunkStatusQuery = useQuery({
    queryKey: paperNoteChunkStatusQueryKey(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<TeamWorkflowPaperNoteChunkStatus>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/paper-note-chunks/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const researchStageRoundStatusQuery = useQuery({
    queryKey: researchStageRoundStatusQueryKey(effectiveTeamId || "none"),
    queryFn: () =>
      fetchJson<ResearchStageRoundStatusPayload>(
        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/stage-rounds/status`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data),
  });
  const sourceCollectionRunsQuery = useQuery({
    queryKey: queryKeys.teamWorkflowSourceCollectionRuns(effectiveTeamId || "none", SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
    queryFn: () =>
      fetchJson<DataProcessingRunListPayload>(
        `/api/data-processing/runs?limit=${SOURCE_COLLECTION_RUN_PREVIEW_LIMIT}&teamId=${encodeURIComponent(effectiveTeamId)}&startedFrom=team_workflow_source_collection`,
      ),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected),
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
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(linkedChatRoomId)}`),
    enabled: Boolean(linkedChatRoomId && teamDetailQuery.data),
    refetchInterval: (query) => {
      const detail = query.state.data as ChatRoomDetail | undefined;
      return linkedRoomRefetchInterval(pageVisible, detail?.status || linkedRoomStatusForPolling);
    },
  });
  const canvas = canvasFromTeam(selectedTeam);
  const canvasNodes = useMemo(
    () =>
      (canvas?.nodes ?? []).map((node) => ({
        ...node,
        ...(nodePositionDrafts[node.id] ?? {}),
      })),
    [canvas, nodePositionDrafts],
  );
  const selectedNode = canvasNodes.find((node) => node.id === selectedNodeId) ?? canvasNodes[0] ?? null;
  const organizationEdges = useMemo(() => (canvas?.edges ?? []).filter((edge) => !isCommunicationEdge(edge)), [canvas]);
  const communicationEdges = useMemo(
    () => (canvas?.edges ?? []).filter((edge) => isCommunicationEdge(edge)),
    [canvas],
  );
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
  const sourceCollectionAgentIds = useMemo(() => sourceCollectionAgentIdsFromCanvas(canvas), [canvas]);
  const sourceCollectionOwnerAgentId = useMemo(() => sourceCollectionOwnerAgentIdFromCanvas(canvas), [canvas]);
  const sourceCollectionQualityAgentId = sourceCollectionAgentIds.source_quality || sourceCollectionOwnerAgentId || "Source Quality Assessment Agent";
  const researchStageAgentBindingsByStage = useMemo(() => {
    const roleBindings = new Map<string, { agentId: string; label: string; source: "canvas" | "member" | "fallback" }>();

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
      (Object.keys(RESEARCH_STAGE_AGENT_ROLES) as ResearchStageType[]).map((stageType) => {
        const bindings = RESEARCH_STAGE_AGENT_ROLES[stageType].map((definition) => {
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
  }, [activeAgentsById, canvas, selectedTeam?.members]);
  const selectedSourceCollectionRun =
    sourceCollectionRuns.find((run) => run.runId === selectedSourceCollectionRunId) ?? sourceCollectionRuns[0] ?? null;
  const selectedSourceCollectionRunEffectiveId = selectedSourceCollectionRun?.runId ?? "";
  const sourceCollectionRunStatusQuery = useQuery({
    queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: () => fetchJson<DataProcessingStatus>(`/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/status`),
    enabled: Boolean(researchWorkflowTeamSelected && selectedSourceCollectionRunEffectiveId),
    refetchInterval: (query) => {
      const status = query.state.data as DataProcessingStatus | undefined;
      return sourceCollectionRunRefetchInterval(pageVisible, status?.runStatus || "");
    },
  });
  const sourceCollectionAssignmentsQuery = useQuery({
    queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: () =>
      fetchJson<DataProcessingCollectionAssignmentListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/collection-assignments`,
      ),
    enabled: Boolean(researchWorkflowTeamSelected && selectedSourceCollectionRunEffectiveId),
    refetchInterval: () => sourceCollectionRunRefetchInterval(pageVisible, sourceCollectionRunStatusQuery.data?.runStatus || ""),
  });
  const autoCanvasViewportStyle = useMemo(() => canvasViewStyle(canvasNodes, canvasFrameSize), [canvasFrameSize, canvasNodes]);
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
    onSuccess: (_canvas, variables) => {
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
      queryClient.setQueryData(queryKeys.team(team.teamId), team);
      if (team.linkedChatRoom?.roomId) {
        void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
      } else {
        void chatWorkspaceCache.afterTeamChanged(team.teamId);
      }
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
      return fetchJson<TeamWorkflowSourceCollectionRunStartPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: payload.draft.title.trim() || "Challenge Cup source collection",
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
              workflowStage: "knowledge_collection",
              uiEntry: "teams_research_source_collection_panel",
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(payload.run.runId) });
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
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      } else if (variables.stageType === "experiment") {
        setResearchWorkspaceView("experiment");
      } else if (variables.stageType === "iteration") {
        setResearchWorkspaceView("iteration");
      }
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
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
            assessedByAgent: sourceCollectionQualityAgentId,
            decision: payload.decision,
            notes: payload.decision === "approved"
              ? "Source Quality Assessment Agent approved this source for downstream paper_note extraction."
              : "Source Quality Assessment Agent returned this source for repair before downstream extraction.",
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const buildCandidateGraphMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<TeamWorkflowCandidateGraphBuildPayload>(`/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidate-graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "Candidate graph preview",
          createdByAgent: "Candidate Graph Preview Agent",
        }),
      }),
    onSuccess: (payload, teamId) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidateGraph(teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(teamId) });
    },
  });

  const canvasSavePendingForTeam = (teamId: string | undefined | null) =>
    saveCanvasMutation.isPending && Boolean(teamId) && saveCanvasMutation.variables?.teamId === teamId;

  function saveCanvas(nextCanvas: TeamOrganizationCanvas | null) {
    if (!nextCanvas || canvasSavePendingForTeam(nextCanvas.teamId)) {
      return;
    }
    saveCanvasMutation.mutate(nextCanvas);
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

  function renderResearchStageAgentSummary(stageType: ResearchStageType) {
    const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
    const readyCount = bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "ready").length;
    const blockedCount = bindings.filter((binding) => binding.agentId && !binding.agent).length
      + bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "blocked").length;
    const missingCount = bindings.filter((binding) => !binding.agentId).length;
    const toneClass = blockedCount > 0
      ? styles.researchStageAgentSummaryBlocked
      : missingCount > 0
        ? styles.researchStageAgentSummaryMissing
        : styles.researchStageAgentSummaryReady;
    return (
      <div className={`${styles.researchStageAgentSummary} ${toneClass}`}>
        <Bot size={13} />
        <span>{lang === "zh" ? "阶段 Agent" : "Stage Agents"}</span>
        <strong>{readyCount}/{bindings.length}</strong>
      </div>
    );
  }

  function renderResearchStageAgentPanel(stageType: ResearchStageType, variant: "compact" | "page" = "page") {
    const bindings = researchStageAgentBindingsByStage[stageType] ?? [];
    const readyCount = bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "ready").length;
    const panelClassName = [
      styles.researchStageAgentPanel,
      variant === "compact" ? styles.researchStageAgentPanelCompact : "",
    ].filter(Boolean).join(" ");

    return (
      <section className={panelClassName} aria-label={lang === "zh" ? "阶段 Agent 配置" : "Stage Agent configuration"}>
        <div className={styles.researchStageAgentPanelHeader}>
          <div>
            <strong>{lang === "zh" ? "本阶段 Agent" : "Stage Agents"}</strong>
            <span>{readyCount}/{bindings.length} {lang === "zh" ? "可用" : "ready"}</span>
          </div>
          <Link to="/agents">
            <Link2 size={13} />
            {lang === "zh" ? "Agent 管理" : "Agent management"}
          </Link>
        </div>
        <div className={styles.researchStageAgentGrid}>
          {bindings.map((binding) => {
            const tone = binding.agent
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
                ? (lang === "zh" ? "引用失效" : "missing reference")
                : (lang === "zh" ? "待绑定" : "missing");

            return (
              <article
                key={`${stageType}-${binding.key}`}
                className={[
                  styles.researchStageAgentCard,
                  styles[`researchStageAgentCard_${tone}`],
                ].filter(Boolean).join(" ")}
              >
                <div className={styles.researchStageAgentRole}>
                  <small>{lang === "zh" ? binding.zh : binding.en}</small>
                  <strong>{agentName}</strong>
                </div>
                <div className={styles.researchStageAgentMeta}>
                  <span>{lang === "zh" ? binding.zhFocus : binding.enFocus}</span>
                  <span>{researchStageAgentModelLabel(binding.agent, lang)}</span>
                </div>
                <div className={styles.researchStageAgentActions}>
                  <span>{statusLabel}</span>
                  <Link to={binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents"}>
                    <Link2 size={12} />
                    {binding.agent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind")}
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    );
  }

  function sourceCollectionStageAgentBindings(stageId: SourceCollectionStageModuleId) {
    const targetKeys = new Set(SOURCE_COLLECTION_STAGE_AGENT_KEYS[stageId]);
    return (researchStageAgentBindingsByStage.knowledge_collection ?? []).filter((binding) => targetKeys.has(binding.key));
  }

  function renderSourceCollectionStageAgents(stageId: SourceCollectionStageModuleId) {
    const bindings = sourceCollectionStageAgentBindings(stageId);
    if (!bindings.length) {
      return null;
    }
    return (
      <section className={styles.sourceCollectionStageAgentPanel} aria-label={lang === "zh" ? "当前步骤 Agent 配置" : "Current step Agent configuration"}>
        <div className={styles.sourceCollectionStageAgentHeader}>
          <div>
            <strong>{lang === "zh" ? "当前步骤 Agent 配置" : "Step Agent configuration"}</strong>
            <span>{bindings.length} {lang === "zh" ? "个功能 Agent" : "functional Agents"}</span>
          </div>
          <Link to="/agents">
            <Link2 size={12} />
            {lang === "zh" ? "Agent 管理" : "Agent management"}
          </Link>
        </div>
        <div className={styles.sourceCollectionStageAgentList}>
          {bindings.map((binding) => {
            const tone = binding.agent
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
                ? (lang === "zh" ? "引用失效" : "missing reference")
                : (lang === "zh" ? "待绑定" : "missing");
            const modelLabel = researchStageAgentModelLabel(binding.agent, lang);
            return (
              <article
                key={`source-step-${stageId}-${binding.key}`}
                className={[
                  styles.sourceCollectionStageAgentCard,
                  styles[`researchStageAgentCard_${tone}`],
                ].filter(Boolean).join(" ")}
              >
                <div className={styles.sourceCollectionStageAgentCardBody}>
                  <span>
                    <small>{lang === "zh" ? "职责" : "Role"}</small>
                    <strong>{lang === "zh" ? binding.zh : binding.en}</strong>
                  </span>
                  <span>
                    <small>Agent</small>
                    <strong>{agentName}</strong>
                  </span>
                  <span>
                    <small>{lang === "zh" ? "模型" : "Model"}</small>
                    <strong>{modelLabel}</strong>
                  </span>
                </div>
                <div className={styles.sourceCollectionStageAgentCardActions}>
                  <span>{statusLabel}</span>
                  <Link to={binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents"}>
                    <Link2 size={12} />
                    {binding.agent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind")}
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    );
  }

  function renderResearchStageLauncher() {
    if (!researchWorkflowTeamSelected) {
      return null;
    }
    const phaseOrder: ResearchStageType[] = ["knowledge_collection", "experiment", "iteration"];
    const phaseFallback: Record<ResearchStageType, { label: string; primaryAction: string }> = {
      knowledge_collection: {
        label: lang === "zh" ? "知识搜集" : "Knowledge",
        primaryAction: lang === "zh" ? "开始知识搜集" : "Start knowledge",
      },
      experiment: {
        label: lang === "zh" ? "实验" : "Experiment",
        primaryAction: lang === "zh" ? "启动实验规划" : "Plan experiment",
      },
      iteration: {
        label: lang === "zh" ? "迭代" : "Iteration",
        primaryAction: lang === "zh" ? "启动迭代" : "Start iteration",
      },
    };
    const knowledgeCollectionStatusLabel = !selectedSourceCollectionRun
      ? (lang === "zh" ? "未开始" : "not started")
      : selectedTeamExecuteSourceCollectionSearchPending
        ? (lang === "zh" ? "搜索中" : "searching")
        : sourceCollectionSearchOpenAssignmentCount > 0
          ? (lang === "zh" ? "需补充资料" : "more sources needed")
          : sourceCollectionDownstreamOpenAssignmentCount > 0
            ? (lang === "zh" ? "待提炼/筛选" : "downstream pending")
          : sourceManifestCandidates.length > sourceCollectionApprovedCount
            ? (lang === "zh" ? "资料待筛选" : "needs screening")
            : sourceManifestCandidates.length > 0
              ? (lang === "zh" ? "可进入实验" : "ready for experiment")
              : (lang === "zh" ? "等待回写" : "waiting for writeback");
    const knowledgeCollectionPrimaryActionLabel = !selectedSourceCollectionRun
      ? (lang === "zh" ? "开始知识搜集" : "Start knowledge")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (selectedTeamExecuteSourceCollectionSearchPending
          ? (lang === "zh" ? "搜索中" : "Searching")
          : (lang === "zh" ? "搜索下一批" : "Search next batch"))
        : sourceCollectionDownstreamOpenAssignmentCount > 0
          ? (lang === "zh" ? "进入阶段详情" : "Open stage details")
        : sourceManifestCandidates.length > sourceCollectionApprovedCount
          ? (lang === "zh" ? "进入资料筛选" : "Open screening")
          : (lang === "zh" ? "进入搜集工作台" : "Open collection workspace");
    const knowledgeCollectionPrimaryDisabled = !selectedSourceCollectionRun
      ? selectedTeamStartResearchStagePending || !researchStageCanLaunch
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? !canExecuteSourceCollectionSearch
        : false;
    const runSourceCollectionSearchFromConsole = () => {
      if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !canExecuteSourceCollectionSearch) {
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
    const runKnowledgeCollectionPrimaryAction = () => {
      if (!selectedTeam?.teamId) {
        return;
      }
      if (!selectedSourceCollectionRun) {
        launchResearchStage("knowledge_collection");
        return;
      }
      if (sourceCollectionSearchOpenAssignmentCount > 0) {
        runSourceCollectionSearchFromConsole();
        return;
      }
      navigate(researchSourceCollectionRoute(selectedTeam.teamId));
    };
    const stagePrimaryLabel = (stageType: ResearchStageType, fallback: string) => {
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionPrimaryActionLabel;
      }
      return fallback;
    };
    const stageStatusLabel = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionStatusLabel;
      }
      if (active) {
        return lang === "zh" ? "运行中" : "running";
      }
      if (latestRound) {
        return lang === "zh" ? "已有轮次" : "has round";
      }
      return lang === "zh" ? "未启动" : "not started";
    };
    const stagePrimaryDisabled = (stageType: ResearchStageType) => {
      if (stageType === "knowledge_collection") {
        return knowledgeCollectionPrimaryDisabled;
      }
      return selectedTeamStartResearchStagePending;
    };
    const runStagePrimaryAction = (stageType: ResearchStageType) => {
      if (stageType === "knowledge_collection") {
        runKnowledgeCollectionPrimaryAction();
        return;
      }
      launchResearchStage(stageType);
    };
    const stageHint = (stageType: ResearchStageType, active: boolean, latestRound: ResearchStagePhaseStatus["latestRound"] | null | undefined) => {
      if (stageType === "knowledge_collection") {
        if (!selectedSourceCollectionRun) {
          return lang === "zh" ? "生成搜索计划和团队分工，先把资料搜集跑起来。" : "Create the search plan and team assignments.";
        }
        if (selectedTeamExecuteSourceCollectionSearchPending) {
          return lang === "zh" ? "正在执行搜索，结果会写入资料记录和候选资料仓库。" : "Searching now; results will be written into DataRecords and candidates.";
        }
        if (sourceCollectionSearchOpenAssignmentCount > 0) {
          return lang === "zh" ? "还有搜索任务，可继续跑下一批。" : "Search tasks are ready for another batch.";
        }
        if (sourceCollectionDownstreamOpenAssignmentCount > 0) {
          return lang === "zh" ? "搜索已停，后续进入提炼或筛选。" : "Search is idle; extraction or screening is next.";
        }
        if (sourceManifestCandidates.length > sourceCollectionApprovedCount) {
          return lang === "zh" ? "已有候选资料，下一步进入筛选。" : "Candidate sources are ready for screening.";
        }
        return lang === "zh" ? "本轮可补充搜集，或由用户决定进入实验。" : "Add another collection round or move to experiments.";
      }
      if (stageType === "experiment") {
        if (active) {
          return lang === "zh" ? "实验规划已启动，补齐 baseline、指标和记录。" : "Planning is active. Fill baselines, metrics, and records.";
        }
        return latestRound
          ? (lang === "zh" ? "可重新规划实验，或查看上一轮计划。" : "Replan or review the latest plan.")
          : (lang === "zh" ? "知识搜集后，由用户决定启动实验规划。" : "Start experiment planning after collection.");
      }
      if (active) {
        return lang === "zh" ? "迭代已启动，围绕结果复盘和版本化推进。" : "Iteration is active for review and versioning.";
      }
      return latestRound
        ? (lang === "zh" ? "可开启新一轮优化，沉淀交付计划。" : "Start another optimization round and prepare delivery.")
        : (lang === "zh" ? "实验完成后再进入迭代优化。" : "Enter iteration after experiments are complete.");
    };
    const currentStageLabel = researchStageRoundStatus?.currentStage
      ? researchWorkspaceViewLabel(researchStageRoundStatus.currentStage as ResearchStageWorkspaceView, lang)
      : lang === "zh" ? "待启动" : "not started";
    return (
      <section className={styles.researchStageLauncher} aria-label={lang === "zh" ? "科研控制台" : "Research console"}>
        <div className={styles.researchStageLauncherHeader}>
          <div>
            <strong>{lang === "zh" ? "科研控制台（三阶段）" : "Research console (3 stages)"}</strong>
            <span>
              {researchStageRoundStatus
                ? `${lang === "zh" ? "当前阶段" : "Current"} · ${currentStageLabel}`
                : researchStageRoundStatusQuery.isPending
                ? (lang === "zh" ? "读取阶段状态中" : "Loading stage status")
                : (lang === "zh" ? "选择一个阶段开始" : "Choose a stage to start")}
            </span>
          </div>
          <button type="button" onClick={() => void researchStageRoundStatusQuery.refetch()} disabled={researchStageRoundStatusQuery.isFetching}>
            <RefreshCw size={13} />
          </button>
        </div>
        <label className={styles.researchStageTopicInput}>
          <span>{lang === "zh" ? "研究主题" : "Research topic"}</span>
          <input
            value={sourceCollectionDraft.topic}
            onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, topic: event.target.value }))}
            placeholder={lang === "zh" ? "例如：predictive coding" : "e.g. predictive coding"}
          />
        </label>
        <div className={styles.researchStageGrid}>
          {phaseOrder.map((stageType) => {
            const phase = researchStagePhases.find((item) => item.stageType === stageType);
            const fallback = phaseFallback[stageType];
            const latestRound = phase?.latestRound;
            const active = Boolean(phase?.activeRoundId);
            const disabled = stagePrimaryDisabled(stageType);
            const navItem = RESEARCH_WORKSPACE_NAV_ITEMS.find((item) => item.view === stageType);
            const primaryLabel = stagePrimaryLabel(stageType, phase?.primaryAction || fallback.primaryAction);
            return (
              <article key={stageType} className={active ? `${styles.researchStageCard} ${styles.researchStageCardActive}` : styles.researchStageCard}>
                <div className={styles.researchStageCardHead}>
                  <small>{String(phaseOrder.indexOf(stageType) + 1).padStart(2, "0")}</small>
                  <div>
                    <strong>{phase?.label || fallback.label}</strong>
                    <span>{stageStatusLabel(stageType, active, latestRound)}</span>
                  </div>
                </div>
                <p>{stageHint(stageType, active, latestRound)}</p>
                {stageType === "knowledge_collection" && selectedSourceCollectionRun ? (
                  <div className={styles.researchStageCardMetrics}>
                    <span>{sourceCollectionRunLabel(selectedSourceCollectionRun.runId)}</span>
                    <span>{lang === "zh" ? `可搜索 ${sourceCollectionSearchOpenAssignmentCount}` : `search ${sourceCollectionSearchOpenAssignmentCount}`}</span>
                    <span>{lang === "zh" ? `后续 ${sourceCollectionDownstreamOpenAssignmentCount}` : `next ${sourceCollectionDownstreamOpenAssignmentCount}`}</span>
                    <span>{lang === "zh" ? `候选 ${sourceManifestCandidates.length}` : `candidates ${sourceManifestCandidates.length}`}</span>
                    <span>{lang === "zh" ? `查询 ${sourceCollectionQueryCount}` : `queries ${sourceCollectionQueryCount}`}</span>
                  </div>
                ) : (
                  <em>{navItem ? (lang === "zh" ? navItem.zhModules : navItem.enModules) : ""}</em>
                )}
                {renderResearchStageAgentSummary(stageType)}
                <div className={styles.researchStageActions}>
                  <button type="button" onClick={() => runStagePrimaryAction(stageType)} disabled={disabled}>
                    {stageType === "knowledge_collection" && selectedSourceCollectionRun && sourceCollectionSearchOpenAssignmentCount > 0 ? <Search size={13} /> : <Play size={13} />}
                    {primaryLabel}
                  </button>
                  {stageType === "knowledge_collection" ? (
                    <button type="button" onClick={() => launchResearchStage(stageType, "new_round")} disabled={selectedTeamStartResearchStagePending || !researchStageCanLaunch}>
                      <Plus size={13} />
                      {lang === "zh" ? "新一轮搜集" : "New round"}
                    </button>
                  ) : null}
                  <Link to={researchWorkspaceStageRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID, stageType)}>
                    <Link2 size={13} />
                    {lang === "zh" ? "阶段详情" : "Details"}
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
        {selectedTeamStartResearchStageError ? (
          <div className={styles.workflowError}>{selectedTeamStartResearchStageError.message}</div>
        ) : null}
        {selectedTeamStartResearchStageResult?.stageRound ? (
          <div className={styles.workflowSuccess}>
            {researchStageStartFeedbackText(
              selectedTeamStartResearchStageResult,
              lang,
              researchWorkspaceViewLabel(selectedTeamStartResearchStageResult.stageRound.stageType as ResearchStageWorkspaceView, lang),
            )}
          </div>
        ) : null}
      </section>
    );
  }

  function renderAiSearchSourceScopePanel() {
    const scope = selectedTeam?.sourceScope ?? null;
    const latestRunCounts = latestAiSearchRun ? aiSearchRunCounts(latestAiSearchRun) : null;
    const latestRunStatusClass =
      latestAiSearchRun?.status === "failed"
        ? styles.aiSearchRunStatusFailed
        : latestAiSearchRun?.status === "partial"
        ? styles.aiSearchRunStatusPartial
        : latestAiSearchRun?.status === "running"
        ? styles.aiSearchRunStatusRunning
        : styles.aiSearchRunStatusCompleted;
    return (
      <section className={styles.aiSearchScopePanel}>
        <div className={styles.aiSearchScopeHeader}>
          <div>
            <strong>{lang === "zh" ? "AI 搜索执行台" : "AI search workspace"}</strong>
            <span>
              {scope
                ? lang === "zh"
                  ? `按 ${scope.summary.enabledByDefaultCount} 个默认可信源搜索，结果保留证据链接和存放位置`
                  : `Searches ${scope.summary.enabledByDefaultCount} trusted default sources and keeps evidence links plus storage`
                : (lang === "zh" ? "等待团队详情载入" : "Waiting for team detail")}
            </span>
          </div>
          <span className={styles.aiSearchScopeBadge}>
            {scope?.policy.requiresPrimaryEvidenceForConclusion
              ? (lang === "zh" ? "结论需一手证据" : "Primary proof required")
              : (lang === "zh" ? "证据规则未启用" : "Proof rule off")}
          </span>
        </div>
        {scope ? (
          <>
            <div className={styles.aiSearchWorkflowSummary}>
              <div>
                <strong>{lang === "zh" ? "搜索过程" : "Search process"}</strong>
                <span>
                  {lang === "zh"
                    ? "主题输入后依次生成搜索、读取可信来源、提取摘要与引用、保存运行记录。"
                    : "A topic becomes queries, trusted sources are scanned, summaries and references are extracted, and the run is stored."}
                </span>
              </div>
              <small>
                {lang === "zh"
                  ? "主视图只显示可判断结果；技术细节在下方展开。"
                  : "Main view shows decision-ready results; technical details stay collapsed below."}
              </small>
            </div>
            <form
              className={styles.aiSearchRunPanel}
              onSubmit={(event) => {
                event.preventDefault();
                if (!selectedTeam?.teamId || !aiSearchRunCanStart) {
                  return;
                }
                startAiSearchRunMutation.mutate({
                  teamId: selectedTeam.teamId,
                  topic: aiSearchRunTopic,
                });
              }}
            >
              <div className={styles.aiSearchRunHeader}>
                <div>
                  <strong>{lang === "zh" ? "启动一轮搜索" : "Start a search round"}</strong>
                  <span>{lang === "zh" ? "主题 -> 可信来源 -> 摘要/引用 -> 运行记录" : "Topic -> trusted sources -> summary/refs -> run record"}</span>
                </div>
                <button type="submit" disabled={!aiSearchRunCanStart}>
                  <Search size={13} />
                  {selectedTeamStartAiSearchPending
                    ? (lang === "zh" ? "搜索中" : "Searching")
                    : (lang === "zh" ? "启动一键搜索" : "Start search")}
                </button>
              </div>
              <label className={styles.aiSearchRunTopic}>
                <span>{lang === "zh" ? "主题" : "Topic"}</span>
                <input
                  value={aiSearchRunTopic}
                  onChange={(event) => setAiSearchRunTopic(event.target.value)}
                  placeholder={lang === "zh" ? "AI 最新动态" : "Latest AI updates"}
                />
              </label>
              {selectedTeamStartAiSearchError ? (
                <div className={styles.messageError}>{selectedTeamStartAiSearchError.message}</div>
              ) : null}
              <div className={styles.aiSearchRunResultHeader}>
                <strong>{lang === "zh" ? "最近搜索结果" : "Recent search results"}</strong>
                <span>
                  {aiSearchRunsQuery.isFetching
                    ? (lang === "zh" ? "刷新中" : "refreshing")
                    : `${aiSearchRunsQuery.data?.summary.visibleRunCount ?? aiSearchRuns.length}/${aiSearchRunsQuery.data?.summary.runCount ?? aiSearchRuns.length}`}
                </span>
              </div>
              {latestAiSearchRun && latestRunCounts ? (
                <div className={styles.aiSearchRunLatest}>
                  <div className={styles.aiSearchRunSummary}>
                    <div>
                      <strong>{latestAiSearchRun.title}</strong>
                      <span>{latestAiSearchRun.runId} · {latestAiSearchRun.topic}</span>
                    </div>
                    <span className={`${styles.aiSearchRunStatus} ${latestRunStatusClass}`}>
                      {aiSearchRunStatusLabel(latestAiSearchRun.status, lang)}
                    </span>
                  </div>
                  <div className={styles.aiSearchRunInsight}>
                    <div>
                      <strong>{lang === "zh" ? "本轮判断" : "Run readout"}</strong>
                      <span>{aiSearchRunPrimaryResultText(latestAiSearchRun, latestRunCounts, lang)}</span>
                    </div>
                    <small>{aiSearchRunNextActionText(latestAiSearchRun, latestRunCounts, lang)}</small>
                  </div>
                  <div className={styles.aiSearchRunStats}>
                    <span>{lang === "zh" ? "查询" : "queries"} <strong>{aiSearchRunQueryCount(latestAiSearchRun)}</strong></span>
                    <span>{lang === "zh" ? "可用结果" : "usable"} <strong>{latestRunCounts.succeededCount}</strong></span>
                    <span>{lang === "zh" ? "需复核" : "review"} <strong>{aiSearchRunNeedsReviewCount(latestAiSearchRun)}</strong></span>
                    <span>{lang === "zh" ? "失败" : "failed"} <strong>{latestRunCounts.failedCount}</strong></span>
                    {latestRunCounts.degradedCount ? (
                      <span>{lang === "zh" ? "降级" : "fallback"} <strong>{latestRunCounts.degradedCount}</strong></span>
                    ) : null}
                    <span>{lang === "zh" ? "引用" : "refs"} <strong>{latestRunCounts.referenceCount}</strong></span>
                  </div>
                  <div className={styles.aiSearchRunCards}>
                    {latestAiSearchRun.cards.slice(0, 6).map((card) => {
                      const cardNeedsReview = card.status === "failed" || aiSearchRunCardUsesFallback(card);
                      const cardModeLabel = aiSearchRunCardModeLabel(card, lang);
                      const fallbackReason = aiSearchRunCardFallbackReason(card);
                      const cardClasses = [styles.aiSearchRunCard];
                      if (card.status === "failed") {
                        cardClasses.push(styles.aiSearchRunCardFailed);
                      } else if (cardNeedsReview) {
                        cardClasses.push(styles.aiSearchRunCardReview);
                      }
                      if (card.degraded) {
                        cardClasses.push(styles.aiSearchRunCardDegraded);
                      }
                      return (
                        <article key={card.cardId} className={cardClasses.filter(Boolean).join(" ")}>
                          <div className={styles.aiSearchRunCardHeader}>
                            <div>
                              <strong>{card.sourceName || card.sourceId}</strong>
                              <span>
                                {card.groupLabel} · {aiSearchSourceTierLabel(card.tier, lang)} · {card.sourceType}
                                {cardModeLabel ? ` · ${cardModeLabel}` : ""}
                              </span>
                            </div>
                            <span>
                              {card.status === "failed" ? (lang === "zh" ? "失败" : "failed") : cardNeedsReview ? (lang === "zh" ? "需复核" : "review") : (lang === "zh" ? "可用" : "usable")}
                            </span>
                          </div>
                          <div className={styles.aiSearchRunQuery}>
                            <span>{lang === "zh" ? "搜索词" : "Query"}</span>
                            <strong>{card.query}</strong>
                            {cardModeLabel ? <em>{cardModeLabel}</em> : null}
                          </div>
                          {card.degraded && fallbackReason ? (
                            <small className={styles.aiSearchRunFallbackReason}>
                              {lang === "zh" ? "主搜索降级" : "Primary search fallback"}: {fallbackReason}
                            </small>
                          ) : null}
                          <p>{card.summary || (card.status === "failed" ? (lang === "zh" ? "搜索执行失败，已保留失败卡片。" : "Search failed; the failed card was retained.") : card.query)}</p>
                          <div className={styles.aiSearchRunRefs}>
                            <small>{lang === "zh" ? "证据链接" : "Evidence links"}</small>
                            {card.references.length ? (
                              card.references.slice(0, 3).map((reference) => (
                                <a key={`${card.cardId}-${reference.url}`} href={reference.url} target="_blank" rel="noreferrer">
                                  {reference.title || reference.url}
                                </a>
                              ))
                            ) : (
                              <span>{lang === "zh" ? "暂无可点开的参考来源" : "No clickable references yet"}</span>
                            )}
                          </div>
                          {fallbackReason || card.resultText ? (
                            <details className={styles.aiSearchRunCardDetails}>
                              <summary>{lang === "zh" ? "执行细节" : "Execution detail"}</summary>
                              {fallbackReason ? <span>{fallbackReason}</span> : null}
                              {card.resultText ? <p>{card.resultText}</p> : null}
                            </details>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                  <div className={styles.aiSearchRunStorage}>
                    <strong>{lang === "zh" ? "存放位置" : "Stored at"}</strong>
                    <span>{aiSearchRunPath(latestAiSearchRun)}</span>
                  </div>
                </div>
              ) : (
                <div className={styles.empty}>
                  {aiSearchRunsQuery.isPending
                    ? (lang === "zh" ? "正在读取最近搜索结果..." : "Loading recent search results...")
                    : (lang === "zh" ? "还没有搜索记录。输入主题后启动一轮搜索，结果会按“本轮判断、证据链接、存放位置”展示。" : "No search records yet. Enter a topic and start a search round; results will show readout, evidence links, and storage.")}
                </div>
              )}
            </form>
            <details className={styles.aiSearchScopeDetails}>
              <summary>
                <span>{lang === "zh" ? "来源与技术边界" : "Sources and technical boundary"}</span>
                <small>{lang === "zh" ? "白名单、去重、存储路径" : "Allowlist, dedupe, storage path"}</small>
              </summary>
              <p className={styles.aiSearchScopeDescription}>{scope.description}</p>
              <div className={styles.aiSearchScopeStats}>
                <span>{lang === "zh" ? "来源分组" : "Groups"} <strong>{scope.summary.groupCount}</strong></span>
                <span>{lang === "zh" ? "默认启用" : "Default on"} <strong>{scope.summary.enabledByDefaultCount}</strong></span>
                <span>{lang === "zh" ? "仅线索" : "Signals"} <strong>{scope.summary.signalOnlyCount}</strong></span>
              </div>
              <div className={styles.aiSearchScopePolicy}>
                <span>{lang === "zh" ? "默认 Tier" : "Default tiers"}: {scope.policy.defaultEnabledTiers.join(", ")}</span>
                <span>{lang === "zh" ? "去重" : "Dedupe"}: {scope.policy.dedupeBy.join(" / ")}</span>
                <span>{lang === "zh" ? "正式知识写入" : "Formal write"}: {scope.policy.writesFormalKnowledge ? "on" : "off"}</span>
                <span>{scope.storage.path}</span>
              </div>
              <div className={styles.aiSearchSourceGroups}>
                {scope.groups.map((group) => (
                  <article key={group.groupId} className={styles.aiSearchSourceGroup}>
                    <div className={styles.aiSearchSourceGroupHeader}>
                      <div>
                        <strong>{group.label}</strong>
                        <span>{aiSearchSourceTierLabel(group.tier, lang)} · {aiSearchSourceRoleLabel(group.evidenceRole, lang)}</span>
                      </div>
                      <span className={group.enabledByDefault ? styles.aiSearchScopeEnabled : styles.aiSearchScopeSignal}>
                        {group.enabledByDefault ? (lang === "zh" ? "默认启用" : "enabled") : (lang === "zh" ? "线索" : "signal")}
                      </span>
                    </div>
                    <p>{group.description}</p>
                    <div className={styles.aiSearchSourceList}>
                      {group.sources.map((source) => (
                        <a key={source.sourceId} href={source.url} target="_blank" rel="noreferrer" className={styles.aiSearchSourceItem}>
                          <strong>{source.name}</strong>
                          <span>{source.sourceType} · {source.region} · {source.language}</span>
                          <small>{source.tags.slice(0, 4).join(" / ")}</small>
                        </a>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </details>
          </>
        ) : (
          <div className={styles.empty}>
            {teamDetailQuery.isPending
              ? (lang === "zh" ? "正在读取 AI 搜索范围名单..." : "Loading AI search source scope...")
              : (lang === "zh" ? "当前团队详情没有返回 sourceScope。" : "This Team detail did not return sourceScope.")}
          </div>
        )}
      </section>
    );
  }

  function renderSourceCollectionConversation() {
    const toneClass: Record<SourceCollectionTraceMessage["tone"], string> = {
      plan: styles.sourceCollectionTrace_plan,
      cache: styles.sourceCollectionTrace_cache,
      search: styles.sourceCollectionTrace_search,
      acquire: styles.sourceCollectionTrace_acquire,
      extract: styles.sourceCollectionTrace_extract,
      quality: styles.sourceCollectionTrace_quality,
      storage: styles.sourceCollectionTrace_storage,
      blocked: styles.sourceCollectionTrace_blocked,
    };
    const currentTraceMessage =
      sourceCollectionTraceMessages.find((message) => message.id.startsWith("active-work-"))
      ?? sourceCollectionTraceMessages.find((message) => message.id === "search-execution-summary")
      ?? sourceCollectionTraceMessages.find((message) => message.id.startsWith("writeback-"))
      ?? (sourceCollectionOperationFailed ? sourceCollectionTraceMessages.find((message) => message.tone === "blocked") : null)
      ?? (!selectedSourceCollectionRun ? sourceCollectionTraceMessages.find((message) => message.id === "coordination-plan") : null)
      ?? (sourceCollectionSearchOpenAssignmentCount > 0 || sourceCollectionDownstreamOpenAssignmentCount > 0 ? sourceCollectionTraceMessages.find((message) => message.id === "assignment-summary") : null)
      ?? (sourceManifestCandidates.length ? sourceCollectionTraceMessages.find((message) => message.id.startsWith("candidate-")) : null)
      ?? sourceCollectionTraceMessages[0]
      ?? null;
    const visibleResults = sourceManifestCandidates.slice(0, 10);
    return (
      <section id="source-collection-process" className={styles.sourceCollectionConversationPanel} aria-label={lang === "zh" ? "搜集对话流" : "Collection conversation"}>
        <div className={styles.sourceCollectionConversationHeader}>
          <div>
            <strong>{lang === "zh" ? "当前搜集动作" : "Current collection action"}</strong>
          </div>
          <small>{sourceCollectionConsoleStatusText}</small>
        </div>
        <div className={styles.sourceCollectionTraceList}>
          {currentTraceMessage ? [currentTraceMessage].map((message, index) => (
            <article key={message.id} className={`${styles.sourceCollectionTraceMessage} ${toneClass[message.tone]}`}>
              <div className={styles.sourceCollectionTraceAvatar}>
                <small>{String(index + 1).padStart(2, "0")}</small>
                <span>{sourceCollectionTraceToneLabel(message.tone, lang)}</span>
              </div>
              <div className={styles.sourceCollectionTraceBody}>
                <div className={styles.sourceCollectionTraceMeta}>
                  <strong>{sourceCollectionTraceToneLabel(message.tone, lang)}</strong>
                  <span>{sourceCollectionStatusLabel(message.status, lang)}</span>
                </div>
                <h3>{message.title}</h3>
                <p>{message.body}</p>
                <div className={styles.sourceCollectionTraceOwner}>
                  <span>{sourceCollectionAgentRoleLabel(message.agentRole, lang)}</span>
                </div>
                {message.refs.length || message.storageRefs.length ? (
                  <details className={styles.sourceCollectionTraceDetails}>
                    <summary>{lang === "zh" ? "查看证据与存放位置" : "Evidence and storage"}</summary>
                    {message.refs.length ? (
                      <div className={styles.sourceCollectionTraceRefs}>
                        {message.refs.map((ref) => (
                          <span key={ref}>{ref}</span>
                        ))}
                      </div>
                    ) : null}
                    {message.storageRefs.length ? (
                      <div className={styles.sourceCollectionTraceStorage}>
                        {message.storageRefs.map((ref) => {
                          const target = sourceCollectionStorageTargetForRef(ref, selectedSourceCollectionStorageArtifacts);
                          return target ? (
                            <button
                              key={ref}
                              type="button"
                              disabled={selectedSourceCollectionStorageOpenPending}
                              onClick={() => openSourceCollectionStorageTarget(target)}
                              title={ref}
                            >
                              <Link2 size={12} />
                              {sourceCollectionStorageTargetLabel(target, lang)}
                            </button>
                          ) : (
                            <span key={ref}>{ref}</span>
                          );
                        })}
                      </div>
                    ) : null}
                  </details>
                ) : null}
              </div>
            </article>
          )) : (
            <div className={styles.empty}>{lang === "zh" ? "还没有正在执行的搜集动作。" : "No active collection action yet."}</div>
          )}
        </div>
        <section id="source-collection-results" className={styles.sourceCollectionResultsPanel} aria-label={lang === "zh" ? "已收集资料" : "Collected sources"}>
          <div className={styles.sourceCollectionResultsHeader}>
            <strong>{lang === "zh" ? "已收集资料" : "Collected sources"}</strong>
            <span>{sourceManifestCandidates.length} {lang === "zh" ? "条候选资料" : "candidate sources"}</span>
          </div>
          <div className={styles.sourceCollectionResultStats}>
            <span>{lang === "zh" ? "已搜到" : "collected"} <strong>{sourceCollectionCollectedCount}</strong></span>
            <span>{lang === "zh" ? "可点击来源" : "clickable sources"} <strong>{sourceCollectionClickableSourceCount}</strong></span>
            <span>{lang === "zh" ? "本地文件" : "local files"} <strong>{sourceCollectionLocalFileCount}</strong></span>
            <span>{lang === "zh" ? "待 Agent 筛选" : "waiting for Agent screening"} <strong>{sourceQualityUnassessedCount}</strong></span>
          </div>
          {sourceCollectionMissingSourceCount > 0 ? (
            <div className={styles.sourceCollectionResultWarning}>
              {lang === "zh"
                ? `${sourceCollectionMissingSourceCount} 条资料缺少 DOI、链接或本地文件路径，不能视为可溯源结果。`
                : `${sourceCollectionMissingSourceCount} sources are missing DOI, link, or local file path.`}
            </div>
          ) : null}
          {visibleResults.length ? (
            <div className={styles.sourceCollectionResultList}>
              {visibleResults.map((candidate) => {
                const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
                const provenance = sourceCollectionCandidateProvenance(candidate, lang);
                const resultStatusLabel = sourceQualitySummary
                  ? workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)
                  : workflowStateLabel(candidate.qualityStatus || candidate.currentState, lang);
                const resultStatusRaw = sourceQualitySummary?.decision || candidate.qualityStatus || candidate.currentState;
                const selected = selectedSourceCollectionCandidateId === candidate.candidateId;
                return (
                  <article
                    key={candidate.candidateId}
                    className={`${styles.sourceCollectionResultItem} ${selected ? styles.sourceCollectionResultItemSelected : ""}`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected}
                    title={lang === "zh" ? "点击查看来源详情" : "Open source detail"}
                    onClick={() => selectSourceCollectionCandidate(candidate)}
                    onKeyDown={(event) => sourceCollectionCandidateCardKeyDown(event, candidate)}
                  >
                    <div className={styles.sourceCollectionResultContent}>
                      <strong title={candidate.title || candidate.candidateId}>{candidate.title || candidate.candidateId}</strong>
                      <p title={candidate.summary || candidate.candidateId}>{candidate.summary || candidate.candidateId}</p>
                      <div className={styles.sourceCollectionResultMeta}>
                        <span>{sourceCollectionSourceTypeLabel(candidate.sourceKind || candidate.candidateType, lang)}</span>
                        {sourceQualitySummary ? (
                          <span>{lang === "zh" ? "评分" : "score"} {sourceQualitySummary.overallScore}/100</span>
                        ) : null}
                        <span>{formatTime(candidate.updatedAt, lang)}</span>
                      </div>
                    </div>
                    <span
                      className={`${styles.workflowTag} ${styles.sourceCollectionResultStatus} ${workflowQualityTone(candidate.qualityStatus)}`}
                      title={resultStatusRaw}
                    >
                      {resultStatusLabel}
                    </span>
                    <div className={`${styles.sourceCollectionResultSource} ${provenance.kind === "missing" ? styles.sourceCollectionResultSourceMissing : ""}`}>
                      <span>{provenance.label}</span>
                      <code title={provenance.href || provenance.value}>{provenance.value}</code>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className={styles.empty}>{lang === "zh" ? "暂无已收集资料。点击资料搜集卡的开始按钮后，结果会出现在这里。" : "No collected sources yet."}</div>
          )}
        </section>
      </section>
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
    return (
      <section className={styles.workflowSourceCollectionStorageActions} aria-label={lang === "zh" ? "搜集证据落盘位置" : "Source collection evidence storage"}>
        <div>
          <strong>{lang === "zh" ? "本轮产物" : "Run artifacts"}</strong>
        </div>
        <div className={styles.workflowSourceCollectionStorageButtons}>
          <button
            type="button"
            disabled={selectedSourceCollectionStorageOpenPending}
            onClick={() => openSourceCollectionStorageTarget("run_directory")}
          >
            <Link2 size={12} />
            {sourceCollectionStorageTargetLabel("run_directory", lang)}
          </button>
        </div>
        <details className={styles.workflowSourceCollectionStorageDetails}>
          <summary>{lang === "zh" ? "更多证据文件" : "More evidence files"}</summary>
          <div className={styles.workflowSourceCollectionStorageButtons}>
            {detailActions.map((target) => (
              <button
                key={target}
                type="button"
                disabled={selectedSourceCollectionStorageOpenPending}
                onClick={() => openSourceCollectionStorageTarget(target)}
              >
                <Link2 size={12} />
                {sourceCollectionStorageTargetLabel(target, lang)}
              </button>
            ))}
          </div>
          <small title={selectedSourceCollectionStorageArtifacts.runDirectory}>
            {selectedSourceCollectionStorageArtifacts.runDirectory}
          </small>
        </details>
        {selectedSourceCollectionStorageOpenResult ? (
          <small>
            {lang === "zh" ? "已打开" : "Opened"} {selectedSourceCollectionStorageOpenResult.openedPath}
          </small>
        ) : null}
        {selectedSourceCollectionStorageOpenError ? (
          <small className={styles.workflowSourceCollectionStorageError}>{selectedSourceCollectionStorageOpenError.message}</small>
        ) : null}
      </section>
    );
  }

  function renderSourceCollectionSelectedSourcePanel() {
    if (!selectedSourceCollectionCandidate) {
      return null;
    }
    const provenance = sourceCollectionCandidateProvenance(selectedSourceCollectionCandidate, lang);
    const trace = selectedSourceCollectionCandidateTrace ?? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate);
    const sourceQualitySummary = candidateSourceQualityAssessmentSummary(selectedSourceCollectionCandidate);
    const runId = trace.runId || selectedSourceCollectionRunEffectiveId;
    const fileStorageTarget = provenance.kind === "file" && selectedSourceCollectionCandidateStorageArtifacts
      ? sourceCollectionStorageTargetForRef(provenance.value, selectedSourceCollectionCandidateStorageArtifacts)
      : null;
    const traceRows = [
      [lang === "zh" ? "类型" : "Type", sourceCollectionSourceTypeLabel(selectedSourceCollectionCandidate.sourceKind || selectedSourceCollectionCandidate.candidateType, lang)],
      [lang === "zh" ? "来源" : "Source", provenance.value],
      [lang === "zh" ? "查询" : "Query", trace.query ? translateResearchPhrase(trace.query, lang) : ""],
      [lang === "zh" ? "资料记录" : "Record", trace.recordId],
      [lang === "zh" ? "批次" : "Run", runId ? sourceCollectionRunLabel(runId) : ""],
      [lang === "zh" ? "分工" : "Assignment", trace.assignmentId],
      [lang === "zh" ? "搜索源" : "Provider", trace.searchProvider],
    ].filter(([, value]) => Boolean(value));
    const storageTargets: SourceCollectionStorageOpenTarget[] = ["run_directory", "search_events", "records", "candidates"];
    return (
      <section className={styles.sourceCollectionSourceDetailPanel} aria-label={lang === "zh" ? "资料来源详情" : "Source provenance detail"}>
        <div className={styles.sourceCollectionSourceDetailHeader}>
          <div>
            <strong title={selectedSourceCollectionCandidate.title || selectedSourceCollectionCandidate.candidateId}>
              {selectedSourceCollectionCandidate.title || selectedSourceCollectionCandidate.candidateId}
            </strong>
            <span>{selectedSourceCollectionCandidate.candidateId}</span>
          </div>
          <span className={`${styles.workflowTag} ${workflowQualityTone(selectedSourceCollectionCandidate.qualityStatus)}`}>
            {sourceQualitySummary
              ? `${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100`
              : workflowStateLabel(selectedSourceCollectionCandidate.currentState, lang)}
          </span>
        </div>
        <div className={styles.sourceCollectionSourceDetailActions}>
          {provenance.href ? (
            <a href={provenance.href} target="_blank" rel="noreferrer" title={provenance.href}>
              <Link2 size={12} />
              {sourceCollectionCandidateOpenLabel(provenance, lang)}
            </a>
          ) : null}
          {fileStorageTarget ? (
            <button
              type="button"
              onClick={() => openSourceCollectionStorageTarget(fileStorageTarget, runId)}
              disabled={selectedSourceCollectionStorageOpenPending}
              title={provenance.value}
            >
              <Link2 size={12} />
              {sourceCollectionStorageTargetLabel(fileStorageTarget, lang)}
            </button>
          ) : null}
          {trace.searchUrl && trace.searchUrl !== provenance.href ? (
            <a href={trace.searchUrl} target="_blank" rel="noreferrer" title={trace.searchUrl}>
              <Search size={12} />
              {lang === "zh" ? "打开搜索页" : "Open search"}
            </a>
          ) : null}
          {runId ? storageTargets.map((target) => (
            <button
              key={`${selectedSourceCollectionCandidate.candidateId}-${target}`}
              type="button"
              onClick={() => openSourceCollectionStorageTarget(target, runId)}
              disabled={selectedSourceCollectionStorageOpenPending}
            >
              <Link2 size={12} />
              {sourceCollectionStorageTargetLabel(target, lang)}
            </button>
          )) : null}
        </div>
        <div className={styles.sourceCollectionSourceDetailFacts}>
          {traceRows.map(([label, value]) => (
            <span key={`${label}-${value}`}>
              <b>{label}</b>
              <code title={value}>{value}</code>
            </span>
          ))}
        </div>
      </section>
    );
  }

  function renderSourceCollectionScreeningPanel() {
    const screeningCandidates = sourceManifestCandidates.slice(0, 6);
    return (
      <details
        id="source-collection-screening-panel"
        className={sourceCollectionPanelClassName("source-collection-screening-panel")}
        open={
          selectedSourceCollectionStageId === "screening"
          || sourceCollectionExpandedPanelId === "source-collection-screening-panel"
          || sourceCollectionScreeningStepState === "active"
          || sourceCollectionScreeningStepState === "pending"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-screening-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        tabIndex={-1}
      >
        <summary>
          <span>{lang === "zh" ? "资料筛选" : "Source screening"}</span>
          <small>{sourceQualityAssessedCount}/{sourceQualityCandidateCount}</small>
        </summary>
        <div id="source-collection-screening-stats" className={styles.workflowSourceQualityStats}>
          <span>{lang === "zh" ? "候选" : "sources"} <strong>{sourceQualityCandidateCount}</strong></span>
          <span>{lang === "zh" ? "已筛" : "assessed"} <strong>{sourceQualityAssessedCount}</strong></span>
          <span>{lang === "zh" ? "通过" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
          <span>{lang === "zh" ? "待筛" : "pending"} <strong>{sourceQualityUnassessedCount}</strong></span>
        </div>
        <div className={styles.sourceCollectionPanelActions}>
          <button
            type="button"
            className={styles.sourceCollectionStagePrimaryAction}
            onClick={runSourceCollectionScreeningAction}
            disabled={sourceCollectionScreeningDisabled || selectedTeamSourceQualityPending}
          >
            <CheckCircle2 size={13} />
            {sourceCollectionScreeningButtonText}
          </button>
          <button
            type="button"
            className={styles.sourceCollectionStageSecondaryAction}
            onClick={openSourceCollectionScreeningPanel}
            disabled={sourceCollectionScreeningDisabled}
          >
            <Eye size={13} />
            {lang === "zh" ? "查看筛选结果" : "View results"}
          </button>
        </div>
        {screeningCandidates.length ? (
          <div className={styles.workflowCandidateList}>
            {screeningCandidates.map((candidate) => {
              const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
              const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
              const canPlanPaperNoteChunks = sourceCandidateHasCompletedExtraction(candidate);
              const candidateQualityPending =
                selectedTeamAssessSourceQualityPending
                && assessSourceQualityMutation.variables?.candidateId === candidate.candidateId;
              const candidatePlanPending =
                selectedTeamPlanPaperNoteChunksPending
                && planPaperNoteChunksMutation.variables?.candidateId === candidate.candidateId;
              const selected = selectedSourceCollectionCandidateId === candidate.candidateId;
              return (
                <article
                  key={candidate.candidateId}
                  className={`${styles.workflowCandidateItem} ${selected ? styles.workflowCandidateItemSelected : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  title={lang === "zh" ? "点击查看来源详情" : "Open source detail"}
                  onClick={() => selectSourceCollectionCandidate(candidate)}
                  onKeyDown={(event) => sourceCollectionCandidateCardKeyDown(event, candidate)}
                >
                  <div className={styles.workflowCandidateHeader}>
                    <strong>{candidate.title || candidate.candidateId}</strong>
                    <span className={`${styles.workflowTag} ${workflowQualityTone(candidate.qualityStatus)}`}>
                      {sourceQualitySummary
                        ? workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)
                        : (lang === "zh" ? "待筛选" : "pending")}
                    </span>
                  </div>
                  <p>{candidate.summary || candidate.candidateType}</p>
                  <div className={styles.workflowCandidateMeta}>
                    <span>{lang === "zh" ? "资料候选" : sourceCollectionSourceTypeLabel(candidate.candidateType, lang)}</span>
                    <span>{formatTime(candidate.updatedAt, lang)}</span>
                    {sourceQualitySummary ? (
                      <span>{lang === "zh" ? "评分" : "score"} {sourceQualitySummary.overallScore}/100</span>
                    ) : null}
                    {chunkPlanSummary ? (
                      <span>
                        paper_note {chunkPlanSummary.completedChunkCount}/{chunkPlanSummary.chunkCount}
                      </span>
                    ) : canPlanPaperNoteChunks ? (
                      <span>{lang === "zh" ? "可分块" : "chunk ready"}</span>
                    ) : null}
                  </div>
                  <div className={styles.workflowCandidateActions}>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
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
                    >
                      <CheckCircle2 size={13} />
                      {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "approved"
                        ? (lang === "zh" ? "筛选中" : "Assessing")
                        : (lang === "zh" ? "通过筛选" : "Approve")}
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
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
                    >
                      <AlertTriangle size={13} />
                      {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "needs_revision"
                        ? (lang === "zh" ? "退回中" : "Returning")
                        : (lang === "zh" ? "退回补资料" : "Repair")}
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        if (!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending) {
                          return;
                        }
                        planPaperNoteChunksMutation.mutate({
                          teamId: selectedTeam.teamId,
                          candidateId: candidate.candidateId,
                        });
                      }}
                      disabled={!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending}
                    >
                      {chunkPlanSummary ? <RefreshCw size={13} /> : <Plus size={13} />}
                      {candidatePlanPending
                        ? (lang === "zh" ? "规划中" : "Planning")
                        : chunkPlanSummary
                          ? (lang === "zh" ? "重建分块" : "Rebuild chunks")
                          : (lang === "zh" ? "生成分块" : "Plan chunks")}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className={styles.empty}>{lang === "zh" ? "暂无候选资料。先在资料搜集卡点击开始搜集或搜索下一批。" : "No source candidates yet."}</div>
        )}
        {teamWorkflowSourceQualityStatus?.actionItems.length ? (
          <div className={styles.workflowIngestionActions}>
            {teamWorkflowSourceQualityStatus.actionItems.slice(0, 3).map((item) => (
              <span key={`${item.code}-${item.candidateId}`} className={workflowIngestionTone(item.severity)}>
                {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
              </span>
            ))}
          </div>
        ) : null}
        {teamWorkflowSourceQualityStatusQuery.error instanceof Error ? (
          <div className={styles.messageError}>{teamWorkflowSourceQualityStatusQuery.error.message}</div>
        ) : null}
        {selectedTeamSourceQualityError ? (
          <div className={styles.messageError}>{selectedTeamSourceQualityError.message}</div>
        ) : null}
      </details>
    );
  }

  function renderSourceCollectionCandidatePanel() {
    const visibleCandidates = sourceManifestCandidates.slice(0, 12);
    return (
      <details
        id="source-collection-candidates-panel"
        className={sourceCollectionPanelClassName("source-collection-candidates-panel")}
        open={
          selectedSourceCollectionStageId === "candidate"
          || sourceCollectionExpandedPanelId === "source-collection-candidates-panel"
          || sourceCollectionCandidateStepState === "active"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-candidates-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        tabIndex={-1}
      >
        <summary>
          <span>{lang === "zh" ? "候选库" : "Candidate library"}</span>
          <small>{sourceManifestCandidates.length}</small>
        </summary>
        <div className={styles.workflowSourceQualityStats}>
          <span>{lang === "zh" ? "候选" : "candidates"} <strong>{sourceManifestCandidates.length}</strong></span>
          <span>{lang === "zh" ? "已筛" : "assessed"} <strong>{sourceQualityAssessedCount}</strong></span>
          <span>{lang === "zh" ? "通过" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
          <span>{lang === "zh" ? "待筛" : "pending"} <strong>{sourceQualityUnassessedCount}</strong></span>
        </div>
        {visibleCandidates.length ? (
          <div className={styles.workflowCandidateList}>
            {visibleCandidates.map((candidate) => {
              const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
              const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
              const qualityText = sourceQualitySummary
                ? `${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100`
                : (lang === "zh" ? "待筛选" : "pending screening");
              const selected = selectedSourceCollectionCandidateId === candidate.candidateId;
              return (
                <article
                  key={candidate.candidateId}
                  className={`${styles.workflowCandidateItem} ${selected ? styles.workflowCandidateItemSelected : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  title={lang === "zh" ? "点击查看来源详情" : "Open source detail"}
                  onClick={() => selectSourceCollectionCandidate(candidate)}
                  onKeyDown={(event) => sourceCollectionCandidateCardKeyDown(event, candidate)}
                >
                  <div className={styles.workflowCandidateHeader}>
                    <strong>{candidate.title || candidate.candidateId}</strong>
                    <span className={`${styles.workflowTag} ${workflowQualityTone(candidate.qualityStatus)}`}>
                      {workflowStateLabel(candidate.currentState, lang)}
                    </span>
                  </div>
                  <p>{candidate.summary || candidate.candidateId}</p>
                  <div className={styles.workflowCandidateMeta}>
                    <span>{sourceCollectionSourceTypeLabel(candidate.sourceKind || candidate.candidateType, lang)}</span>
                    <span>{qualityText}</span>
                    {chunkPlanSummary ? (
                      <span>paper_note {chunkPlanSummary.completedChunkCount}/{chunkPlanSummary.chunkCount}</span>
                    ) : null}
                    <span>{formatTime(candidate.updatedAt, lang)}</span>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className={styles.empty}>{lang === "zh" ? "暂无候选资料。" : "No source candidates yet."}</div>
        )}
      </details>
    );
  }

  function renderSourceCollectionGraphPanel() {
    return (
      <details
        id="source-collection-graph-panel"
        className={sourceCollectionPanelClassName("source-collection-graph-panel")}
        open={
          selectedSourceCollectionStageId === "graph"
          || sourceCollectionExpandedPanelId === "source-collection-graph-panel"
          || sourceCollectionGraphStepState === "active"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-graph-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        tabIndex={-1}
      >
        <summary>
          <span>{lang === "zh" ? "候选图谱" : "Candidate graph"}</span>
          <small>{candidateGraphNodeCount} / {candidateGraphEdgeCount}</small>
        </summary>
        {teamWorkflowCandidateGraph && teamWorkflowCandidateGraphLayout ? (
          <>
            <div className={styles.workflowGraphStats}>
              <span>{lang === "zh" ? "节点" : "nodes"} <strong>{teamWorkflowCandidateGraph.summary.nodeCount}</strong></span>
              <span>{lang === "zh" ? "边" : "edges"} <strong>{teamWorkflowCandidateGraph.summary.edgeCount}</strong></span>
              <span>{lang === "zh" ? "缺口" : "missing"} <strong>{teamWorkflowCandidateGraph.summary.missingLinkCount}</strong></span>
              <span>{lang === "zh" ? "待审" : "review"} <strong>{teamWorkflowCandidateGraph.summary.unreviewedNodeCount}</strong></span>
            </div>
            <div
              className={styles.workflowGraphFrame}
              style={{ "--workflow-graph-height": `${teamWorkflowCandidateGraphLayout.height}px` } as WorkflowGraphFrameStyle}
            >
              <svg
                className={styles.workflowGraphSvg}
                viewBox={`0 0 ${WORKFLOW_GRAPH_WIDTH} ${teamWorkflowCandidateGraphLayout.height}`}
                preserveAspectRatio="xMinYMin meet"
                aria-hidden="true"
              >
                <defs>
                  <marker id="workflow-graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                    <path d="M 0 0 L 10 5 L 0 10 z" />
                  </marker>
                </defs>
                {teamWorkflowCandidateGraphLayout.edges.map((edge) => {
                  const path = workflowGraphEdgePath(edge, teamWorkflowCandidateGraphLayout.nodes);
                  return path ? (
                    <path
                      key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}`}
                      className={styles.workflowGraphEdge}
                      d={path}
                    />
                  ) : null;
                })}
              </svg>
              {teamWorkflowCandidateGraphLayout.nodes.map((node) => (
                <div
                  key={node.candidateId}
                  className={`${styles.workflowGraphNode} ${workflowGraphNodeTone(node)}`}
                  style={{
                    "--workflow-graph-node-x": `${node.x}px`,
                    "--workflow-graph-node-y": `${node.y}px`,
                  } as WorkflowGraphNodeStyle}
                  title={`${node.candidateId} · ${node.currentState}`}
                >
                  <strong>{node.title || node.candidateId}</strong>
                  <span>{workflowStateLabel(node.currentState, lang)}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className={styles.empty}>
            {teamWorkflowCandidateGraphQuery.isPending
              ? (lang === "zh" ? "正在读取候选图谱..." : "Loading candidate graph...")
              : (lang === "zh" ? "尚未生成候选图谱。" : "No candidate graph yet.")}
          </div>
        )}
        {teamWorkflowCandidateGraphQuery.error instanceof Error ? (
          <div className={styles.messageError}>{teamWorkflowCandidateGraphQuery.error.message}</div>
        ) : null}
        {selectedTeamBuildCandidateGraphError ? (
          <div className={styles.messageError}>{selectedTeamBuildCandidateGraphError.message}</div>
        ) : null}
      </details>
    );
  }

  function renderSourceCollectionMemoryPanel() {
    return (
      <details
        id="source-collection-memory-panel"
        className={sourceCollectionPanelClassName("source-collection-memory-panel")}
        open={
          selectedSourceCollectionStageId === "memory"
          || sourceCollectionExpandedPanelId === "source-collection-memory-panel"
          || sourceCollectionMemoryStepState === "active"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-memory-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        tabIndex={-1}
      >
        <summary>
          <span>{lang === "zh" ? "共享记忆前审" : "Memory precheck"}</span>
          <small>{knowledgePendingReviewCount} / {formalKnowledgeItemCount}</small>
        </summary>
        <div className={styles.workflowSourceQualityStats}>
          <span>{lang === "zh" ? "待审" : "pending"} <strong>{knowledgePendingReviewCount}</strong></span>
          <span>{lang === "zh" ? "正式" : "formal"} <strong>{formalKnowledgeItemCount}</strong></span>
          <span>{lang === "zh" ? "通过候选" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
        </div>
        {teamWorkflowKnowledgeIngestionStatus?.actionItems.length ? (
          <div className={styles.workflowIngestionActions}>
            {teamWorkflowKnowledgeIngestionStatus.actionItems.slice(0, 4).map((item) => (
              <span key={`${item.code}-${item.message}`} className={workflowIngestionTone(item.severity)}>
                {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
              </span>
            ))}
          </div>
        ) : null}
        <div className={styles.workflowIngestionBoundary}>
          <span>{lang === "zh" ? "候选区前审" : "candidate precheck"}</span>
          <span>{lang === "zh" ? "正式知识写入关闭" : "formal knowledge write off"}</span>
          <span>{lang === "zh" ? "进入候选仓库后再筛选" : "screen after candidate import"}</span>
        </div>
        {teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error ? (
          <div className={styles.messageError}>{teamWorkflowKnowledgeIngestionStatusQuery.error.message}</div>
        ) : null}
      </details>
    );
  }

  function renderSourceCollectionControlsPanel() {
    const activeModule =
      sourceCollectionStageModules.find((module) => module.id === selectedSourceCollectionStageId)
      ?? sourceCollectionStageModules[0];
    return (
      <section
        id="source-collection-actions"
        ref={sourceCollectionControlPanelRef}
        className={styles.sourceCollectionControlPanel}
        aria-label={lang === "zh" ? "资料搜集控制台" : "Source collection controls"}
      >
        <div className={styles.workflowIngestionHeader}>
          <div>
            <strong>{lang === "zh" ? "阶段详情" : "Stage details"}</strong>
            <span>
              {selectedSourceCollectionRun
                ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionStageFocusLabel}`
                : lang === "zh" ? "等待启动搜集批次" : "Waiting for a collection run"}
            </span>
          </div>
          <span className={`${styles.workflowTag} ${workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}`}>
            {sourceCollectionStatusLabel(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "pending", lang)}
          </span>
        </div>
        <section className={styles.sourceCollectionStageOperationPanel}>
          <div>
            <strong>{activeModule.label}</strong>
            <span>{activeModule.status} · {activeModule.metric}</span>
          </div>
          <button
            type="button"
            className={activeModule.actionTone === "primary" ? styles.sourceCollectionStagePrimaryAction : styles.sourceCollectionStageSecondaryAction}
            disabled={activeModule.actionDisabled}
            onClick={activeModule.onAction}
          >
            {renderSourceCollectionStageActionIcon(activeModule.actionIcon)}
            {activeModule.actionLabel}
          </button>
        </section>
        {renderSourceCollectionSelectedSourcePanel()}
        {selectedSourceCollectionStageId === "collection" ? (
        <>
        <details className={styles.workflowSourceCollectionDetails} open={!selectedSourceCollectionRun}>
          <summary>
            <span>{lang === "zh" ? "本轮配置" : "Run settings"}</span>
          </summary>
          <form
            className={styles.workflowSourceCollectionForm}
            onSubmit={(event) => {
              event.preventDefault();
              if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
                return;
              }
              startSourceCollectionRunMutation.mutate({
                teamId: selectedTeam.teamId,
                draft: sourceCollectionDraft,
              });
            }}
          >
          <label>
            <span>{lang === "zh" ? "主题" : "Topic"}</span>
            <input
              value={sourceCollectionDraft.topic}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, topic: event.target.value }))}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "标题" : "Title"}</span>
            <input
              value={sourceCollectionDraft.title}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, title: event.target.value }))}
            />
          </label>
          <label className={styles.workflowSourceCollectionWide}>
            <span>{lang === "zh" ? "目标" : "Goal"}</span>
            <textarea
              value={sourceCollectionDraft.goal}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, goal: event.target.value }))}
              rows={2}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "搜索种子" : "Query seeds"}</span>
            <textarea
              value={sourceCollectionDraft.querySeeds}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, querySeeds: event.target.value }))}
              rows={3}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "输入引用" : "Input refs"}</span>
            <textarea
              value={sourceCollectionDraft.inputRefs}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, inputRefs: event.target.value }))}
              rows={3}
              placeholder={lang === "zh" ? "可选：本地文件、seed-query:..." : "Optional: local file, seed-query:..."}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "语言" : "Languages"}</span>
            <input
              value={sourceCollectionDraft.searchLanguages}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, searchLanguages: event.target.value }))}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "资料类型" : "Source types"}</span>
            <input
              value={sourceCollectionDraft.sourceTypes}
              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, sourceTypes: event.target.value }))}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "每条上限" : "Max results"}</span>
            <input
              type="number"
              min={1}
              max={100}
              value={sourceCollectionDraft.maxResultsPerQuery}
              onChange={(event) =>
                setSourceCollectionDraft((current) => ({
                  ...current,
                  maxResultsPerQuery: Math.max(1, Math.min(100, Number(event.target.value) || 1)),
                }))
              }
            />
          </label>
          <button type="submit" disabled={!sourceCollectionCanStart || selectedTeamStartSourceCollectionPending}>
            <Search size={13} />
            {selectedTeamStartSourceCollectionPending
              ? (lang === "zh" ? "启动中" : "Starting")
              : (lang === "zh" ? "启动搜集批次" : "Start collection")}
          </button>
          </form>
        </details>
        <div className={styles.workflowSourceCollectionRuns}>
          <label>
            <span>{lang === "zh" ? "最近批次" : "Recent runs"}</span>
            <select
              value={selectedSourceCollectionRunEffectiveId}
              onChange={(event) => setSelectedSourceCollectionRunId(event.target.value)}
              disabled={!sourceCollectionRuns.length}
            >
              {sourceCollectionRuns.length ? (
                sourceCollectionRuns.map((run) => (
                  <option key={run.runId} value={run.runId}>
                    {sourceCollectionRunLabel(run.runId)} · {sourceCollectionRunTitleLabel(run.title, lang)}
                  </option>
                ))
              ) : (
                <option value="">{lang === "zh" ? "暂无批次" : "No runs"}</option>
              )}
            </select>
          </label>
        </div>
        {renderSourceCollectionStorageActions()}
        <details className={styles.workflowSourceCollectionDetails}>
          <summary>
            <span>{lang === "zh" ? "查询与分工详情" : "Query and assignment details"}</span>
          </summary>
          {sourceCollectionAssignments.length ? (
            <div className={styles.workflowSourceCollectionAssignments}>
              {sourceCollectionAssignments.map((assignment) => (
                <button
                  key={assignment.assignmentId}
                  type="button"
                  className={assignment.assignmentId === selectedSourceCollectionAssignment?.assignmentId ? styles.workflowSourceCollectionAssignmentActive : ""}
                  onClick={() => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId: assignment.assignmentId }))}
                >
                  <strong>{sourceCollectionAgentRoleLabel(assignment.agentRole, lang)}</strong>
                  <span>
                    {sourceCollectionStatusLabel(assignment.status, lang)} · {assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0} {lang === "zh" ? "条搜索" : "queries"}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className={styles.empty}>{lang === "zh" ? "还没有生成 Agent 分工。" : "No Agent assignments yet."}</div>
          )}
          {selectedSourceCollectionQueries.length ? (
            <div className={styles.workflowSourceCollectionQueries}>
              {selectedSourceCollectionQueries.slice(0, 6).map((query) => (
                <span key={query.queryId}>
                  <strong>{translateResearchPhrase(query.query, lang)}</strong>
                  <small>{query.queryId} · {sourceCollectionSourceTypeLabel(query.sourceType, lang)} · {sourceCollectionLanguageLabel(query.language, lang)}</small>
                </span>
              ))}
            </div>
          ) : null}
        </details>
        <details className={styles.workflowSourceCollectionDetails}>
          <summary>
            <span>{lang === "zh" ? "兜底手工回写" : "Fallback manual writeback"}</span>
          </summary>
          <form
            className={styles.workflowSourceCollectionOutputForm}
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
          >
          <div className={styles.workflowSourceCollectionOutputHeader}>
            <strong>{lang === "zh" ? "写入一条资料结果" : "Write one collected source"}</strong>
            <span>{lang === "zh" ? "生成资料记录后自动导入候选资料库" : "Creates a DataRecord, then imports a source_manifest candidate"}</span>
          </div>
          <label>
            <span>{lang === "zh" ? "分工任务" : "Assignment"}</span>
            <select
              value={sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId || ""}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId: event.target.value }))}
              disabled={!sourceCollectionAssignments.length}
            >
              {sourceCollectionAssignments.map((assignment) => (
                <option key={assignment.assignmentId} value={assignment.assignmentId}>
                  {sourceCollectionAgentRoleLabel(assignment.agentRole, lang)} · {sourceCollectionStatusLabel(assignment.status, lang)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{lang === "zh" ? "类型" : "Type"}</span>
            <select
              value={sourceCollectionOutputDraft.sourceType}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, sourceType: event.target.value }))}
            >
              {["paper", "url", "dataset", "file", "note", "manual"].map((sourceType) => (
                <option key={sourceType} value={sourceType}>{sourceCollectionSourceTypeLabel(sourceType, lang)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{lang === "zh" ? "标题" : "Title"}</span>
            <input
              value={sourceCollectionOutputDraft.title}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, title: event.target.value }))}
            />
          </label>
          <label>
            <span>{lang === "zh" ? "来源引用" : "Source ref"}</span>
            <input
              value={sourceCollectionOutputDraft.sourceRef}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, sourceRef: event.target.value }))}
              placeholder="https://doi.org/... / local path / dataset id"
            />
          </label>
          <label>
            <span>{lang === "zh" ? "原始位置" : "Raw location"}</span>
            <input
              value={sourceCollectionOutputDraft.rawLocation}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, rawLocation: event.target.value }))}
              placeholder={lang === "zh" ? "页码、文件路径、段落或采集位置" : "Page range, file path, section, or capture location"}
            />
          </label>
          <label className={styles.workflowSourceCollectionWide}>
            <span>{lang === "zh" ? "摘要" : "Summary"}</span>
            <textarea
              value={sourceCollectionOutputDraft.summary}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, summary: event.target.value }))}
              rows={2}
            />
          </label>
          <label className={styles.workflowSourceCollectionWide}>
            <span>{lang === "zh" ? "备注" : "Notes"}</span>
            <input
              value={sourceCollectionOutputDraft.notes}
              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, notes: event.target.value }))}
            />
          </label>
          <button type="submit" disabled={!canRecordSourceCollectionOutput}>
            <CheckCircle2 size={13} />
            {selectedTeamRecordSourceCollectionOutputPending
              ? (lang === "zh" ? "回写中" : "Writing")
              : (lang === "zh" ? "回写并导入候选" : "Write back and import")}
          </button>
          </form>
        </details>
        </>
        ) : null}
        {selectedSourceCollectionStageId === "screening" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "来源" : "sources"} <strong>{sourceQualityCandidateCount}</strong></span>
            <span>{lang === "zh" ? "已筛" : "assessed"} <strong>{sourceQualityAssessedCount}</strong></span>
            <span>{lang === "zh" ? "通过" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
            <span>{lang === "zh" ? "待筛" : "pending"} <strong>{sourceQualityUnassessedCount}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "candidate" ? (
          <>
            <div className={styles.workflowSourceQualityStats}>
              <span>{lang === "zh" ? "候选" : "candidates"} <strong>{sourceManifestCandidates.length}</strong></span>
              <span>{lang === "zh" ? "通过筛选" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
            </div>
            {renderSourceCollectionStorageActions()}
          </>
        ) : null}
        {selectedSourceCollectionStageId === "graph" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "节点" : "nodes"} <strong>{candidateGraphNodeCount}</strong></span>
            <span>{lang === "zh" ? "边" : "edges"} <strong>{candidateGraphEdgeCount}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "memory" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "待审" : "pending"} <strong>{knowledgePendingReviewCount}</strong></span>
            <span>{lang === "zh" ? "正式" : "formal"} <strong>{formalKnowledgeItemCount}</strong></span>
            <span>{lang === "zh" ? "通过候选" : "approved"} <strong>{sourceCollectionApprovedCount}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "collection" ? (
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
                    {selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} {lang === "zh" ? "条搜索" : "queries"} / {selectedTeamExecuteSourceCollectionSearchResult.recordCount} {lang === "zh" ? "条资料记录" : "DataRecord"} / {selectedTeamExecuteSourceCollectionSearchResult.importedCount} {lang === "zh" ? "个候选" : "candidate"}
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
      </section>
    );
  }

  function renderSourceCollectionActiveStagePanel() {
    if (selectedSourceCollectionStageId === "screening") {
      return renderSourceCollectionScreeningPanel();
    }
    if (selectedSourceCollectionStageId === "candidate") {
      return renderSourceCollectionCandidatePanel();
    }
    if (selectedSourceCollectionStageId === "graph") {
      return renderSourceCollectionGraphPanel();
    }
    if (selectedSourceCollectionStageId === "memory") {
      return renderSourceCollectionMemoryPanel();
    }
    return renderSourceCollectionConversation();
  }

  function renderResearchStageStandalonePage(stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">) {
    const stageType: ResearchStageType = stageView;
    const stagePhase = researchStagePhases.find((phase) => phase.stageType === stageType);
    const latestRound = stagePhase?.latestRound;
    const config = {
      experiment: {
        eyebrow: lang === "zh" ? "ai科学研究团队 / 实验阶段" : "AI research team / experiment stage",
        title: lang === "zh" ? "实验规划工作台" : "Experiment planning workspace",
        description: lang === "zh"
          ? "把已筛选知识转成可验证实验，先规划 baseline、指标、数据与执行记录；是否真正进入实验由用户触发。"
          : "Turns screened knowledge into verifiable experiments. Baselines, metrics, data, and run records are planned before execution.",
        primaryAction: lang === "zh" ? "启动实验规划" : "Start experiment planning",
        secondaryAction: lang === "zh" ? "重新规划实验" : "Replan experiment",
        modules: [
          [lang === "zh" ? "实验问题" : "Experiment question", lang === "zh" ? "从知识搜集结论中抽取可验证假设。" : "Extract verifiable hypotheses from collected knowledge."],
          [lang === "zh" ? "Baseline 与指标" : "Baseline and metrics", lang === "zh" ? "记录对照模型、评价指标和成功阈值。" : "Record control models, metrics, and success criteria."],
          [lang === "zh" ? "执行记录" : "Run records", lang === "zh" ? "预留训练、日志、结果和异常回写位置。" : "Reserve writeback slots for runs, logs, results, and exceptions."],
          [lang === "zh" ? "结果对比" : "Result comparison", lang === "zh" ? "后续承接消融、对照和实验结论。" : "Later receives ablations, comparisons, and conclusions."],
        ],
      },
      iteration: {
        eyebrow: lang === "zh" ? "ai科学研究团队 / 迭代阶段" : "AI research team / iteration stage",
        title: lang === "zh" ? "迭代优化工作台" : "Iteration workspace",
        description: lang === "zh"
          ? "把实验结论转成下一轮改进计划，记录复盘、版本、风险和交付门禁；每轮迭代由用户重新触发。"
          : "Turns experiment conclusions into the next improvement plan with review, versions, risks, and delivery gates.",
        primaryAction: lang === "zh" ? "启动迭代" : "Start iteration",
        secondaryAction: lang === "zh" ? "开启新一轮迭代" : "Start new iteration",
        modules: [
          [lang === "zh" ? "复盘结论" : "Review outcome", lang === "zh" ? "整理实验发现、失败原因和保留假设。" : "Summarize findings, failure causes, and retained hypotheses."],
          [lang === "zh" ? "版本计划" : "Version plan", lang === "zh" ? "给算法、数据、参数和文档建立版本边界。" : "Define version boundaries for algorithm, data, parameters, and docs."],
          [lang === "zh" ? "改进任务" : "Improvement tasks", lang === "zh" ? "把下一轮要做的优化拆成可追踪任务。" : "Split next improvements into traceable tasks."],
          [lang === "zh" ? "交付门禁" : "Delivery gate", lang === "zh" ? "保留挑战杯材料、复现实验和风险清单入口。" : "Reserve entries for deliverables, reproducibility, and risk list."],
        ],
      },
    }[stageView];
    const disabled = selectedTeamStartResearchStagePending || !selectedTeam?.teamId;

    return (
      <section className={`${styles.route} ${styles.researchStagePage}`}>
        <header className={`${styles.header} ${styles.researchStagePageHeader}`}>
          <div>
            <p>{config.eyebrow}</p>
            <h1>{config.title}</h1>
          </div>
          <div className={styles.sourceCollectionPageActions}>
            <Link to={teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <ArrowLeft size={14} />
              {lang === "zh" ? "返回团队页面" : "Back to team"}
            </Link>
            <button type="button" onClick={() => void researchStageRoundStatusQuery.refetch()} disabled={researchStageRoundStatusQuery.isFetching}>
              <RefreshCw size={14} />
              {lang === "zh" ? "刷新" : "Refresh"}
            </button>
          </div>
        </header>
        <main className={styles.researchStagePageBody}>
          <section className={styles.researchStageHeroPanel}>
            <div>
              <strong>{stagePhase?.label || researchWorkspaceViewLabel(stageView, lang)}</strong>
              <p>{config.description}</p>
            </div>
            <div className={styles.researchStageHeroStats}>
              <span>
                {lang === "zh" ? "状态" : "Status"}
                <strong>{stagePhase?.status || (lang === "zh" ? "未启动" : "not started")}</strong>
              </span>
              <span>
                {lang === "zh" ? "轮次" : "Rounds"}
                <strong>{stagePhase?.roundCount ?? 0}</strong>
              </span>
              <span>
                {lang === "zh" ? "最近" : "Latest"}
                <strong>{latestRound ? `${latestRound.status} #${latestRound.roundNumber}` : (lang === "zh" ? "无" : "none")}</strong>
              </span>
            </div>
          </section>
          {renderResearchStageAgentPanel(stageType)}
          <section className={styles.researchStageActionPanel}>
            <div>
              <strong>{lang === "zh" ? "阶段启动" : "Stage launch"}</strong>
              <span>
                {stagePhase?.readiness?.reason || (lang === "zh" ? "本阶段只创建规划轮次，不自动执行实验或迭代。" : "This stage creates planning rounds only.")}
              </span>
            </div>
            <div className={styles.researchStagePageActions}>
              <button type="button" onClick={() => launchResearchStage(stageType)} disabled={disabled}>
                <Play size={13} />
                {stagePhase?.primaryAction || config.primaryAction}
              </button>
              <button type="button" onClick={() => launchResearchStage(stageType, "new_round")} disabled={disabled}>
                <Plus size={13} />
                {stagePhase?.secondaryAction || config.secondaryAction}
              </button>
            </div>
            {selectedTeamStartResearchStageError ? <div className={styles.workflowError}>{selectedTeamStartResearchStageError.message}</div> : null}
            {selectedTeamStartResearchStageResult?.stageRound.stageType === stageType ? (
              <div className={styles.workflowSuccess}>
                {researchStageStartFeedbackText(selectedTeamStartResearchStageResult, lang, researchWorkspaceViewLabel(stageView, lang))}
              </div>
            ) : null}
          </section>
          <section className={styles.researchStageModuleGrid} aria-label={lang === "zh" ? "阶段模块" : "Stage modules"}>
            {config.modules.map(([title, body]) => (
              <article key={title} className={styles.researchStageModuleCard}>
                <strong>{title}</strong>
                <span>{body}</span>
              </article>
            ))}
          </section>
          <section className={styles.researchStageBoundaryPanel}>
            <strong>{lang === "zh" ? "边界" : "Boundary"}</strong>
            <span>{lang === "zh" ? "不自动进入下一阶段。" : "Does not auto-transition to the next stage."}</span>
            <span>{lang === "zh" ? "不写正式 Team Knowledge / RAG / official graph。" : "Does not write formal Team Knowledge / RAG / official graph."}</span>
            <span>{lang === "zh" ? "规划结果先留在团队 workflow runtime memory。" : "Planning output remains in team workflow runtime memory."}</span>
          </section>
        </main>
      </section>
    );
  }

  function addNode() {
    if (!canvas) {
      return;
    }
    const id = nextNodeId(canvas.nodes);
    saveCanvas({
      ...canvas,
      nodes: [
        ...canvas.nodes,
        {
          id,
          label: lang === "zh" ? "新角色" : "New role",
          type: "role",
          status: "unbound",
          x: 140 + canvas.nodes.length * 54,
          y: 150 + canvas.nodes.length * 36,
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
    if (!canvas || !selectedNode) {
      return;
    }
    const membership = nodeDraft.agentId ? agentTeamMembership.get(nodeDraft.agentId) : undefined;
    if (membership && membership.teamId !== selectedTeam?.teamId) {
      return;
    }
    const agent = activeAgents.find((item) => item.agentId === nodeDraft.agentId);
    saveCanvas({
      ...canvas,
      nodes: canvas.nodes.map((node) =>
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
    if (!canvas || !selectedNode) {
      return;
    }
    saveCanvas({
      ...canvas,
      nodes: canvas.nodes.map((node) =>
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
    if (!canvas || !selectedNode || canvas.nodes.length <= 1) {
      return;
    }
    const deletedNodeId = selectedNode.id;
    const nextNodes = canvas.nodes.filter((node) => node.id !== deletedNodeId);
    saveCanvas({
      ...canvas,
      nodes: nextNodes,
      edges: canvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId),
    });
    setSelectedNodeId(nextNodes[0]?.id ?? "");
  }

  function connectFromLead() {
    if (!canvas || !selectedNode || canvas.nodes.length < 2) {
      return;
    }
    const source = canvas.nodes[0];
    if (source.id === selectedNode.id || canvas.edges.some((edge) => edge.source === source.id && edge.target === selectedNode.id)) {
      return;
    }
    saveCanvas({
      ...canvas,
      edges: [
        ...canvas.edges,
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
    if (!canvas || canvasSavePendingForTeam(canvas.teamId)) {
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
    if (!dragState || !canvas) {
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
      ...canvas,
      nodes: canvas.nodes.map((node) => (node.id === dragState.nodeId ? { ...node, x: dragState.currentX, y: dragState.currentY } : node)),
    });
  }

  const validation = canvas?.validation;
  const selectedTeamSaveCanvasPending = canvasSavePendingForTeam(selectedTeam?.teamId);
  const selectedTeamSaveCanvasSuccess = saveCanvasMutation.isSuccess && saveCanvasMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamSyncPending = syncTeamChatRoomMutation.isPending && syncTeamChatRoomMutation.variables === selectedTeam?.teamId;
  const selectedTeamArchivePending = archiveTeamMutation.isPending && archiveTeamMutation.variables === selectedTeam?.teamId;
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
  const communicationEdgeHint = showCommunicationEdges
    ? selectedNodeId
      ? (lang === "zh" ? `信息线已展开：选中节点 ${visibleCommunicationEdgeCount} 条` : `Information lines expanded: ${visibleCommunicationEdgeCount} for selected node`)
      : (lang === "zh" ? `信息线已展开：全部 ${visibleCommunicationEdgeCount} 条` : `Information lines expanded: ${visibleCommunicationEdgeCount} total`)
    : (lang === "zh" ? `信息线已收起（${communicationEdges.length} 条，可展开）` : `Information lines hidden (${communicationEdges.length} available)`);
  const communicationEdgeButtonLabel = showCommunicationEdges
    ? (lang === "zh" ? "收起信息线" : "Hide info lines")
    : (lang === "zh" ? `展开信息线 ${communicationEdges.length}` : `Show info ${communicationEdges.length}`);
  const teamWorkflow = teamWorkflowQuery.data ?? null;
  const teamWorkflowCandidates = teamWorkflowCandidatesQuery.data?.candidates ?? [];
  const teamWorkflowValidationSummary = teamWorkflowCandidatesQuery.data?.validationSummary ?? null;
  const teamWorkflowCandidateGraphRecord = latestWorkflowCandidate(teamWorkflowCandidateGraphQuery.data?.candidates ?? []);
  const teamWorkflowCandidateGraph = workflowCandidateGraphFromCandidate(teamWorkflowCandidateGraphRecord);
  const teamWorkflowCandidateGraphLayout = teamWorkflowCandidateGraph ? workflowGraphLayout(teamWorkflowCandidateGraph) : null;
  const teamWorkflowCoordinationStatus = teamWorkflowCoordinationStatusQuery.data ?? null;
  const teamWorkflowKnowledgeIngestionStatus = teamWorkflowKnowledgeIngestionStatusQuery.data ?? null;
  const teamWorkflowOfficialModelEvidenceStatus = teamWorkflowOfficialModelEvidenceStatusQuery.data ?? null;
  const teamWorkflowSourceQualityStatus = teamWorkflowSourceQualityStatusQuery.data ?? null;
  const teamWorkflowPaperNoteChunkStatus = teamWorkflowPaperNoteChunkStatusQuery.data ?? null;
  const researchStageRoundStatus = researchStageRoundStatusQuery.data ?? null;
  const researchStagePhases = researchStageRoundStatus?.phases ?? [];
  const sourceCollectionAssignments = sourceCollectionAssignmentsQuery.data?.assignments ?? [];
  const sourceCollectionRunStatus = sourceCollectionRunStatusQuery.data ?? null;
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
  const selectedTeamStartSourceCollectionPending =
    startSourceCollectionRunMutation.isPending && startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId;
  const selectedTeamStartSourceCollectionError =
    startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId && startSourceCollectionRunMutation.error instanceof Error
      ? startSourceCollectionRunMutation.error
      : null;
  const selectedTeamStartSourceCollectionResult =
    startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId ? startSourceCollectionRunMutation.data : undefined;
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
  const selectedTeamInitialSourceCollectionSearchResult = selectedTeamStartResearchStageResult?.sourceCollectionSearchExecution;
  const selectedSourceCollectionSearchExecutionResult =
    selectedTeamExecuteSourceCollectionSearchResult ?? selectedTeamInitialSourceCollectionSearchResult;
  const selectedSourceCollectionSearchAccepted = Boolean(selectedSourceCollectionSearchExecutionResult?.accepted);
  const selectedSourceCollectionActiveWorkRun = selectedSourceCollectionSearchExecutionResult?.activeWorkRun;
  const selectedSourceCollectionStorageArtifacts =
    selectedSourceCollectionSearchExecutionResult?.storageArtifacts
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
    if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeam.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(selectedTeam.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(selectedTeam.teamId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(selectedTeam.teamId) });
    void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(selectedTeam.teamId) });
    void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(selectedTeam.teamId) });
  }, [
    queryClient,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionSearchAccepted,
    selectedTeam?.teamId,
    sourceCollectionRunStatus?.runStatus,
    sourceCollectionRunStatus?.summary.recordCount,
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
  const sourceCollectionCandidateProvenances = useMemo(
    () => sourceManifestCandidates.map((candidate) => sourceCollectionCandidateProvenance(candidate, lang)),
    [lang, sourceManifestCandidates],
  );
  const sourceCollectionClickableSourceCount = sourceCollectionCandidateProvenances.filter((item) => item.href).length;
  const sourceCollectionLocalFileCount = sourceCollectionCandidateProvenances.filter((item) => item.kind === "file").length;
  const sourceCollectionMissingSourceCount = sourceCollectionCandidateProvenances.filter((item) => item.kind === "missing").length;
  const sourceCollectionCollectedCount = Math.max(sourceCollectionRunSummary?.recordCount ?? 0, sourceManifestCandidates.length);
  const sourceCollectionQueryCount =
    sourceCollectionSearchPlanRef?.queryCount
    ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount
    ?? sourceCollectionAssignments.reduce((total, assignment) => total + (assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0), 0);
  const sourceCollectionApprovedCount = teamWorkflowSourceQualityStatus?.summary.approvedSourceCandidateCount ?? 0;
  const sourceCollectionStageFocusLabel = !selectedSourceCollectionRun
    ? (lang === "zh" ? "尚未启动" : "not started")
    : sourceCollectionSearchOpenAssignmentCount > 0
      ? (lang === "zh" ? "还需补充资料" : "more sources needed")
      : sourceCollectionDownstreamOpenAssignmentCount > 0
        ? (lang === "zh" ? "等待提炼/筛选" : "downstream pending")
      : sourceManifestCandidates.length > sourceCollectionApprovedCount
        ? (lang === "zh" ? "资料待筛选" : "screening needed")
        : sourceManifestCandidates.length > 0
          ? (lang === "zh" ? "可进入实验规划" : "ready for experiment")
          : (lang === "zh" ? "等待结果回写" : "waiting for writeback");
  const sourceCollectionRunStatusValue = String(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "").toLowerCase();
  const sourceCollectionAcceptedBackgroundActive = Boolean(
    selectedSourceCollectionSearchAccepted
    && selectedSourceCollectionActiveWorkRun
    && ["running", "queued"].includes(String(selectedSourceCollectionActiveWorkRun.status || "").toLowerCase())
    && (!sourceCollectionRunStatus || sourceCollectionSearchOpenAssignmentCount > 0)
    && (!sourceCollectionRunStatus || ["collecting", "processing"].includes(sourceCollectionRunStatusValue)),
  );
  const sourceCollectionTraceMessages = useMemo<SourceCollectionTraceMessage[]>(() => {
    const messages: SourceCollectionTraceMessage[] = [];
    messages.push({
      id: "coordination-plan",
      agentRole: "Research Coordination Agent",
      title: selectedSourceCollectionRun
        ? (lang === "zh" ? "已建立本轮资料搜集批次" : "Created the source collection run")
        : (lang === "zh" ? "等待启动资料搜集批次" : "Waiting for a source collection run"),
      body: selectedSourceCollectionRun
        ? `${lang === "zh" ? "目标" : "Goal"}：${translateResearchPhrase(String(selectedSourceCollectionRun.scope?.goal || sourceCollectionDraft.goal || "-"), lang)}`
        : (lang === "zh" ? "点击启动后会生成查询计划、团队 Agent 分工和回写契约。" : "Starting creates a query plan, team-agent assignments, and a writeback contract."),
      status: selectedSourceCollectionRun?.status || "pending",
      tone: selectedSourceCollectionRun ? "plan" : "blocked",
      refs: selectedSourceCollectionRun
        ? [
            `${lang === "zh" ? "批次" : "run"}: ${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)}`,
            `${lang === "zh" ? "主题" : "topic"}: ${translateResearchPhrase(String(selectedSourceCollectionRun.scope?.topic || sourceCollectionDraft.topic), lang)}`,
          ]
        : [],
      storageRefs: selectedSourceCollectionStorageArtifacts
        ? [selectedSourceCollectionStorageArtifacts.runDirectory, selectedSourceCollectionStorageArtifacts.searchPlanPath]
        : [],
    });
    const plannedQueries = sourceCollectionAssignments.flatMap((assignment) => assignment.scope.assignedQueries ?? []);
    const promptCacheGateStatus = sourceCollectionPromptCachePolicy?.gate?.status || sourceCollectionPromptCachePolicyRef?.gateStatus || "";
    const promptCacheMode = sourceCollectionPromptCachePolicy?.promptCacheMode || sourceCollectionPromptCachePolicyRef?.promptCacheMode || "";
    const promptCacheRolePartitions = sourceCollectionPromptCachePolicy?.rolePartitions?.length
      ? sourceCollectionPromptCachePolicy.rolePartitions
      : sourceCollectionAssignments
          .map((assignment) => ({
            agentRole: assignment.agentRole,
            agentId: assignment.agentId,
            promptCachePartition: String(assignment.scope.promptCachePartition || ""),
          }))
          .filter((item) => item.promptCachePartition);
    if (selectedSourceCollectionRun || sourceCollectionPromptCachePolicy || sourceCollectionPromptCachePolicyRef) {
      messages.push({
        id: "prompt-cache-gate",
        agentRole: "Research Coordination Agent",
        title: lang === "zh" ? "KV 缓存门禁已写入本轮搜集" : "KV cache gate attached to this run",
        body: lang === "zh"
          ? `本轮使用 ${sourceCollectionPromptCachePolicy?.modelName || sourceCollectionPromptCachePolicyRef?.modelId || "当前可用 KV 模型"}，稳定前缀只放团队规则、结构契约和回写边界；每次搜索只传当前搜索词、结果引用和存储位置，避免反复重放网页全文。`
          : `This run uses ${sourceCollectionPromptCachePolicy?.modelName || sourceCollectionPromptCachePolicyRef?.modelId || SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL}. The stable prefix keeps team rules, schemas, and writeback boundaries; each search sends only the current query, result refs, and storage location.`,
        status: sourceCollectionPromptCacheStatusLabel(promptCacheGateStatus, lang),
        tone: promptCacheGateStatus === "blocked" ? "blocked" : "cache",
        refs: (lang === "zh"
          ? [
              `缓存要求：${sourceCollectionPromptCacheRequirement}`,
              promptCacheMode ? `缓存模式：${promptCacheMode}` : "",
              "稳定前缀：团队规则 / 结构契约 / 回写边界",
              "动态增量：当前搜索词 / 结果引用",
            ]
          : [
              `requirement: ${sourceCollectionPromptCacheRequirement}`,
              promptCacheMode ? `mode: ${promptCacheMode}` : "",
              "stable prefix: team rules + schema + boundary",
              "dynamic delta: query/result refs only",
            ]).filter(Boolean),
        storageRefs: promptCacheRolePartitions.slice(0, 4).map((item) => `${sourceCollectionAgentRoleLabel(item.agentRole, lang)}：${lang === "zh" ? "缓存分区" : "cache"} ${item.promptCachePartition}`),
      });
    }
    if (plannedQueries.length || sourceCollectionSearchPlanRef || selectedTeamStartSourceCollectionResult?.searchPlan) {
      const plannedQueryCacheRefs = Array.from(
        new Set(
          plannedQueries
            .map((query) => query.execution?.promptCachePartition)
            .filter((value): value is string => Boolean(value)),
        ),
      );
      messages.push({
        id: "query-plan",
        agentRole: "Data Discovery Agent",
        title: lang === "zh" ? "已拆成可执行搜索问题" : "Split into executable search queries",
        body: lang === "zh"
          ? `当前可见 ${plannedQueries.length || sourceCollectionSearchPlanRef?.queryCount || selectedTeamStartSourceCollectionResult?.searchPlan.queryCount || 0} 条搜索问题，按资料类型和语言分配给功能 Agent；搜索词是动态增量，不会挤进稳定缓存前缀。`
          : `${plannedQueries.length || sourceCollectionSearchPlanRef?.queryCount || selectedTeamStartSourceCollectionResult?.searchPlan.queryCount || 0} visible queries are assigned by source type and language; queries are dynamic deltas outside the stable cached prefix.`,
        status: "planned",
        tone: "search",
        refs: plannedQueries.slice(0, 5).map((query) =>
          `${translateResearchPhrase(query.query, lang)} · ${sourceCollectionSourceTypeLabel(query.sourceType, lang)} · ${sourceCollectionLanguageLabel(query.language, lang)}`
        ),
        storageRefs: [
          selectedSourceCollectionStorageArtifacts?.searchPlanPath || "",
          ...plannedQueryCacheRefs.slice(0, 3).map((partition) => `KV ${partition}`),
        ].filter(Boolean),
      });
    }
    if (sourceCollectionAcceptedBackgroundActive && selectedSourceCollectionActiveWorkRun) {
      messages.push({
        id: `active-work-${selectedSourceCollectionActiveWorkRun.runId}`,
        agentRole: "Source Collection Agent",
        title: lang === "zh" ? "正在执行本批资料搜索" : "Running this source search batch",
        body: selectedSourceCollectionActiveWorkRun.currentTask || selectedSourceCollectionActiveWorkRun.summary || (lang === "zh" ? "后台正在把搜索结果写成资料记录和候选资料。" : "The background worker is writing search results into records and candidates."),
        status: selectedSourceCollectionActiveWorkRun.status,
        tone: "search",
        refs: [
          `${selectedSourceCollectionActiveWorkRun.searchOpenAssignmentCount ?? sourceCollectionSearchOpenAssignmentCount} ${lang === "zh" ? "个可搜索任务" : "searchable assignments"}`,
          `${selectedSourceCollectionActiveWorkRun.downstreamOpenAssignmentCount ?? sourceCollectionDownstreamOpenAssignmentCount} ${lang === "zh" ? "个后续任务" : "downstream assignments"}`,
          `${selectedSourceCollectionActiveWorkRun.recordCount ?? sourceCollectionRunSummary?.recordCount ?? 0} ${lang === "zh" ? "条资料记录" : "records"}`,
          `${selectedSourceCollectionActiveWorkRun.queryCount ?? sourceCollectionQueryCount} ${lang === "zh" ? "条搜索问题" : "queries"}`,
        ],
        storageRefs: [selectedSourceCollectionActiveWorkRun.storagePath || selectedSourceCollectionStorageArtifacts?.runDirectory || ""].filter(Boolean),
      });
    }
    if (selectedTeamExecuteSourceCollectionSearchResult?.executionEvents?.length) {
      const events = selectedTeamExecuteSourceCollectionSearchResult.executionEvents;
      const searchedCount = events.filter((event) => event.eventType === "search.executed").length;
      const failedCount = events.filter((event) => event.status === "failed" || event.eventType === "search.failed").length;
      const storageRefs = Array.from(new Set(events.flatMap((event) => event.storageRefs ?? []).filter(Boolean))).slice(0, 6);
      const evidenceRefs = events
        .filter((event) => event.query || event.rawLocation || event.refs?.length)
        .slice(0, 8)
        .map((event) => {
          const query = event.query || event.queryId || event.eventType;
          const ref = event.rawLocation || event.refs?.[0] || "";
          return [query, ref].filter(Boolean).join(" · ");
        });
      messages.push({
        id: "search-execution-summary",
        agentRole: "Source Collection Agent",
        title: lang === "zh" ? "已执行一批搜索并写入候选" : "Ran one search batch and wrote candidates",
        body: lang === "zh"
          ? `本批执行 ${selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} 条搜索，写入 ${selectedTeamExecuteSourceCollectionSearchResult.recordCount} 条资料记录，导入 ${selectedTeamExecuteSourceCollectionSearchResult.importedCount} 个候选资料${failedCount ? `，${failedCount} 条需要补救` : ""}。`
          : `This batch executed ${selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} queries, wrote ${selectedTeamExecuteSourceCollectionSearchResult.recordCount} DataRecords, and imported ${selectedTeamExecuteSourceCollectionSearchResult.importedCount} source_manifest candidates${failedCount ? `; ${failedCount} need follow-up` : ""}.`,
        status: failedCount ? "needs_attention" : "completed",
        tone: failedCount ? "blocked" : "storage",
        refs: [
          `${searchedCount} ${lang === "zh" ? "条元数据搜索" : "metadata searches"}`,
          ...evidenceRefs,
        ],
        storageRefs,
      });
    }
    if (sourceCollectionAssignments.length) {
      const visibleAssignments = sourceCollectionAssignments.slice(0, 5);
      const assignedQueries = visibleAssignments.flatMap((assignment) => assignment.scope.assignedQueries ?? []);
      messages.push({
        id: "assignment-summary",
        agentRole: "Research Coordination Agent",
        title: lang === "zh" ? "已把搜集任务分配给功能 Agent" : "Assigned collection work to functional Agents",
        body: lang === "zh"
          ? `${sourceCollectionAssignments.length} 个任务已分配：${sourceCollectionSearchOpenAssignmentCount} 个还能继续搜索，${sourceCollectionDownstreamOpenAssignmentCount} 个等待提炼或筛选。`
          : `${sourceCollectionAssignments.length} assignments are allocated: ${sourceCollectionSearchOpenAssignmentCount} can still search and ${sourceCollectionDownstreamOpenAssignmentCount} wait for extraction or screening.`,
        status: sourceCollectionSearchOpenAssignmentCount ? "open" : "ready_for_screening",
        tone: sourceCollectionSearchOpenAssignmentCount ? "acquire" : "quality",
        refs: [
          ...visibleAssignments.map((assignment) => `${sourceCollectionAgentRoleLabel(assignment.agentRole, lang)}：${sourceCollectionStatusLabel(assignment.status, lang)}`),
          ...assignedQueries.slice(0, 4).map((query) => translateResearchPhrase(query.query, lang)),
        ],
        storageRefs: visibleAssignments
          .map((assignment) => assignment.scope.promptCachePartition ? `${sourceCollectionAgentRoleLabel(assignment.agentRole, lang)}：KV ${assignment.scope.promptCachePartition}` : assignment.assignmentId)
          .filter(Boolean),
      });
    }
    if (selectedTeamRecordSourceCollectionOutputResult) {
      const records = selectedTeamRecordSourceCollectionOutputResult.output.createdRecords;
      const outputRecord = selectedTeamRecordSourceCollectionOutputResult.output.output;
      messages.push({
        id: `writeback-${outputRecord.outputId}`,
        agentRole: outputRecord.agentRole || "Source Intake Agent",
        title: lang === "zh" ? "已把搜集结果写成资料记录" : "Wrote collected result as DataRecord",
        body: lang === "zh"
          ? `本次回写 ${records.length} 条资料记录，并导入 ${selectedTeamRecordSourceCollectionOutputResult.imported.length} 个候选资料。`
          : `This writeback created ${records.length} DataRecords and imported ${selectedTeamRecordSourceCollectionOutputResult.imported.length} source_manifest candidates.`,
        status: outputRecord.status,
        tone: "storage",
        refs: records.slice(0, 4).map((record) => `${record.title || record.recordId} · ${record.sourceRef || record.rawLocation || sourceCollectionSourceTypeLabel(record.sourceType, lang)}`),
        storageRefs: [
          outputRecord.outputId,
          ...(selectedSourceCollectionRun?.storage ? [selectedSourceCollectionRun.storage.recordsPath, selectedSourceCollectionRun.storage.collectionOutputsPath] : []),
        ],
      });
    }
    sourceManifestCandidates.slice(0, 4).forEach((candidate) => {
      messages.push({
        id: `candidate-${candidate.candidateId}`,
        agentRole: candidate.createdByAgent || "Source Intake Agent",
        title: lang === "zh" ? "已进入候选资料仓库" : "Imported into candidate source store",
        body: candidate.summary || (lang === "zh" ? "该资料已作为候选保留，等待质量筛选或内容抽取。" : "This source is retained as a candidate for quality screening or extraction."),
        status: candidate.qualityStatus || candidate.currentState,
        tone: "storage",
        refs: [candidate.title || candidate.candidateId, candidate.currentState].filter(Boolean),
        storageRefs: [candidate.candidateId, teamWorkflow?.candidateStore.storagePath || ""].filter(Boolean),
      });
    });
    (teamWorkflowSourceQualityStatus?.candidates ?? []).slice(0, 3).forEach((candidate) => {
      if (!candidate.decision && candidate.bucket === "pending") {
        return;
      }
      messages.push({
        id: `quality-${candidate.candidateId}`,
        agentRole: "Source Quality Assessment Agent",
        title: lang === "zh" ? "已完成资料质量判断" : "Completed source quality decision",
        body: lang === "zh"
          ? `${candidate.title}：${workflowIngestionStatusLabel(candidate.decision || candidate.bucket, lang)}，综合分 ${candidate.overallScore || 0}/100。`
          : `${candidate.title}: ${workflowIngestionStatusLabel(candidate.decision || candidate.bucket, lang)}, overall ${candidate.overallScore || 0}/100.`,
        status: candidate.decision || candidate.bucket,
        tone: candidate.bucket === "rejected" ? "blocked" : "quality",
        refs: candidate.requiredFixes.length ? candidate.requiredFixes.slice(0, 3) : [candidate.sourceKind || "source_manifest"],
        storageRefs: [candidate.candidateId],
      });
    });
    return messages;
  }, [
    lang,
    selectedSourceCollectionRun,
    selectedSourceCollectionActiveWorkRun,
    selectedSourceCollectionStorageArtifacts,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamStartResearchStageResult,
    selectedTeamStartSourceCollectionResult,
    sourceCollectionAssignments,
    sourceCollectionAcceptedBackgroundActive,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceCollectionDraft.goal,
    sourceCollectionDraft.topic,
    sourceCollectionOpenAssignmentCount,
    sourceCollectionPromptCachePolicy,
    sourceCollectionPromptCachePolicyRef,
    sourceCollectionPromptCacheRequirement,
    sourceCollectionPromptCacheStatus,
    sourceCollectionSearchPlanRef,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionQueryCount,
    sourceCollectionRunSummary?.recordCount,
    sourceManifestCandidates,
    teamWorkflow?.candidateStore.storagePath,
    teamWorkflowSourceQualityStatus,
  ]);
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
    && sourceCollectionSearchOpenAssignmentCount > 0
    && !selectedTeamExecuteSourceCollectionSearchPending,
  );
  const selectedTeamBuildCandidateGraphPending =
    buildCandidateGraphMutation.isPending && buildCandidateGraphMutation.variables === selectedTeam?.teamId;
  const selectedTeamBuildCandidateGraphError =
    buildCandidateGraphMutation.variables === selectedTeam?.teamId && buildCandidateGraphMutation.error instanceof Error
      ? buildCandidateGraphMutation.error
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
  const sourceCollectionRecordCount = sourceCollectionRunSummary?.recordCount ?? 0;
  const sourceCollectionOperationActive = Boolean(
    selectedTeamStartResearchStagePending
    || selectedTeamStartSourceCollectionPending
    || selectedTeamExecuteSourceCollectionSearchPending
    || sourceCollectionAcceptedBackgroundActive
    || selectedTeamRecordSourceCollectionOutputPending
    || selectedTeamSourceQualityPending
    || selectedTeamBuildCandidateGraphPending,
  );
  const sourceCollectionOperationFailed = Boolean(
    sourceCollectionRunStatusValue === "failed"
    || sourceCollectionRunStatusValue === "blocked"
    || sourceCollectionAcceptedBackgroundFailed
    || selectedTeamStartResearchStageError
    || selectedTeamStartSourceCollectionError
    || selectedTeamExecuteSourceCollectionSearchError
    || selectedTeamRecordSourceCollectionOutputError
    || selectedTeamSourceQualityError
    || selectedTeamBuildCandidateGraphError,
  );
  const sourceQualityAssessedCount = teamWorkflowSourceQualityStatus?.summary.assessedSourceCandidateCount ?? 0;
  const sourceQualityCandidateCount = teamWorkflowSourceQualityStatus?.summary.sourceCandidateCount ?? sourceManifestCandidates.length;
  const sourceQualityUnassessedCount =
    teamWorkflowSourceQualityStatus?.summary.unassessedSourceCandidateCount
    ?? Math.max(0, sourceQualityCandidateCount - sourceQualityAssessedCount);
  const candidateGraphNodeCount = teamWorkflowCandidateGraph?.summary.nodeCount ?? 0;
  const candidateGraphEdgeCount = teamWorkflowCandidateGraph?.summary.edgeCount ?? 0;
  const knowledgePendingReviewCount = teamWorkflowKnowledgeIngestionStatus?.summary.pendingKnowledgeReviewCandidateCount ?? 0;
  const formalKnowledgeItemCount = teamWorkflowKnowledgeIngestionStatus?.summary.formalKnowledgeItemCount ?? 0;
  const sourceCollectionScreeningDisabled = !selectedTeam?.teamId || sourceQualityCandidateCount <= 0;
  const sourceCollectionScreeningButtonText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "Agent 筛选中" : "Agent screening")
    : sourceQualityUnassessedCount > 0
      ? (lang === "zh" ? "Agent 筛选资料" : "Agent screen")
      : sourceQualityCandidateCount > 0
        ? (lang === "zh" ? "Agent 重新筛选" : "Agent re-screen")
        : (lang === "zh" ? "资料筛选" : "Screening");
  const sourceCollectionScreeningStatusText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "进行中" : "running")
    : sourceQualityUnassessedCount > 0
      ? `${sourceQualityUnassessedCount} ${lang === "zh" ? "待筛" : "pending"}`
      : sourceQualityCandidateCount > 0
        ? (lang === "zh" ? "已筛选" : "done")
        : (lang === "zh" ? "暂无候选" : "no candidates");
  const sourceCollectionPanelClassName = (panelId: string) => [
    styles.workflowSourceCollectionDetails,
    sourceCollectionFocusedPanelId === panelId ? styles.sourceCollectionFocusedPanel : "",
  ].filter(Boolean).join(" ");
  const sourceCollectionStageForPanel = (panelId: string): SourceCollectionStageModuleId => {
    if (panelId === "source-collection-screening-panel") {
      return "screening";
    }
    if (panelId === "source-collection-candidates-panel") {
      return "candidate";
    }
    if (panelId === "source-collection-graph-panel") {
      return "graph";
    }
    if (panelId === "source-collection-memory-panel") {
      return "memory";
    }
    return "collection";
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
    selectSourceCollectionStage("screening");
    if (!selectedTeam?.teamId || sourceCollectionScreeningDisabled || selectedTeamSourceQualityPending) {
      return;
    }
    const forceRescreen = sourceQualityUnassessedCount <= 0 && sourceQualityCandidateCount > 0;
    const maxCandidates = forceRescreen ? sourceQualityCandidateCount : sourceQualityUnassessedCount;
    assessSourceQualityBatchMutation.mutate({
      teamId: selectedTeam.teamId,
      assessedByAgent: sourceCollectionQualityAgentId,
      maxCandidates: Math.max(1, Math.min(200, maxCandidates)),
      force: forceRescreen,
      notes: forceRescreen
        ? "Source Quality Assessment Agent re-screened already assessed source_manifest candidates on user request."
        : "Source Quality Assessment Agent screened pending source_manifest candidates.",
    });
  };
  const openSourceCollectionCandidatePanel = () => {
    if (!selectedTeam?.teamId) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-candidates-panel");
  };
  const refreshSourceCollectionGraph = () => {
    if (!selectedTeam?.teamId || sourceManifestCandidates.length <= 0 || selectedTeamBuildCandidateGraphPending) {
      return;
    }
    buildCandidateGraphMutation.mutate(selectedTeam.teamId);
    scrollSourceCollectionPanelIntoView("source-collection-graph-panel");
  };
  const refreshSourceCollectionMemoryPrecheck = () => {
    if (!selectedTeam?.teamId || teamWorkflowKnowledgeIngestionStatusQuery.isFetching) {
      return;
    }
    void teamWorkflowKnowledgeIngestionStatusQuery.refetch();
    scrollSourceCollectionPanelIntoView("source-collection-memory-panel");
  };
  const runSourceCollectionSearchFromHeader = () => {
    if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !canExecuteSourceCollectionSearch) {
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
    if (!selectedTeam?.teamId) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-process");
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
  const sourceCollectionConsoleState: SourceCollectionStepState = sourceCollectionOperationFailed
    ? "failed"
    : sourceCollectionOperationActive
      ? "active"
      : !selectedSourceCollectionRun
        ? "idle"
        : sourceCollectionSearchOpenAssignmentCount > 0 || sourceCollectionDownstreamOpenAssignmentCount > 0 || sourceManifestCandidates.length > sourceCollectionApprovedCount
          ? "pending"
          : sourceManifestCandidates.length > 0
            ? "done"
            : "pending";
  const sourceCollectionConsoleStatusText = selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
    ? (lang === "zh" ? "正在团队搜索" : "Team search running")
    : selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionPending
      ? (lang === "zh" ? "正在启动搜集" : "Starting collection")
      : selectedTeamRecordSourceCollectionOutputPending
        ? (lang === "zh" ? "正在写入候选" : "Writing candidates")
        : selectedTeamSourceQualityPending
          ? (lang === "zh" ? "正在筛选资料" : "Screening sources")
          : selectedTeamBuildCandidateGraphPending
            ? (lang === "zh" ? "正在刷新图谱" : "Refreshing graph")
            : sourceCollectionOperationFailed
              ? (lang === "zh" ? "处理失败" : "Failed")
              : !selectedSourceCollectionRun
                ? (lang === "zh" ? "未开始" : "Not started")
                : sourceCollectionSearchOpenAssignmentCount > 0
                  ? (lang === "zh" ? "需补充资料" : "More sources needed")
                  : sourceCollectionDownstreamOpenAssignmentCount > 0
                    ? (lang === "zh" ? "待提炼/筛选" : "Extraction or screening pending")
                  : sourceManifestCandidates.length > sourceCollectionApprovedCount
                    ? (lang === "zh" ? "待筛选资料" : "Needs screening")
                    : sourceManifestCandidates.length > 0
                      ? (lang === "zh" ? "可进入实验" : "Ready for experiment")
                      : (lang === "zh" ? "待回写" : "Waiting for writeback");
  const sourceCollectionDecisionText = (() => {
    if (sourceCollectionOperationFailed) {
      return lang === "zh" ? "处理失败，先查看下方失败步骤，再重试当前按钮。" : "A step failed. Review the failed step below, then retry its action.";
    }
    if (sourceCollectionOperationActive) {
      if (sourceCollectionAcceptedBackgroundActive) {
        return selectedSourceCollectionActiveWorkRun?.currentTask || selectedSourceCollectionActiveWorkRun?.summary || (lang === "zh" ? "后台资料搜集正在运行，完成后会刷新记录、候选和下一步状态。" : "Background source collection is running; records, candidates, and next state will refresh when it completes.");
      }
      return lang === "zh" ? "正在处理当前动作，完成后会刷新阶段颜色和结果数量。" : "Current action is running. Stage colors and counts update when it completes.";
    }
    if (!selectedSourceCollectionRun) {
      return lang === "zh" ? "点击开始搜集，生成本轮搜索任务和存储目录。" : "Start collection to create the search work and storage folder.";
    }
    if (sourceCollectionSearchOpenAssignmentCount > 0) {
      return lang === "zh"
        ? `还有 ${sourceCollectionSearchOpenAssignmentCount} 个搜索任务未完成，点击搜索下一批推进。`
        : `${sourceCollectionSearchOpenAssignmentCount} search assignments remain. Run the next search to proceed.`;
    }
    if (sourceCollectionDownstreamOpenAssignmentCount > 0) {
      return lang === "zh"
        ? `搜索已停止，还有 ${sourceCollectionDownstreamOpenAssignmentCount} 个后续任务等待提炼或筛选。`
        : `Search is idle; ${sourceCollectionDownstreamOpenAssignmentCount} downstream tasks wait for extraction or screening.`;
    }
    if (sourceManifestCandidates.length > sourceCollectionApprovedCount) {
      return lang === "zh"
        ? "候选资料已到位，下一步执行资料筛选。"
        : "Candidate sources are ready. Run screening next.";
    }
    if (sourceManifestCandidates.length > 0) {
      return lang === "zh"
        ? "资料链路已具备，可进入实验规划或继续补充资料。"
        : "The source chain is ready. Move to experiment planning or collect more.";
    }
    return lang === "zh" ? "等待 Agent 回写搜集结果。" : "Waiting for agent writeback.";
  })();
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
  const sourceCollectionStepClassName = (state: SourceCollectionStepState) => ({
    active: styles.sourceCollectionStepActive,
    done: styles.sourceCollectionStepDone,
    failed: styles.sourceCollectionStepFailed,
    idle: styles.sourceCollectionStepIdle,
    pending: styles.sourceCollectionStepPending,
  }[state]);
  const sourceCollectionSearchStepState: SourceCollectionStepState = sourceCollectionOperationFailed
    ? "failed"
    : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive || selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionPending
      ? "active"
      : !selectedSourceCollectionRun
        ? "idle"
        : sourceCollectionSearchOpenAssignmentCount > 0
          ? "pending"
          : sourceCollectionRecordCount || sourceManifestCandidates.length
            ? "done"
            : "pending";
  const sourceCollectionScreeningStepState: SourceCollectionStepState = selectedTeamSourceQualityError
    ? "failed"
    : selectedTeamSourceQualityPending
      ? "active"
      : sourceQualityAssessedCount > 0
        ? "done"
        : sourceManifestCandidates.length > 0 && sourceCollectionSearchOpenAssignmentCount <= 0
          ? "pending"
          : "idle";
  const sourceCollectionCandidateStepState: SourceCollectionStepState = selectedTeamRecordSourceCollectionOutputError
    ? "failed"
    : selectedTeamRecordSourceCollectionOutputPending
      ? "active"
      : sourceManifestCandidates.length > 0
        ? "done"
        : selectedSourceCollectionRun
          ? "pending"
          : "idle";
  const sourceCollectionGraphStepState: SourceCollectionStepState = selectedTeamBuildCandidateGraphError || teamWorkflowCandidateGraphQuery.error
    ? "failed"
    : selectedTeamBuildCandidateGraphPending || teamWorkflowCandidateGraphQuery.isFetching
      ? "active"
      : candidateGraphNodeCount > 0
        ? "done"
        : sourceManifestCandidates.length > 0
          ? "pending"
          : "idle";
  const sourceCollectionMemoryStepState: SourceCollectionStepState = teamWorkflowKnowledgeIngestionStatusQuery.error
    ? "failed"
    : teamWorkflowKnowledgeIngestionStatusQuery.isFetching
      ? "active"
      : formalKnowledgeItemCount > 0
        ? "done"
        : knowledgePendingReviewCount > 0 || sourceCollectionApprovedCount > 0
          ? "pending"
          : "idle";
  const sourceCollectionCollectionActionLabel = !selectedSourceCollectionRun
    ? (lang === "zh" ? "开始搜集" : "Start")
    : selectedTeamExecuteSourceCollectionSearchPending
      ? (lang === "zh" ? "搜索中" : "Searching")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? "搜索下一批" : "Search next")
      : (lang === "zh" ? "新一轮搜集" : "New round");
  const sourceCollectionCollectionActionDisabled = !selectedSourceCollectionRun
    ? selectedTeamStartResearchStagePending || !researchStageCanLaunch
    : sourceCollectionSearchOpenAssignmentCount > 0
      ? !canExecuteSourceCollectionSearch
      : selectedTeamStartResearchStagePending || !researchStageCanLaunch;
  const sourceCollectionStageModules: SourceCollectionStageModule[] = [
    {
      id: "collection",
      label: lang === "zh" ? "资料搜集" : "Collection",
      metric: lang === "zh" ? `已搜到 ${sourceCollectionCollectedCount} 条` : `${sourceCollectionCollectedCount} collected`,
      summary: !selectedSourceCollectionRun
        ? (lang === "zh" ? "点击开始生成本轮任务" : "Start to create this run")
        : sourceCollectionSearchOpenAssignmentCount > 0
          ? (lang === "zh" ? `${sourceCollectionSearchOpenAssignmentCount} 个搜索任务待执行` : `${sourceCollectionSearchOpenAssignmentCount} search tasks remain`)
          : (lang === "zh" ? `${sourceCollectionQueryCount} 个搜索问题已处理` : `${sourceCollectionQueryCount} search questions handled`),
      state: sourceCollectionSearchStepState,
      status: sourceCollectionStepStatusText(sourceCollectionSearchStepState),
      detailLabel: lang === "zh" ? "查看搜集过程" : "View collection process",
      actionLabel: sourceCollectionCollectionActionLabel,
      actionDisabled: sourceCollectionCollectionActionDisabled,
      actionTone: "primary",
      actionIcon: selectedSourceCollectionRun && sourceCollectionSearchOpenAssignmentCount > 0 ? "search" : "play",
      onAction: runSourceCollectionCollectionAction,
      onDetail: () => scrollSourceCollectionPanelIntoView("source-collection-process"),
    },
    {
      id: "screening",
      label: lang === "zh" ? "资料筛选" : "Screening",
      metric: lang === "zh" ? `已筛 ${sourceQualityAssessedCount}/${sourceQualityCandidateCount}` : `${sourceQualityAssessedCount}/${sourceQualityCandidateCount} screened`,
      summary: sourceQualityCandidateCount <= 0
        ? (lang === "zh" ? "先完成资料搜集" : "Collect sources first")
        : sourceQualityUnassessedCount > 0
          ? (lang === "zh" ? `${sourceQualityUnassessedCount} 条等待 Agent 审查` : `${sourceQualityUnassessedCount} wait for agent review`)
          : (lang === "zh" ? `${sourceCollectionApprovedCount} 条已通过` : `${sourceCollectionApprovedCount} approved`),
      state: sourceCollectionScreeningStepState,
      status: sourceCollectionStepStatusText(sourceCollectionScreeningStepState),
      detailLabel: lang === "zh" ? "查看筛选详情" : "View screening details",
      actionLabel: sourceCollectionScreeningButtonText,
      actionDisabled: sourceCollectionScreeningDisabled || selectedTeamSourceQualityPending,
      actionTone: "primary",
      actionIcon: "check",
      onAction: runSourceCollectionScreeningAction,
      onDetail: () => scrollSourceCollectionPanelIntoView("source-collection-screening-panel"),
    },
    {
      id: "candidate",
      label: lang === "zh" ? "候选入库" : "Candidates",
      metric: lang === "zh" ? `候选资料 ${sourceManifestCandidates.length} 条` : `${sourceManifestCandidates.length} candidates`,
      summary: sourceManifestCandidates.length > 0
        ? (lang === "zh" ? "候选库可视化查看" : "Open the visual library")
        : (lang === "zh" ? "等待资料入候选" : "Waiting for candidates"),
      state: sourceCollectionCandidateStepState,
      status: sourceCollectionStepStatusText(sourceCollectionCandidateStepState),
      detailLabel: lang === "zh" ? "查看候选库" : "View candidate library",
      actionLabel: lang === "zh" ? "查看候选库" : "View library",
      actionDisabled: !selectedTeam?.teamId,
      actionTone: "secondary",
      actionIcon: "archive",
      onAction: openSourceCollectionCandidatePanel,
      onDetail: openSourceCollectionCandidatePanel,
    },
    {
      id: "graph",
      label: lang === "zh" ? "候选图谱" : "Graph",
      metric: lang === "zh" ? `节点 ${candidateGraphNodeCount} · 关系 ${candidateGraphEdgeCount}` : `${candidateGraphNodeCount} nodes · ${candidateGraphEdgeCount} edges`,
      summary: candidateGraphNodeCount > 0
        ? (lang === "zh" ? "关系快照已生成" : "Graph snapshot ready")
        : sourceManifestCandidates.length > 0
          ? (lang === "zh" ? "可生成候选关系" : "Can build candidate links")
          : (lang === "zh" ? "先有候选资料" : "Needs candidates first"),
      state: sourceCollectionGraphStepState,
      status: sourceCollectionStepStatusText(sourceCollectionGraphStepState),
      detailLabel: lang === "zh" ? "查看图谱详情" : "View graph details",
      actionLabel: selectedTeamBuildCandidateGraphPending ? (lang === "zh" ? "生成中" : "Building") : (lang === "zh" ? "刷新图谱" : "Refresh"),
      actionDisabled: !selectedTeam?.teamId || sourceManifestCandidates.length <= 0 || selectedTeamBuildCandidateGraphPending,
      actionTone: "secondary",
      actionIcon: "refresh",
      onAction: refreshSourceCollectionGraph,
      onDetail: () => scrollSourceCollectionPanelIntoView("source-collection-graph-panel"),
    },
    {
      id: "memory",
      label: lang === "zh" ? "共享记忆前审" : "Memory precheck",
      metric: lang === "zh" ? `待审 ${knowledgePendingReviewCount} · 正式 ${formalKnowledgeItemCount}` : `${knowledgePendingReviewCount} review · ${formalKnowledgeItemCount} formal`,
      summary: formalKnowledgeItemCount > 0
        ? (lang === "zh" ? "正式知识已同步" : "Formal knowledge synced")
        : knowledgePendingReviewCount > 0
          ? (lang === "zh" ? "有待审入库对象" : "Review items pending")
          : sourceCollectionApprovedCount > 0
            ? (lang === "zh" ? "可检查入库门槛" : "Ready to check the gate")
            : (lang === "zh" ? "等筛选通过后前审" : "Precheck after approval"),
      state: sourceCollectionMemoryStepState,
      status: sourceCollectionStepStatusText(sourceCollectionMemoryStepState),
      detailLabel: lang === "zh" ? "查看前审详情" : "View precheck details",
      actionLabel: teamWorkflowKnowledgeIngestionStatusQuery.isFetching ? (lang === "zh" ? "检查中" : "Checking") : (lang === "zh" ? "检查前审" : "Check"),
      actionDisabled: !selectedTeam?.teamId || teamWorkflowKnowledgeIngestionStatusQuery.isFetching,
      actionTone: "secondary",
      actionIcon: "refresh",
      onAction: refreshSourceCollectionMemoryPrecheck,
      onDetail: () => scrollSourceCollectionPanelIntoView("source-collection-memory-panel"),
    },
  ];
  const sourceCollectionStageCardKeyDown = (
    event: ReactKeyboardEvent<HTMLElement>,
    onDetail: () => void,
  ) => {
    if (event.target instanceof Element && event.target.closest("button")) {
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    onDetail();
  };
  const renderSourceCollectionStageActionIcon = (icon: SourceCollectionStageModule["actionIcon"]) => {
    if (icon === "search") {
      return <Search size={13} />;
    }
    if (icon === "check") {
      return <CheckCircle2 size={13} />;
    }
    if (icon === "archive") {
      return <Archive size={13} />;
    }
    if (icon === "refresh") {
      return <RefreshCw size={13} />;
    }
    return <Play size={13} />;
  };
  const activeWorkflowItemCount = teamWorkflow?.activeWorkflowItems.length ?? 0;
  const researchCanvasVisible = researchWorkflowTeamSelected && researchWorkspaceView === "canvas";
  const workspaceClassName = [
    hasTeams ? styles.workspace : `${styles.workspace} ${styles.workspaceEmpty}`,
    researchWorkflowTeamSelected ? styles.workspaceResearch : "",
    researchCanvasVisible ? styles.workspaceResearchCanvas : "",
  ].filter(Boolean).join(" ");
  const canvasPanelClassName = [
    styles.canvasPanel,
    researchWorkflowTeamSelected && !researchCanvasVisible ? styles.researchCanvasPanelHidden : "",
  ].filter(Boolean).join(" ");
  const inspectorClassName = [
    styles.inspector,
    researchWorkflowTeamSelected ? styles.researchInspector : "",
  ].filter(Boolean).join(" ");
  const showNodeBindingPanel = !researchWorkflowTeamSelected || researchCanvasVisible;
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

  if (sourceCollectionStandalone) {
    return (
      <section className={`${styles.route} ${styles.sourceCollectionPage}`}>
        <header className={`${styles.header} ${styles.sourceCollectionPageHeader}`}>
          <div className={styles.sourceCollectionPageTitleBlock}>
            <p>{lang === "zh" ? "ai科学研究团队 / 知识搜集阶段" : "AI research team / knowledge collection stage"}</p>
            <div className={styles.sourceCollectionPageTitleLine}>
              <h1>{lang === "zh" ? "知识搜集工作台" : "Knowledge collection workspace"}</h1>
              <span className={`${styles.sourceCollectionRunBadge} ${sourceCollectionStepClassName(sourceCollectionConsoleState)}`}>
                {sourceCollectionConsoleStatusText}
              </span>
            </div>
          </div>
          <div className={styles.sourceCollectionPageActions}>
            <Link to={teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)}>
              <ArrowLeft size={14} />
              {lang === "zh" ? "返回团队页面" : "Back to team"}
            </Link>
            <button type="button" onClick={() => void sourceCollectionRunsQuery.refetch()} disabled={sourceCollectionRunsQuery.isFetching}>
              <RefreshCw size={14} />
              {lang === "zh" ? "刷新" : "Refresh"}
            </button>
          </div>
        </header>
        {researchWorkflowTeamSelected ? (
          <main className={styles.sourceCollectionPageBody}>
            <section className={`${styles.sourceCollectionCommandBar} ${sourceCollectionStepClassName(sourceCollectionConsoleState)}`} aria-label={lang === "zh" ? "知识搜集操作台" : "Knowledge collection command bar"}>
              <div className={styles.sourceCollectionCommandTitle}>
                <strong>{sourceCollectionRunTitleLabel(selectedSourceCollectionRun?.title || sourceCollectionDraft.title, lang)}</strong>
                <span>{sourceCollectionDecisionText}</span>
              </div>
              <div className={styles.sourceCollectionCommandStats}>
                <span>{lang === "zh" ? "下一步" : "next"} <strong>{sourceCollectionStageFocusLabel}</strong></span>
                <span>{lang === "zh" ? "可搜索" : "search"} <strong>{lang === "zh" ? `${sourceCollectionSearchOpenAssignmentCount} 项` : sourceCollectionSearchOpenAssignmentCount}</strong></span>
                <span>{lang === "zh" ? "后续" : "next work"} <strong>{lang === "zh" ? `${sourceCollectionDownstreamOpenAssignmentCount} 项` : sourceCollectionDownstreamOpenAssignmentCount}</strong></span>
                <span>{lang === "zh" ? "搜集结果" : "results"} <strong>{lang === "zh" ? `${sourceCollectionCollectedCount} 条` : sourceCollectionCollectedCount}</strong></span>
                <span>{lang === "zh" ? "搜索问题" : "search questions"} <strong>{lang === "zh" ? `${sourceCollectionQueryCount} 个` : sourceCollectionQueryCount}</strong></span>
                <span>{lang === "zh" ? "缓存" : "cache"} <strong>{sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}</strong></span>
              </div>
            </section>
            <section id="source-collection-stage-status" className={styles.sourceCollectionStageModules} aria-label={lang === "zh" ? "知识搜集内部模块" : "Knowledge collection modules"}>
              {sourceCollectionStageModules.map((module, index) => (
                <article
                  key={module.id}
                  className={[
                    styles.sourceCollectionStageCard,
                    sourceCollectionStepClassName(module.state),
                    module.id === selectedSourceCollectionStageId ? styles.sourceCollectionStageCardSelected : "",
                  ].filter(Boolean).join(" ")}
                  role="button"
                  tabIndex={0}
                  aria-pressed={module.id === selectedSourceCollectionStageId}
                  title={module.detailLabel}
                  onClick={(event) => {
                    if (event.target instanceof Element && event.target.closest("button, a")) {
                      return;
                    }
                    module.onDetail();
                  }}
                  onKeyDown={(event) => sourceCollectionStageCardKeyDown(event, module.onDetail)}
                >
                  <div className={styles.sourceCollectionStageCardHead}>
                    <strong>{String(index + 1).padStart(2, "0")}</strong>
                    <span>{module.status}</span>
                  </div>
                  <span className={styles.sourceCollectionStageModuleText}>
                    <b>{module.label}</b>
                    <em>{module.metric}</em>
                    <small>{module.summary}</small>
                  </span>
                  <div className={styles.sourceCollectionStageActionRow}>
                    <button
                      type="button"
                      className={module.actionTone === "primary" ? styles.sourceCollectionStagePrimaryAction : styles.sourceCollectionStageSecondaryAction}
                      disabled={module.actionDisabled}
                      onClick={module.onAction}
                      title={module.actionLabel}
                    >
                      {renderSourceCollectionStageActionIcon(module.actionIcon)}
                      {module.actionLabel}
                    </button>
                  </div>
                </article>
              ))}
            </section>
            <div className={styles.sourceCollectionPageGrid}>
              {renderSourceCollectionActiveStagePanel()}
              {renderSourceCollectionControlsPanel()}
            </div>
          </main>
        ) : (
          <main className={styles.sourceCollectionPageBody}>
            <section className={styles.sourceCollectionUnavailable}>
              <strong>{lang === "zh" ? "正在读取 ai科学研究团队" : "Loading AI research team"}</strong>
              <span>
                {teamDetailQuery.error instanceof Error
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
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p>{lang === "zh" ? "团队工作台 / 组织画布" : "Team Workspace / Canvas"}</p>
          <h1>{lang === "zh" ? "团队组织画布" : "Team Organization Canvas"}</h1>
        </div>
        <button type="button" className={styles.iconButton} onClick={() => teamsQuery.refetch()} title={lang === "zh" ? "刷新" : "Refresh"}>
          <RefreshCw size={15} />
        </button>
      </header>

      <div className={styles.summaryBar}>
        <span>{lang === "zh" ? "团队" : "Teams"} <strong>{visibleTeamSummary.activeTeamCount}</strong></span>
        <span>{lang === "zh" ? "成员引用" : "Members"} <strong>{visibleTeamSummary.memberCount}</strong></span>
        <span>{lang === "zh" ? "失效引用" : "Stale"} <strong>{visibleTeamSummary.staleMemberCount}</strong></span>
        <span>{lang === "zh" ? "成员源" : "Member source"} <strong>Agent Center</strong></span>
      </div>
      <section className={`${styles.teamPickerPanel} ${styles.teamSwitcherBar}`}>
        <label className={styles.teamPickerLabel}>
          <span>{lang === "zh" ? "团队" : "Team"}</span>
          <select
            value={selectedTeam?.teamId ?? effectiveTeamId}
            onChange={(event) => {
              const nextTeam = visibleTeams.find((team) => team.teamId === event.target.value);
              if (nextTeam) {
                selectTeamRecord(nextTeam);
              }
            }}
            disabled={!visibleTeams.length}
            aria-label={lang === "zh" ? "选择团队" : "Select team"}
          >
            {visibleTeams.length ? (
              visibleTeams.map((team) => (
                <option key={team.teamId} value={team.teamId}>
                  {team.name}
                </option>
              ))
            ) : (
              <option value="">{lang === "zh" ? "正在读取团队" : "Loading teams"}</option>
            )}
          </select>
        </label>
        <div className={styles.teamPickerSummary}>
          <strong>{selectedTeam?.name ?? (lang === "zh" ? "等待团队载入" : "Waiting for team")}</strong>
          <span>{selectedTeam?.purpose || selectedTeam?.teamId || (lang === "zh" ? "仅显示科研与搜索两个团队入口。" : "Only research and search teams are shown.")}</span>
          {selectedTeam ? (
            <small>{selectedTeam.memberCount} agents · {formatTime(selectedTeam.updatedAt, lang)}</small>
          ) : null}
        </div>
      </section>
      <div className={workspaceClassName}>
        <main className={canvasPanelClassName} id="research-organization-canvas">
          <div className={styles.canvasToolbar}>
            <div>
              <strong>{selectedTeam?.name ?? (lang === "zh" ? "暂无团队" : "No team")}</strong>
              <span>{canvas ? `${canvas.path} · ${TEAM_ORGANIZATION_CANVAS_KIND}` : "workspace/teams"}</span>
              {canvas ? (
                <small className={styles.edgeLayerLine}>
                  {lang === "zh" ? "组织线" : "Org lines"} {organizationEdges.length}
                  {" · "}
                  {lang === "zh" ? "信息线" : "Info lines"} {communicationEdges.length}
                  {" · "}
                  {communicationEdgeHint}
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
                  {conversationProjection?.status === "agent_missing"
                    ? (lang === "zh" ? `成员缺失 ${conversationProjection.missingAgentCount} 个，请先修复 Agent 引用。` : `${conversationProjection.missingAgentCount} missing agents. Repair Agent references first.`)
                    : activeTeamMemberCount > 0
                    ? (lang === "zh" ? "尚未衔接群聊，可同步创建。" : "No linked room yet. Sync to create one.")
                    : (lang === "zh" ? "绑定 active Agent 后可衔接群聊。" : "Bind active agents before linking a room.")}
                </small>
              ) : null}
            </div>
            <div className={styles.toolbarActions}>
              {saveLabel ? <span className={styles.saveState}>{saveLabel}</span> : null}
              <button
                type="button"
                className={showCommunicationEdges ? styles.layerButtonActive : ""}
                onClick={() => setShowCommunicationEdges((current) => !current)}
                disabled={!canvas || communicationEdges.length === 0}
                title={communicationEdgeHint}
              >
                <Link2 size={14} />
                {communicationEdgeButtonLabel}
              </button>
              {linkedChatRoomId ? (
                <Link className={styles.toolbarLink} to={`/chat?room=${encodeURIComponent(linkedChatRoomId)}`}>
                  {lang === "zh" ? "打开群聊" : "Open room"}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
                  disabled={!selectedTeam || activeTeamMemberCount === 0 || selectedTeamSyncPending}
                >
                  <Link2 size={14} />
                  {selectedTeamSyncPending
                    ? (lang === "zh" ? "同步中" : "Syncing")
                    : (lang === "zh" ? "同步群聊" : "Sync room")}
                </button>
              )}
              <button type="button" onClick={addNode} disabled={!canvas}>
                <Plus size={14} />
                {lang === "zh" ? "节点" : "Node"}
              </button>
              <button
                type="button"
                className={styles.dangerButton}
                onClick={() => selectedTeam?.teamId && archiveTeamMutation.mutate(selectedTeam.teamId)}
                disabled={!selectedTeam || selectedTeamArchivePending}
              >
                <Archive size={14} />
                {lang === "zh" ? "归档" : "Archive"}
              </button>
            </div>
          </div>
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
                    const line = edgeLine(edge, canvasNodes, visibleEdges);
                    return line ? (
                      <path
                        key={edge.id}
                        className={isCommunicationEdge(edge) ? styles.edgeCommunication : styles.edgeOrganization}
                        d={`M ${line.x1} ${line.y1} Q ${line.cx} ${line.cy} ${line.x2} ${line.y2}`}
                      />
                    ) : null;
                  })}
                </svg>
                {canvasNodes.map((node) => {
                  const agent = activeAgents.find((item) => item.agentId === node.agentId);
                  const display = agent ? agentDisplayInfo(agent, lang) : null;
                  const functionLabel = teamNodeFunctionLabel(node, display?.functionLabel, lang);
                  return (
                    <button
                      key={node.id}
                      type="button"
                      className={`${styles.node} ${nodeTone(node)} ${selectedNode?.id === node.id ? styles.nodeActive : ""}`}
                      style={{ "--node-x": `${node.x}px`, "--node-y": `${node.y}px` } as NodePositionStyle}
                      title={lang === "zh" ? "拖动调整节点位置" : "Drag to reposition"}
                      onPointerDown={(event) => startNodeDrag(event, node)}
                      onPointerMove={moveNodeDrag}
                      onPointerUp={finishNodeDrag}
                      onPointerCancel={finishNodeDrag}
                      onClick={() => setSelectedNodeId(node.id)}
                    >
                      <span className={styles.nodeIcon}>{node.agentId ? <Bot size={15} /> : <Users size={15} />}</span>
                      <strong>{node.label}</strong>
                      <span className={`${styles.nodeRoleBadge} ${roleBadgeTone(node, display?.tone)}`}>{functionLabel}</span>
                      <small>{node.agentCode || node.status}</small>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className={styles.emptyCanvasPanel} ref={canvasFrameRef}>
              <div className={styles.emptyCanvasContent}>
                <span className={styles.emptyCanvasKicker}>{lang === "zh" ? "团队入口" : "Team entry"}</span>
                <strong>{lang === "zh" ? "选择团队后进入对应工作区" : "Select a team to open its workspace"}</strong>
                <p>
                  {lang === "zh"
                    ? "顶部只保留 AI 搜索范围团队和 ai科学研究团队两个入口；选择后这里会显示对应团队内容。"
                    : "The top selector only exposes the AI search scope team and the AI research team; selecting one opens its workspace."}
                </p>
                <div className={styles.emptyCanvasSteps}>
                  <span>{lang === "zh" ? "1 选择团队" : "1 Select team"}</span>
                  <span>{lang === "zh" ? "2 打开页面" : "2 Open page"}</span>
                  <span>{lang === "zh" ? "3 审核流程" : "3 Review workflow"}</span>
                </div>
              </div>
            </div>
          )}
        </main>

        <aside className={inspectorClassName}>
          <div className={styles.inspectorHeader}>
            <strong>
              {researchWorkflowTeamSelected && !researchCanvasVisible
                ? `${lang === "zh" ? "ai科学研究团队" : "AI research team"} · ${researchWorkspaceViewLabel(researchWorkspaceView, lang)}`
                : (lang === "zh" ? "节点绑定" : "Node binding")}
            </strong>
            {validation && !validation.valid ? <AlertTriangle size={16} /> : <Link2 size={16} />}
          </div>
          <div className={styles.inspectorBody}>
            {researchWorkflowTeamSelected && !researchCanvasVisible ? (
              <>
                {renderResearchStageLauncher()}
              </>
            ) : null}
            {showNodeBindingPanel && !selectedTeam ? (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`}>
                <div className={styles.empty}>
                  {lang === "zh"
                    ? "暂无可用团队。请确认 AI 搜索范围团队和 ai科学研究团队已初始化。"
                    : "No available team. Confirm the AI search scope team and AI research team are initialized."}
                </div>
              </section>
            ) : showNodeBindingPanel && selectedNode ? (
              <section className={styles.nodeBindingSection}>
              <label>
                <span>{lang === "zh" ? "节点名称" : "Node label"}</span>
                <input value={nodeDraft.label} onChange={(event) => setNodeDraft((current) => ({ ...current, label: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "组织角色" : "Role"}</span>
                <input value={nodeDraft.role} onChange={(event) => setNodeDraft((current) => ({ ...current, role: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "绑定 Agent" : "Bound Agent"}</span>
                <select value={nodeDraft.agentId} onChange={(event) => setNodeDraft((current) => ({ ...current, agentId: event.target.value }))}>
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
                </select>
              </label>
              <label>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <textarea value={nodeDraft.purpose} onChange={(event) => setNodeDraft((current) => ({ ...current, purpose: event.target.value }))} />
              </label>
              <div className={styles.actionRow}>
                <button type="button" onClick={applyNodeDraft} disabled={!canvas || selectedTeamSaveCanvasPending}>
                  <Save size={14} />
                  {lang === "zh" ? "保存节点" : "Save node"}
                </button>
                <button type="button" onClick={connectFromLead} disabled={!canvas || !selectedNode || canvas.nodes[0]?.id === selectedNode.id}>
                  <Link2 size={14} />
                  {lang === "zh" ? "接入主干" : "Connect"}
                </button>
                <button type="button" onClick={unbindSelectedNode} disabled={!canvas || !selectedNode?.agentId || selectedTeamSaveCanvasPending}>
                  <Unlink size={14} />
                  {lang === "zh" ? "解绑节点" : "Unbind"}
                </button>
                <button
                  type="button"
                  className={styles.dangerButton}
                  onClick={deleteSelectedNode}
                  disabled={!canvas || !selectedNode || canvas.nodes.length <= 1 || selectedTeamSaveCanvasPending}
                >
                  <Trash2 size={14} />
                  {lang === "zh" ? "删除节点" : "Delete"}
                </button>
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
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`} aria-busy={teamDetailQuery.isPending || workspaceQuery.isPending}>
                <div className={styles.empty}>
                  {teamDetailQuery.isPending || workspaceQuery.isPending
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
                          <div className={styles.workflowModelEvidencePanel}>
                            <div className={styles.workflowIngestionHeader}>
                              <div>
                                <strong>{lang === "zh" ? "模型调用证据链" : "Model evidence chain"}</strong>
                                <span>
                                  {teamWorkflowOfficialModelEvidenceStatus
                                    ? `${teamWorkflowOfficialModelEvidenceStatus.summary.coveredNodeCount}/${teamWorkflowOfficialModelEvidenceStatus.summary.requiredNodeCount} nodes · ${teamWorkflowOfficialModelEvidenceStatus.summary.evidenceCount} evidence`
                                    : teamWorkflowOfficialModelEvidenceStatusQuery.isPending
                                    ? (lang === "zh" ? "读取中" : "loading")
                                    : (lang === "zh" ? "等待模型证据" : "waiting for model evidence")}
                                </span>
                              </div>
                              <span className={`${styles.workflowTag} ${workflowIngestionTone(teamWorkflowOfficialModelEvidenceStatus?.status || "")}`}>
                                {teamWorkflowOfficialModelEvidenceStatus
                                  ? workflowIngestionStatusLabel(teamWorkflowOfficialModelEvidenceStatus.status, lang)
                                  : (lang === "zh" ? "未读取" : "not loaded")}
                              </span>
                            </div>
                            {teamWorkflowOfficialModelEvidenceStatus ? (
                              <>
                                <div className={styles.workflowModelEvidenceStats}>
                                  <span>Qwen <strong>{teamWorkflowOfficialModelEvidenceStatus.summary.qwenEvidenceCount}</strong></span>
                                  <span>{lang === "zh" ? "百炼" : "Bailian"} <strong>{teamWorkflowOfficialModelEvidenceStatus.summary.bailianEvidenceCount}</strong></span>
                                  <span>{lang === "zh" ? "本地" : "local"} <strong>{teamWorkflowOfficialModelEvidenceStatus.summary.localEvidenceCount}</strong></span>
                                  <span>{lang === "zh" ? "候选关联" : "linked"} <strong>{teamWorkflowOfficialModelEvidenceStatus.summary.linkedCandidateCount}</strong></span>
                                </div>
                                <div className={styles.workflowModelEvidenceCoverage}>
                                  {teamWorkflowOfficialModelEvidenceStatus.coverage.map((item) => (
                                    <span key={item.taskType} className={`${styles.workflowIngestionStage} ${workflowIngestionTone(item.status === "covered" ? "ready" : "needs_evidence")}`}>
                                      <strong>{item.label}</strong>
                                      <small>{item.evidenceCount} · {item.status}</small>
                                    </span>
                                  ))}
                                </div>
                                {teamWorkflowOfficialModelEvidenceStatus.actionItems.length ? (
                                  <div className={styles.workflowIngestionActions}>
                                    {teamWorkflowOfficialModelEvidenceStatus.actionItems.slice(0, 3).map((item) => (
                                      <span key={`${item.code}-${item.taskType}`} className={workflowIngestionTone(item.severity)}>
                                        {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                                <div className={styles.workflowIngestionBoundary}>
                                  <span>{lang === "zh" ? "证据登记，不是正式知识" : "Evidence only, not formal knowledge"}</span>
                                  <span>
                                    {teamWorkflowOfficialModelEvidenceStatus.officialBoundary.writesFormalKnowledge
                                      ? (lang === "zh" ? "会写正式知识" : "writes formal knowledge")
                                      : (lang === "zh" ? "正式知识写入关闭" : "formal write off")}
                                  </span>
                                  <span>{teamWorkflowOfficialModelEvidenceStatus.storage.evidenceStorePath}</span>
                                </div>
                              </>
                            ) : (
                              <div className={styles.empty}>
                                {teamWorkflowOfficialModelEvidenceStatusQuery.isPending
                                  ? (lang === "zh" ? "正在读取 Qwen/百炼/本地模型调用证据覆盖..." : "Loading Qwen/Bailian/local model evidence coverage...")
                                  : (lang === "zh" ? "暂无模型调用证据。" : "No model evidence yet.")}
                              </div>
                            )}
                            {teamWorkflowOfficialModelEvidenceStatusQuery.error instanceof Error ? (
                              <div className={styles.messageError}>{teamWorkflowOfficialModelEvidenceStatusQuery.error.message}</div>
                            ) : null}
                          </div>
                        </>
                      ) : null}
                      {showResearchSourceCollection ? (
                      <div className={styles.workflowSourceCollectionPanel} id="research-workflow-source-collection">
                        <div className={styles.workflowIngestionHeader}>
                          <div>
                            <strong>{lang === "zh" ? "资料搜集执行" : "Source collection"}</strong>
                            <span>
                              {selectedSourceCollectionRun
                                ? lang === "zh"
                                  ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionRunSummary?.recordCount ?? 0} 条资料 / ${sourceCollectionAssignments.length} 个任务`
                                  : `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionRunSummary?.recordCount ?? 0} records / ${sourceCollectionAssignments.length} assignments`
                                : sourceCollectionRunsQuery.isPending
                                ? (lang === "zh" ? "读取批次中" : "loading runs")
                                : (lang === "zh" ? "等待启动批次" : "waiting for run")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}`}>
                            {sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || (lang === "zh" ? "未启动" : "not started")}
                          </span>
                        </div>
                        <form
                          className={styles.workflowSourceCollectionForm}
                          onSubmit={(event) => {
                            event.preventDefault();
                            if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
                              return;
                            }
                            startSourceCollectionRunMutation.mutate({
                              teamId: selectedTeam.teamId,
                              draft: sourceCollectionDraft,
                            });
                          }}
                        >
                          <label>
                            <span>{lang === "zh" ? "主题" : "Topic"}</span>
                            <input
                              value={sourceCollectionDraft.topic}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, topic: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "标题" : "Title"}</span>
                            <input
                              value={sourceCollectionDraft.title}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, title: event.target.value }))}
                            />
                          </label>
                          <label className={styles.workflowSourceCollectionWide}>
                            <span>{lang === "zh" ? "目标" : "Goal"}</span>
                            <textarea
                              value={sourceCollectionDraft.goal}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, goal: event.target.value }))}
                              rows={2}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "Query seeds" : "Query seeds"}</span>
                            <textarea
                              value={sourceCollectionDraft.querySeeds}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, querySeeds: event.target.value }))}
                              rows={3}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "输入引用" : "Input refs"}</span>
                            <textarea
                              value={sourceCollectionDraft.inputRefs}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, inputRefs: event.target.value }))}
                              rows={3}
                              placeholder={lang === "zh" ? "可选：本地文件、seed-query:..." : "Optional: local file, seed-query:..."}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "语言" : "Languages"}</span>
                            <input
                              value={sourceCollectionDraft.searchLanguages}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, searchLanguages: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "资料类型" : "Source types"}</span>
                            <input
                              value={sourceCollectionDraft.sourceTypes}
                              onChange={(event) => setSourceCollectionDraft((current) => ({ ...current, sourceTypes: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "每条上限" : "Max results"}</span>
                            <input
                              type="number"
                              min={1}
                              max={100}
                              value={sourceCollectionDraft.maxResultsPerQuery}
                              onChange={(event) =>
                                setSourceCollectionDraft((current) => ({
                                  ...current,
                                  maxResultsPerQuery: Math.max(1, Math.min(100, Number(event.target.value) || 1)),
                                }))
                              }
                            />
                          </label>
                          <button type="submit" disabled={!sourceCollectionCanStart || selectedTeamStartSourceCollectionPending}>
                            <Search size={13} />
                            {selectedTeamStartSourceCollectionPending
                              ? (lang === "zh" ? "启动中" : "Starting")
                              : (lang === "zh" ? "启动搜集批次" : "Start collection")}
                          </button>
                        </form>
                        <div className={styles.workflowSourceCollectionRuns}>
                          <label>
                            <span>{lang === "zh" ? "最近批次" : "Recent runs"}</span>
                            <select
                              value={selectedSourceCollectionRunEffectiveId}
                              onChange={(event) => setSelectedSourceCollectionRunId(event.target.value)}
                              disabled={!sourceCollectionRuns.length}
                            >
                              {sourceCollectionRuns.length ? (
                                sourceCollectionRuns.map((run) => (
                                  <option key={run.runId} value={run.runId}>
                                    {sourceCollectionRunLabel(run.runId)} · {run.title}
                                  </option>
                                ))
                              ) : (
                                <option value="">{lang === "zh" ? "暂无批次" : "No runs"}</option>
                              )}
                            </select>
                          </label>
                          <div className={styles.workflowSourceCollectionStats}>
                            <span>{lang === "zh" ? "资料" : "records"} <strong>{sourceCollectionRunSummary?.recordCount ?? 0}</strong></span>
                            <span>{lang === "zh" ? "可搜索" : "search"} <strong>{sourceCollectionSearchOpenAssignmentCount}</strong></span>
                            <span>{lang === "zh" ? "后续" : "next work"} <strong>{sourceCollectionDownstreamOpenAssignmentCount}</strong></span>
                            <span>{lang === "zh" ? "搜索问题" : "queries"} <strong>{sourceCollectionSearchPlanRef?.queryCount ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount ?? 0}</strong></span>
                            <span>KV <strong>{sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}{sourceCollectionPromptCacheMode ? ` · ${sourceCollectionPromptCacheMode}` : ""}</strong></span>
                          </div>
                        </div>
                        {renderSourceCollectionStorageActions()}
                        {selectedTeamStartSourceCollectionResult ? (
                          <div className={styles.workflowSourceCollectionPlan}>
                            <div>
                              <span>plan</span>
                              <strong>{selectedTeamStartSourceCollectionResult.searchPlan.planId}</strong>
                            </div>
                            <div>
                              <span>{lang === "zh" ? "seeds" : "seeds"}</span>
                              <strong>{selectedTeamStartSourceCollectionResult.searchPlan.querySeeds.join(" / ")}</strong>
                            </div>
                            <div>
                              <span>KV</span>
                              <strong>
                                {sourceCollectionPromptCacheStatusLabel(selectedTeamStartSourceCollectionResult.promptCachePolicy.gate.status, lang)}
                                {" · "}
                                {selectedTeamStartSourceCollectionResult.promptCachePolicy.promptCacheMode}
                              </strong>
                            </div>
                            <div>
                              <span>{lang === "zh" ? "边界" : "boundary"}</span>
                              <strong>{lang === "zh" ? "不触发外部搜索，不写正式知识/RAG/图谱" : "No external search, formal Knowledge/RAG/Graph writes off"}</strong>
                            </div>
                          </div>
                        ) : null}
                        {sourceCollectionAssignments.length ? (
                          <div className={styles.workflowSourceCollectionAssignments}>
                            {sourceCollectionAssignments.map((assignment) => (
                              <button
                                key={assignment.assignmentId}
                                type="button"
                                className={assignment.assignmentId === selectedSourceCollectionAssignment?.assignmentId ? styles.workflowSourceCollectionAssignmentActive : ""}
                                onClick={() =>
                                  setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId: assignment.assignmentId }))
                                }
                              >
                                <strong>{assignment.agentRole}</strong>
                                <span>{assignment.status} · {assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0} queries</span>
                              </button>
                            ))}
                          </div>
                        ) : (
                          <div className={styles.empty}>
                            {sourceCollectionAssignmentsQuery.isPending
                              ? (lang === "zh" ? "正在读取功能 Agent assignment..." : "Loading functional Agent assignments...")
                              : (lang === "zh" ? "启动批次后会生成 data_discovery/source_acquisition/content_extraction/source_quality assignment。" : "Starting a run will create data_discovery/source_acquisition/content_extraction/source_quality assignments.")}
                          </div>
                        )}
                        {selectedSourceCollectionQueries.length ? (
                          <div className={styles.workflowSourceCollectionQueries}>
                            {selectedSourceCollectionQueries.slice(0, 6).map((query) => (
                              <span key={query.queryId}>
                                <strong>{query.query}</strong>
                                <small>{query.queryId} · {query.sourceType} · {query.language}</small>
                              </span>
                            ))}
                          </div>
                        ) : null}
                        <form
                          className={styles.workflowSourceCollectionOutputForm}
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
                        >
                          <div className={styles.workflowSourceCollectionOutputHeader}>
                            <strong>{lang === "zh" ? "手工回写一条搜集结果" : "Manual result writeback"}</strong>
                            <span>{lang === "zh" ? "写 DataRecord 后自动导入 source_manifest 候选" : "Writes DataRecord, then imports source_manifest candidate"}</span>
                          </div>
                          <label>
                            <span>{lang === "zh" ? "Assignment" : "Assignment"}</span>
                            <select
                              value={sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId || ""}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId: event.target.value }))}
                              disabled={!sourceCollectionAssignments.length}
                            >
                              {sourceCollectionAssignments.map((assignment) => (
                                <option key={assignment.assignmentId} value={assignment.assignmentId}>
                                  {assignment.agentRole} · {assignment.status}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>{lang === "zh" ? "类型" : "Type"}</span>
                            <select
                              value={sourceCollectionOutputDraft.sourceType}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, sourceType: event.target.value }))}
                            >
                              {["paper", "url", "dataset", "file", "note", "manual"].map((sourceType) => (
                                <option key={sourceType} value={sourceType}>{sourceType}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>{lang === "zh" ? "标题" : "Title"}</span>
                            <input
                              value={sourceCollectionOutputDraft.title}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, title: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "来源引用" : "Source ref"}</span>
                            <input
                              value={sourceCollectionOutputDraft.sourceRef}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, sourceRef: event.target.value }))}
                              placeholder="https://doi.org/... / local path / dataset id"
                            />
                          </label>
                          <label>
                            <span>{lang === "zh" ? "原始位置" : "Raw location"}</span>
                            <input
                              value={sourceCollectionOutputDraft.rawLocation}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, rawLocation: event.target.value }))}
                              placeholder={lang === "zh" ? "页码、文件路径、段落或采集位置" : "Page range, file path, section, or capture location"}
                            />
                          </label>
                          <label className={styles.workflowSourceCollectionWide}>
                            <span>{lang === "zh" ? "摘要" : "Summary"}</span>
                            <textarea
                              value={sourceCollectionOutputDraft.summary}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, summary: event.target.value }))}
                              rows={2}
                            />
                          </label>
                          <label className={styles.workflowSourceCollectionWide}>
                            <span>{lang === "zh" ? "备注" : "Notes"}</span>
                            <input
                              value={sourceCollectionOutputDraft.notes}
                              onChange={(event) => setSourceCollectionOutputDraft((current) => ({ ...current, notes: event.target.value }))}
                            />
                          </label>
                          <button type="submit" disabled={!canRecordSourceCollectionOutput}>
                            <CheckCircle2 size={13} />
                            {selectedTeamRecordSourceCollectionOutputPending
                              ? (lang === "zh" ? "回写中" : "Writing")
                              : (lang === "zh" ? "回写并导入候选" : "Write back and import")}
                          </button>
                        </form>
                        <div className={styles.workflowIngestionBoundary}>
                          <span>{lang === "zh" ? "执行器：手动/Agent 均可提交 CollectionOutput" : "Executor: manual or Agent CollectionOutput"}</span>
                          <span>{lang === "zh" ? "正式知识写入关闭" : "formal knowledge write off"}</span>
                          <span>{lang === "zh" ? "进入候选仓库后再筛选" : "screen after candidate import"}</span>
                        </div>
                        {selectedTeamStartSourceCollectionError ? (
                          <div className={styles.messageError}>{selectedTeamStartSourceCollectionError.message}</div>
                        ) : null}
                        {selectedTeamRecordSourceCollectionOutputError ? (
                          <div className={styles.messageError}>{selectedTeamRecordSourceCollectionOutputError.message}</div>
                        ) : null}
                        {selectedTeamRecordSourceCollectionOutputResult ? (
                          <div className={styles.messageResult}>
                            <strong>{lang === "zh" ? "已回写" : "Written"}</strong>
                            <span>
                              {selectedTeamRecordSourceCollectionOutputResult.output.createdRecords.length} DataRecord / {selectedTeamRecordSourceCollectionOutputResult.imported.length} candidate
                            </span>
                          </div>
                        ) : null}
                      </div>
                      ) : null}
                      {showResearchCoordination ? (
                      <div className={styles.workflowCoordinationPanel} id="research-workflow-coordination">
                        <div className={styles.workflowIngestionHeader}>
                          <div>
                            <strong>{lang === "zh" ? "团队协调队列" : "Coordination queue"}</strong>
                            <span>
                              {teamWorkflowCoordinationStatus
                                ? `${teamWorkflowCoordinationStatus.summary.pendingTransferCount} transfer / ${teamWorkflowCoordinationStatus.summary.reworkCandidateCount} rework / ${teamWorkflowCoordinationStatus.summary.blockedCandidateCount} blocked`
                                : teamWorkflowCoordinationStatusQuery.isPending
                                ? (lang === "zh" ? "读取中" : "loading")
                                : (lang === "zh" ? "等待流程数据" : "waiting for workflow data")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(teamWorkflowCoordinationStatus?.status || "")}`}>
                            {teamWorkflowCoordinationStatus
                              ? workflowCoordinationStatusLabel(teamWorkflowCoordinationStatus.status, lang)
                              : (lang === "zh" ? "未读取" : "not loaded")}
                          </span>
                        </div>
                        {teamWorkflowCoordinationStatus ? (
                          <>
                            <div className={styles.workflowCoordinationStats}>
                              <span>{lang === "zh" ? "待决" : "transfer"} <strong>{teamWorkflowCoordinationStatus.summary.pendingTransferCount}</strong></span>
                              <span>{lang === "zh" ? "返工" : "rework"} <strong>{teamWorkflowCoordinationStatus.summary.reworkCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "治理" : "steward"} <strong>{teamWorkflowCoordinationStatus.summary.stewardshipCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "阻塞" : "blocked"} <strong>{teamWorkflowCoordinationStatus.summary.blockedCandidateCount}</strong></span>
                            </div>
                            <div className={styles.workflowCoordinationQueues}>
                              {[
                                ["pendingTransfers", teamWorkflowCoordinationStatus.queues.pendingTransfers],
                                ["needsRework", teamWorkflowCoordinationStatus.queues.needsRework],
                                ["stewardship", teamWorkflowCoordinationStatus.queues.stewardship],
                                ["blockedQueue", teamWorkflowCoordinationStatus.queues.blocked],
                              ].map(([queueName, queueItems]) => (
                                <div key={String(queueName)} className={styles.workflowCoordinationQueue}>
                                  <strong>{workflowCoordinationStatusLabel(String(queueName), lang)}</strong>
                                  {(queueItems as TeamWorkflowCoordinationStatus["queues"]["active"]).length ? (
                                    (queueItems as TeamWorkflowCoordinationStatus["queues"]["active"]).slice(0, 3).map((item) => (
                                      <span key={`${queueName}-${item.transferId || item.candidateId}`}>
                                        <strong>
                                          {item.transferId ? `${item.fromNode || "-"} -> ${item.toNode || "-"}` : workflowStateLabel(item.currentState, lang)}
                                          {" · "}
                                          {item.title || item.candidateType || item.candidateId}
                                        </strong>
                                        {item.communicationBrief ? (
                                          <small>
                                            {item.communicationBrief.targetAgentRole}
                                            {" · "}
                                            {workflowCoordinationChannelLabel(item.communicationBrief.channel, lang)}
                                          </small>
                                        ) : null}
                                      </span>
                                    ))
                                  ) : (
                                    <small>{lang === "zh" ? "空" : "empty"}</small>
                                  )}
                                </div>
                              ))}
                            </div>
                            {teamWorkflowCoordinationStatus.actionItems.length ? (
                              <div className={styles.workflowIngestionActions}>
                                {teamWorkflowCoordinationStatus.actionItems.slice(0, 4).map((item) => (
                                  <span key={`${item.code}-${item.queue}`} className={workflowIngestionTone(item.severity)}>
                                    {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            <div className={styles.workflowCoordinationBriefSummary}>
                              <span>
                                {lang === "zh" ? "沟通建议" : "briefs"} <strong>{teamWorkflowCoordinationStatus.communication.briefCount}</strong>
                              </span>
                              <span>{teamWorkflowCoordinationStatus.communication.recommendedSender}</span>
                              <span>
                                {teamWorkflowCoordinationStatus.communication.autoSendEnabled
                                  ? (lang === "zh" ? "自动发送开启" : "auto-send on")
                                  : (lang === "zh" ? "不会自动发送" : "no auto-send")}
                              </span>
                            </div>
                            <div className={styles.workflowIngestionBoundary}>
                              <span>{teamWorkflowCoordinationStatus.coordinationPolicy.coordinationAgentId}</span>
                              <span>
                                {teamWorkflowCoordinationStatus.coordinationPolicy.requiresUserConfirmation
                                  ? (lang === "zh" ? "需要用户确认" : "user confirmation")
                                  : (lang === "zh" ? "无需用户确认" : "no user confirmation")}
                              </span>
                              <span>
                                {teamWorkflowCoordinationStatus.coordinationPolicy.autoTransferEnabled
                                  ? (lang === "zh" ? "自动调转开启" : "auto transfer on")
                                  : (lang === "zh" ? "只读状态总览" : "read-only status")}
                              </span>
                            </div>
                          </>
                        ) : (
                          <div className={styles.empty}>
                            {teamWorkflowCoordinationStatusQuery.isPending
                              ? (lang === "zh" ? "正在汇总候选队列、返工项和转移请求..." : "Aggregating candidates, rework items, and transfers...")
                              : (lang === "zh" ? "暂无协调队列状态。" : "No coordination status yet.")}
                          </div>
                        )}
                        {teamWorkflowCoordinationStatusQuery.error instanceof Error ? (
                          <div className={styles.messageError}>{teamWorkflowCoordinationStatusQuery.error.message}</div>
                        ) : null}
                      </div>
                      ) : null}
                      {showResearchIngestion ? (
                      <div className={styles.workflowIngestionPanel} id="research-workflow-ingestion">
                        <div className={styles.workflowIngestionHeader}>
                          <div>
                            <strong>{lang === "zh" ? "知识入库状态" : "Knowledge ingestion"}</strong>
                            <span>
                              {teamWorkflowKnowledgeIngestionStatus
                                ? `${teamWorkflowKnowledgeIngestionStatus.summary.pendingProposalCount} pending / ${teamWorkflowKnowledgeIngestionStatus.summary.formalKnowledgeItemCount} formal`
                                : teamWorkflowKnowledgeIngestionStatusQuery.isPending
                                ? (lang === "zh" ? "读取中" : "loading")
                                : (lang === "zh" ? "等待候选" : "waiting for candidates")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(teamWorkflowKnowledgeIngestionStatus?.status || "")}`}>
                            {teamWorkflowKnowledgeIngestionStatus
                              ? workflowIngestionStatusLabel(teamWorkflowKnowledgeIngestionStatus.status, lang)
                              : (lang === "zh" ? "未读取" : "not loaded")}
                          </span>
                        </div>
                        {teamWorkflowKnowledgeIngestionStatus ? (
                          <>
                            <div className={styles.workflowIngestionStages}>
                              {teamWorkflowKnowledgeIngestionStatus.stages.map((stage) => (
                                <span key={stage.stageId} className={`${styles.workflowIngestionStage} ${workflowIngestionTone(stage.status)}`}>
                                  <strong>{stage.label}</strong>
                                  <small>{workflowIngestionStatusLabel(stage.status, lang)} · {stage.count}</small>
                                </span>
                              ))}
                            </div>
                            <div className={styles.workflowIngestionStats}>
                              <span>{lang === "zh" ? "来源" : "sources"} <strong>{teamWorkflowKnowledgeIngestionStatus.summary.sourceReadyCount}/{teamWorkflowKnowledgeIngestionStatus.summary.sourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "草稿" : "drafts"} <strong>{teamWorkflowKnowledgeIngestionStatus.summary.localDraftCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "待审" : "pending"} <strong>{teamWorkflowKnowledgeIngestionStatus.summary.pendingKnowledgeReviewCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "正式知识" : "formal"} <strong>{teamWorkflowKnowledgeIngestionStatus.summary.formalKnowledgeItemCount}</strong></span>
                            </div>
                            {teamWorkflowKnowledgeIngestionStatus.actionItems.length ? (
                              <div className={styles.workflowIngestionActions}>
                                {teamWorkflowKnowledgeIngestionStatus.actionItems.slice(0, 4).map((item) => (
                                  <span key={`${item.code}-${item.candidateId || item.workflowNode}`} className={workflowIngestionTone(item.severity)}>
                                    {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            <div className={styles.workflowIngestionBoundary}>
                              <span>
                                {teamWorkflowKnowledgeIngestionStatus.officialBoundary.writesOfficialKnowledge
                                  ? (lang === "zh" ? "正式知识已写入" : "official knowledge written")
                                  : (lang === "zh" ? "正式知识未写入" : "official knowledge not written")}
                              </span>
                              <span>
                                {teamWorkflowKnowledgeIngestionStatus.officialBoundary.writesOfficialGraph
                                  ? (lang === "zh" ? "正式图谱已同步" : "official graph synced")
                                  : (lang === "zh" ? "候选图谱预览" : "candidate graph preview")}
                              </span>
                              <span>
                                {teamWorkflowKnowledgeIngestionStatus.officialBoundary.writesOfficialRag
                                  ? (lang === "zh" ? "RAG 已写入" : "RAG written")
                                  : (lang === "zh" ? "RAG 不由本流程写入" : "RAG write off")}
                              </span>
                            </div>
                          </>
                        ) : (
                          <div className={styles.empty}>
                            {teamWorkflowKnowledgeIngestionStatusQuery.isPending
                              ? (lang === "zh" ? "正在汇总 CandidateStore、Team Knowledge 和正式同步边界..." : "Aggregating CandidateStore, Team Knowledge, and sync boundary...")
                              : (lang === "zh" ? "暂无知识入库状态。" : "No knowledge ingestion status yet.")}
                          </div>
                        )}
                        {teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error ? (
                          <div className={styles.messageError}>{teamWorkflowKnowledgeIngestionStatusQuery.error.message}</div>
                        ) : null}
                      </div>
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
                      {teamWorkflowValidationSummary ? (
                        <div className={styles.workflowValidation}>
                          <span>{lang === "zh" ? "校验" : "Validation"}</span>
                          <strong>
                            {teamWorkflowValidationSummary.validCandidateCount}/{teamWorkflowValidationSummary.candidateCount}
                          </strong>
                          <span>{teamWorkflowValidationSummary.errorCount} errors</span>
                          <span>{teamWorkflowValidationSummary.warningCount} warnings</span>
                        </div>
                      ) : teamWorkflowCandidatesQuery.isPending ? (
                        <div className={styles.empty}>{lang === "zh" ? "正在读取候选校验摘要..." : "Loading candidate validation summary..."}</div>
                      ) : null}
                        </>
                      ) : null}
                      {showResearchGraph ? (
                      <div className={styles.workflowGraphPanel} id="research-workflow-graph">
                        <div className={styles.workflowGraphHeader}>
                          <div>
                            <strong>{lang === "zh" ? "候选图谱" : "Candidate graph"}</strong>
                            <span>
                              {teamWorkflowCandidateGraph
                                ? `${teamWorkflowCandidateGraph.summary.nodeCount} nodes / ${teamWorkflowCandidateGraph.summary.edgeCount} edges`
                                : teamWorkflowCandidateGraphQuery.isPending
                                ? (lang === "zh" ? "读取中" : "loading")
                                : (lang === "zh" ? "未生成" : "not built")}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => selectedTeam?.teamId && buildCandidateGraphMutation.mutate(selectedTeam.teamId)}
                            disabled={!selectedTeam?.teamId || selectedTeamBuildCandidateGraphPending}
                          >
                            <RefreshCw size={13} />
                            {selectedTeamBuildCandidateGraphPending
                              ? (lang === "zh" ? "生成中" : "Building")
                              : (lang === "zh" ? "刷新图谱" : "Refresh graph")}
                          </button>
                        </div>
                        {teamWorkflowCandidateGraph && teamWorkflowCandidateGraphLayout ? (
                          <>
                            <div className={styles.workflowGraphStats}>
                              <span>{teamWorkflowCandidateGraph.graphKind}</span>
                              <span>{teamWorkflowCandidateGraph.summary.missingLinkCount} missing</span>
                              <span>{teamWorkflowCandidateGraph.summary.unreviewedNodeCount} review</span>
                              {typeof teamWorkflowCandidateGraph.summary.archivedCandidateCount === "number" ? (
                                <span>{teamWorkflowCandidateGraph.summary.archivedCandidateCount} archived</span>
                              ) : null}
                              <span>
                                {teamWorkflowCandidateGraph.officialBoundary.writesOfficialGraph
                                  ? (lang === "zh" ? "会写正式图谱" : "writes official graph")
                                  : (lang === "zh" ? "候选边界" : "candidate boundary")}
                              </span>
                            </div>
                            <div
                              className={styles.workflowGraphFrame}
                              style={{ "--workflow-graph-height": `${teamWorkflowCandidateGraphLayout.height}px` } as WorkflowGraphFrameStyle}
                            >
                              <svg
                                className={styles.workflowGraphSvg}
                                viewBox={`0 0 ${WORKFLOW_GRAPH_WIDTH} ${teamWorkflowCandidateGraphLayout.height}`}
                                preserveAspectRatio="xMinYMin meet"
                                aria-hidden="true"
                              >
                                <defs>
                                  <marker id="workflow-graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                                    <path d="M 0 0 L 10 5 L 0 10 z" />
                                  </marker>
                                </defs>
                                {teamWorkflowCandidateGraphLayout.edges.map((edge) => {
                                  const path = workflowGraphEdgePath(edge, teamWorkflowCandidateGraphLayout.nodes);
                                  return path ? (
                                    <path
                                      key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}`}
                                      className={styles.workflowGraphEdge}
                                      d={path}
                                    />
                                  ) : null;
                                })}
                              </svg>
                              {teamWorkflowCandidateGraphLayout.nodes.map((node) => (
                                <div
                                  key={node.candidateId}
                                  className={`${styles.workflowGraphNode} ${workflowGraphNodeTone(node)}`}
                                  style={{
                                    "--workflow-graph-node-x": `${node.x}px`,
                                    "--workflow-graph-node-y": `${node.y}px`,
                                  } as WorkflowGraphNodeStyle}
                                  title={`${node.candidateId} · ${node.currentState}`}
                                >
                                  <strong>{node.title || node.candidateId}</strong>
                                  <span>{workflowStateLabel(node.currentState, lang)}</span>
                                </div>
                              ))}
                            </div>
                            {teamWorkflowCandidateGraph.missingLinks.length || teamWorkflowCandidateGraph.unreviewedNodes.length ? (
                              <div className={styles.workflowGraphIssues}>
                                {teamWorkflowCandidateGraph.missingLinks.slice(0, 3).map((edge) => (
                                  <span key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}`}>
                                    {edge.relation}: {edge.targetCandidateId}
                                  </span>
                                ))}
                                {teamWorkflowCandidateGraph.unreviewedNodes.slice(0, 3).map((node) => (
                                  <span key={`${node.candidateId}-${node.reason}`}>{workflowStateLabel(node.currentState, lang)}</span>
                                ))}
                              </div>
                            ) : null}
                            <div className={styles.workflowGraphBoundary}>
                              {lang === "zh"
                                ? "CandidateStore 快照 · 正式知识/RAG/图谱写入关闭"
                                : "CandidateStore snapshot · official Knowledge/RAG/Graph writes off"}
                            </div>
                          </>
                        ) : (
                          <div className={styles.empty}>
                            {teamWorkflowCandidateGraphQuery.isPending
                              ? (lang === "zh" ? "正在读取候选图谱快照..." : "Loading candidate graph snapshot...")
                              : (lang === "zh" ? "还没有候选图谱快照，可先点击刷新图谱。" : "No candidate graph snapshot yet. Refresh the graph first.")}
                          </div>
                        )}
                        {teamWorkflowCandidateGraphQuery.error instanceof Error ? (
                          <div className={styles.messageError}>{teamWorkflowCandidateGraphQuery.error.message}</div>
                        ) : null}
                        {selectedTeamBuildCandidateGraphError ? (
                          <div className={styles.messageError}>{selectedTeamBuildCandidateGraphError.message}</div>
                        ) : null}
                      </div>
                      ) : null}
                      {showResearchCandidates ? (
                        <>
                      <div className={styles.workflowSourceQualityPanel}>
                        <div className={styles.workflowIngestionHeader}>
                          <div>
                            <strong>{lang === "zh" ? "资料质量筛选" : "Source quality screening"}</strong>
                            <span>
                              {teamWorkflowSourceQualityStatus
                                ? `${teamWorkflowSourceQualityStatus.summary.approvedSourceCandidateCount} approved / ${teamWorkflowSourceQualityStatus.summary.sourceCandidateCount} sources`
                                : teamWorkflowSourceQualityStatusQuery.isPending
                                ? (lang === "zh" ? "读取中" : "loading")
                                : (lang === "zh" ? "等待 source_manifest" : "waiting for source_manifest")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(teamWorkflowSourceQualityStatus?.status || "")}`}>
                            {teamWorkflowSourceQualityStatus
                              ? workflowIngestionStatusLabel(teamWorkflowSourceQualityStatus.status, lang)
                              : (lang === "zh" ? "未读取" : "not loaded")}
                          </span>
                        </div>
                        {teamWorkflowSourceQualityStatus ? (
                          <>
                            <div className={styles.workflowSourceQualityStats}>
                              <span>{lang === "zh" ? "来源" : "sources"} <strong>{teamWorkflowSourceQualityStatus.summary.sourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "已筛选" : "assessed"} <strong>{teamWorkflowSourceQualityStatus.summary.assessedSourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "通过" : "approved"} <strong>{teamWorkflowSourceQualityStatus.summary.approvedSourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "待修订" : "revision"} <strong>{teamWorkflowSourceQualityStatus.summary.needsRevisionSourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "未筛选" : "pending"} <strong>{teamWorkflowSourceQualityStatus.summary.unassessedSourceCandidateCount}</strong></span>
                            </div>
                            {teamWorkflowSourceQualityStatus.candidates.length ? (
                              <div className={styles.workflowSourceQualityQueue}>
                                {teamWorkflowSourceQualityStatus.candidates.slice(0, 5).map((item) => (
                                  <span key={item.candidateId} className={workflowIngestionTone(item.bucket === "approved" ? "ready" : item.bucket)}>
                                    <strong>{item.title}</strong>
                                    <small>
                                      {workflowIngestionStatusLabel(item.bucket, lang)} · {item.overallScore ? `${item.overallScore}/100` : "-"} · {item.sourceKind || "source"}
                                    </small>
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            {teamWorkflowSourceQualityStatus.actionItems.length ? (
                              <div className={styles.workflowIngestionActions}>
                                {teamWorkflowSourceQualityStatus.actionItems.slice(0, 3).map((item) => (
                                  <span key={`${item.code}-${item.candidateId}`} className={workflowIngestionTone(item.severity)}>
                                    {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            <div className={styles.workflowIngestionBoundary}>
                              <span>{lang === "zh" ? "Source Quality Assessment Agent" : "Source Quality Assessment Agent"}</span>
                              <span>{lang === "zh" ? "只写 CandidateStore" : "CandidateStore only"}</span>
                              <span>{lang === "zh" ? "不写正式知识/RAG/图谱" : "no formal Knowledge/RAG/Graph writes"}</span>
                            </div>
                          </>
                        ) : (
                          <div className={styles.empty}>
                            {teamWorkflowSourceQualityStatusQuery.isPending
                              ? (lang === "zh" ? "正在汇总 source_manifest 质量筛选状态..." : "Aggregating source quality screening status...")
                              : (lang === "zh" ? "暂无资料质量筛选状态。" : "No source quality status yet.")}
                          </div>
                        )}
                        {teamWorkflowSourceQualityStatusQuery.error instanceof Error ? (
                          <div className={styles.messageError}>{teamWorkflowSourceQualityStatusQuery.error.message}</div>
                        ) : null}
                        {selectedTeamSourceQualityError ? (
                          <div className={styles.messageError}>{selectedTeamSourceQualityError.message}</div>
                        ) : null}
                      </div>
                      <div className={styles.workflowPaperNoteChunkPanel}>
                        <div className={styles.workflowIngestionHeader}>
                          <div>
                            <strong>{lang === "zh" ? "paper_note 分块计划" : "paper_note chunk plan"}</strong>
                            <span>
                              {teamWorkflowPaperNoteChunkStatus
                                ? `${teamWorkflowPaperNoteChunkStatus.summary.planCount} plans / ${teamWorkflowPaperNoteChunkStatus.summary.chunkCount} chunks`
                                : teamWorkflowPaperNoteChunkStatusQuery.isPending
                                ? (lang === "zh" ? "读取中" : "loading")
                                : (lang === "zh" ? "等待 source extraction" : "waiting for source extraction")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(teamWorkflowPaperNoteChunkStatus?.status || "")}`}>
                            {teamWorkflowPaperNoteChunkStatus
                              ? workflowIngestionStatusLabel(teamWorkflowPaperNoteChunkStatus.status, lang)
                              : (lang === "zh" ? "未读取" : "not loaded")}
                          </span>
                        </div>
                        {teamWorkflowPaperNoteChunkStatus ? (
                          <>
                            <div className={styles.workflowPaperNoteChunkStats}>
                              <span>{lang === "zh" ? "可分块来源" : "ready sources"} <strong>{teamWorkflowPaperNoteChunkStatus.summary.readySourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "已规划来源" : "planned sources"} <strong>{teamWorkflowPaperNoteChunkStatus.summary.plannedSourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "缺计划" : "missing plans"} <strong>{teamWorkflowPaperNoteChunkStatus.summary.missingPlanSourceCandidateCount}</strong></span>
                              <span>{lang === "zh" ? "待 draft" : "open chunks"} <strong>{teamWorkflowPaperNoteChunkStatus.summary.openChunkCount}</strong></span>
                            </div>
                            {teamWorkflowPaperNoteChunkStatus.plans.length ? (
                              <div className={styles.workflowPaperNoteChunkPlans}>
                                {teamWorkflowPaperNoteChunkStatus.plans.slice(0, 4).map((plan) => (
                                  <span key={plan.planId}>
                                    <strong>{plan.sourceTitle || plan.sourceCandidateId}</strong>
                                    <small>{workflowIngestionStatusLabel(plan.status, lang)} · {plan.draftedChunkCount}/{plan.chunkCount} · {plan.pageScope || "-"}</small>
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <div className={styles.empty}>
                                {lang === "zh" ? "还没有分块计划。对已完成内容提取的 source 生成计划后，才能按 chunk 产出 paper_note。" : "No chunk plan yet. Generate plans for extracted sources before drafting paper_notes by chunk."}
                              </div>
                            )}
                            {teamWorkflowPaperNoteChunkStatus.actionItems.length ? (
                              <div className={styles.workflowIngestionActions}>
                                {teamWorkflowPaperNoteChunkStatus.actionItems.slice(0, 3).map((item) => (
                                  <span key={`${item.code}-${item.candidateId}`} className={workflowIngestionTone(item.severity)}>
                                    {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                            <div className={styles.workflowIngestionBoundary}>
                              <span>{lang === "zh" ? "CandidateStore 计划" : "CandidateStore plan"}</span>
                              <span>{lang === "zh" ? "不写正式知识/RAG/图谱" : "no formal Knowledge/RAG/Graph writes"}</span>
                              <span>{lang === "zh" ? "后续 paper_note draft 需带 chunkId" : "paper_note draft should use chunkId"}</span>
                            </div>
                          </>
                        ) : (
                          <div className={styles.empty}>
                            {teamWorkflowPaperNoteChunkStatusQuery.isPending
                              ? (lang === "zh" ? "正在汇总 source extraction 与 paper_note chunk 计划..." : "Aggregating source extraction and paper_note chunk plans...")
                              : (lang === "zh" ? "暂无 paper_note 分块状态。" : "No paper_note chunk status yet.")}
                          </div>
                        )}
                        {teamWorkflowPaperNoteChunkStatusQuery.error instanceof Error ? (
                          <div className={styles.messageError}>{teamWorkflowPaperNoteChunkStatusQuery.error.message}</div>
                        ) : null}
                        {selectedTeamPlanPaperNoteChunksError ? (
                          <div className={styles.messageError}>{selectedTeamPlanPaperNoteChunksError.message}</div>
                        ) : null}
                      </div>
                      {teamWorkflowCandidates.length ? (
                        <div className={styles.workflowCandidateList} id="research-workflow-candidates">
                          {teamWorkflowCandidates.map((candidate) => {
                            const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
                            const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
                            const canPlanPaperNoteChunks = sourceCandidateHasCompletedExtraction(candidate);
                            const candidateQualityPending =
                              selectedTeamAssessSourceQualityPending
                              && assessSourceQualityMutation.variables?.candidateId === candidate.candidateId;
                            const candidatePlanPending =
                              selectedTeamPlanPaperNoteChunksPending
                              && planPaperNoteChunksMutation.variables?.candidateId === candidate.candidateId;
                            return (
                              <article key={candidate.candidateId} className={styles.workflowCandidateItem}>
                                <div className={styles.workflowCandidateHeader}>
                                  <strong>{candidate.title || candidate.candidateId}</strong>
                                  <span className={`${styles.workflowTag} ${workflowQualityTone(candidate.qualityStatus)}`}>
                                    {workflowStateLabel(candidate.currentState, lang)}
                                  </span>
                                </div>
                                <p>{candidate.summary || candidate.candidateType}</p>
                                <div className={styles.workflowCandidateMeta}>
                                  <span>{candidate.candidateType}</span>
                                  <span>{candidate.qualityStatus}</span>
                                  <span>{formatTime(candidate.updatedAt, lang)}</span>
                                  {sourceQualitySummary ? (
                                    <span>
                                      source quality {workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · {sourceQualitySummary.overallScore}/100
                                    </span>
                                  ) : candidate.candidateType === "source_manifest" ? (
                                    <span>{lang === "zh" ? "待资料质量筛选" : "pending source quality"}</span>
                                  ) : null}
                                  {chunkPlanSummary ? (
                                    <span>
                                      paper_note chunks {chunkPlanSummary.completedChunkCount}/{chunkPlanSummary.chunkCount}
                                    </span>
                                  ) : canPlanPaperNoteChunks ? (
                                    <span>{lang === "zh" ? "可生成 paper_note 分块" : "ready for paper_note chunks"}</span>
                                  ) : null}
                                </div>
                                {candidate.candidateType === "source_manifest" ? (
                                  <div className={styles.workflowCandidateActions}>
                                    <button
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
                                      title={lang === "zh" ? "由 Source Quality Assessment Agent 标记为通过筛选" : "Mark this source as approved by Source Quality Assessment Agent"}
                                    >
                                      <CheckCircle2 size={13} />
                                      {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "approved"
                                        ? (lang === "zh" ? "筛选中" : "Assessing")
                                        : (lang === "zh" ? "通过筛选" : "Approve source")}
                                    </button>
                                    <button
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
                                      title={lang === "zh" ? "退回 Source Intake / Acquisition Agent 补资料" : "Return this source for quality repair"}
                                    >
                                      <AlertTriangle size={13} />
                                      {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "needs_revision"
                                        ? (lang === "zh" ? "退回中" : "Returning")
                                        : (lang === "zh" ? "退回补资料" : "Needs repair")}
                                    </button>
                                    <button
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
                                    </button>
                                  </div>
                                ) : null}
                              </article>
                            );
                          })}
                        </div>
                      ) : (
                        <div className={styles.empty}>
                          {lang === "zh" ? "候选仓库还没有资料、笔记或机制候选。" : "No sources, notes, or mechanism candidates yet."}
                        </div>
                      )}
                        </>
                      ) : null}
                    </>
                  ) : (
                    <div className={styles.empty}>{lang === "zh" ? "科研流程尚未初始化。" : "Research workflow is not initialized yet."}</div>
                  )
                ) : (
                  <div className={styles.empty}>
                    {lang === "zh" ? "选择 research-team / ai科学研究团队后显示挑战杯科研流程。" : "Select research-team to view the Challenge Cup workflow."}
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
                <textarea
                  value={teamTaskTopic}
                  onChange={(event) => setTeamTaskTopic(event.target.value)}
                  placeholder={lang === "zh" ? "输入团队要协作处理的议题或任务" : "Enter a topic or task for this team"}
                />
                <button
                  type="submit"
                  disabled={!canStartTeamRound || selectedTeamStartRoundPending}
                >
                  <Play size={14} />
                  {selectedTeamStartRoundPending
                    ? (lang === "zh" ? "启动中" : "Starting")
                    : (lang === "zh" ? "启动团队讨论" : "Start team round")}
                </button>
                {selectedTeamStartRoundResult ? (
                  <div className={styles.messageResult}>
                    <strong>{selectedTeamStartRoundResult.rounds.length}</strong>
                    <span>{lang === "zh" ? "轮讨论已写入关联群聊" : "rounds now recorded in the linked room"}</span>
                    <Link to={`/chat?room=${encodeURIComponent(selectedTeamStartRoundResult.roomId)}`}>
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
                      <Link to={`/chat?room=${encodeURIComponent(latestTeamRound.roomId)}`}>
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
                <textarea
                  value={teamMessage}
                  onChange={(event) => setTeamMessage(event.target.value)}
                  placeholder={lang === "zh" ? "发送给当前团队 active 成员" : "Send to active members of this team"}
                />
                <label className={styles.inlineToggle}>
                  <input type="checkbox" checked={teamInterrupt} onChange={(event) => setTeamInterrupt(event.target.checked)} />
                  <span>{lang === "zh" ? "打断正在直聊中的目标 Agent" : "Interrupt targeted running direct sessions"}</span>
                </label>
                <button
                  type="submit"
                  disabled={!selectedTeam || !teamMessage.trim() || activeTeamMemberCount === 0 || selectedTeamMessagePending}
                >
                  <Send size={14} />
                  {lang === "zh" ? "发送给团队" : "Send to team"}
                </button>
                {selectedTeamMessageResult ? (
                  <div className={styles.messageResult}>
                    <strong>{selectedTeamMessageResult.deliveries.length}</strong>
                    <span>{lang === "zh" ? "条投递已进入项目总群" : "deliveries recorded in project bus"}</span>
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
                          </div>
                          <div className={styles.deliveryList}>
                            {event.deliveries.map((delivery) => (
                              <span key={`${event.eventId}-${delivery.targetAgentId}-${delivery.inboxMessageId}`}>
                                {delivery.targetAgentCode || delivery.targetAgentName || delivery.targetAgentId}: {delivery.revoked ? "revoked" : delivery.wake?.wakeStatus || delivery.status}
                              </span>
                            ))}
                          </div>
                          {event.createdBy === "user" && !revoked ? (
                            <button
                              type="button"
                              className={styles.revokeButton}
                              disabled={revokePending}
                              onClick={() => selectedTeam?.teamId && revokeTeamMessageMutation.mutate({ teamId: selectedTeam.teamId, eventId: event.eventId })}
                            >
                              {revokePending ? (lang === "zh" ? "撤回中" : "Revoking") : (lang === "zh" ? "撤回" : "Revoke")}
                            </button>
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
    </section>
  );
}
