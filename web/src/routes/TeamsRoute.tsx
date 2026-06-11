import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, ArrowLeft, Bot, CheckCircle2, Link2, Play, Plus, RefreshCw, Save, Search, Send, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
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
  TeamTemplateInstantiatePayload,
  TeamTemplateListPayload,
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
const SOURCE_COLLECTION_PROMPT_CACHE_POLICY = {
  requirement: "required_for_llm_execution",
  modelId: "houmo_qwen35_9b_agent",
};

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

type TeamDraft = {
  name: string;
  purpose: string;
};

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
  assignments: TeamWorkflowSourceCollectionRunStartPayload["assignments"];
  outputs: Array<DataProcessingCollectionOutputPayload["output"]>;
  createdRecords: DataProcessingCollectionOutputPayload["createdRecords"];
  imported: TeamWorkflowDataRecordSourceCandidateImportPayload[];
  executionEvents: SourceCollectionSearchExecutionEvent[];
  boundaries: {
    externalSearchTriggered: boolean;
    metadataOnlyDownload: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  nextActions: string[];
};

type ResearchStageType = "knowledge_collection" | "experiment" | "iteration";

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
  const sourceCollectionStandalone =
    sourceCollectionStandaloneProp || requestedResearchWorkspaceView === "knowledge_collection" || requestedResearchViewParam === "source_collection";
  const stageStandaloneView: ResearchStageWorkspaceView | null =
    requestedResearchWorkspaceView === "experiment" || requestedResearchWorkspaceView === "iteration" ? requestedResearchWorkspaceView : null;
  const pageVisible = usePageVisibility();
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [teamDraft, setTeamDraft] = useState<TeamDraft>({ name: "", purpose: "" });
  const [createTeamError, setCreateTeamError] = useState("");
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>({ label: "", role: "", purpose: "", agentId: "" });
  const [teamMessage, setTeamMessage] = useState("");
  const [teamInterrupt, setTeamInterrupt] = useState(false);
  const [teamTaskTopic, setTeamTaskTopic] = useState("");
  const [showCommunicationEdges, setShowCommunicationEdges] = useState(false);
  const [researchWorkspaceView, setResearchWorkspaceView] = useState<ResearchWorkspaceView>(
    forcedResearchWorkspaceView ?? requestedResearchWorkspaceView ?? "overview",
  );
  const [sourceCollectionDraft, setSourceCollectionDraft] = useState<SourceCollectionDraft>({
    title: "Neural algorithm source batch",
    topic: "neural predictive coding",
    goal: "Collect traceable neuroscience sources that can support neural-network algorithm hypotheses.",
    querySeeds: "predictive coding cortical hierarchy\nsynaptic plasticity learning rule\nneural gating attention mechanism",
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
  const [nodePositionDrafts, setNodePositionDrafts] = useState<Record<string, { x: number; y: number }>>({});
  const [canvasFrameSize, setCanvasFrameSize] = useState<CanvasFrameSize>({ width: CANVAS_VIEWPORT_WIDTH, height: CANVAS_VIEWPORT_HEIGHT });
  const [lockedCanvasViewportStyle, setLockedCanvasViewportStyle] = useState<CanvasViewportStyle | null>(null);
  const canvasFrameRef = useRef<HTMLDivElement | null>(null);
  const teamNameInputRef = useRef<HTMLInputElement | null>(null);
  const dragStateRef = useRef<NodeDragState | null>(null);
  const dragFrameRef = useRef(0);

  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
  });
  const teamTemplatesQuery = useQuery({
    queryKey: queryKeys.teamTemplates(),
    queryFn: () => fetchJson<TeamTemplateListPayload>("/api/team-templates"),
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
  const teams = teamsQuery.data?.teams ?? [];
  const visibleTeams = useMemo(() => teams.filter((team) => !isEvolutionSystemTeam(team)), [teams]);
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
  const teamTemplates = useMemo(() => teamTemplatesQuery.data?.templates ?? [], [teamTemplatesQuery.data?.templates]);
  const selectedTemplate = useMemo(
    () => teamTemplates.find((template) => template.templateId === selectedTemplateId) ?? teamTemplates[0] ?? null,
    [selectedTemplateId, teamTemplates],
  );
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
    queryFn: () => fetchJson<DataProcessingRunListPayload>(`/api/data-processing/runs?limit=${SOURCE_COLLECTION_RUN_PREVIEW_LIMIT}`),
    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected),
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
  const selectedSourceCollectionRun =
    sourceCollectionRuns.find((run) => run.runId === selectedSourceCollectionRunId) ?? sourceCollectionRuns[0] ?? null;
  const selectedSourceCollectionRunEffectiveId = selectedSourceCollectionRun?.runId ?? "";
  const sourceCollectionRunStatusQuery = useQuery({
    queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: () => fetchJson<DataProcessingStatus>(`/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/status`),
    enabled: Boolean(researchWorkflowTeamSelected && selectedSourceCollectionRunEffectiveId),
  });
  const sourceCollectionAssignmentsQuery = useQuery({
    queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: () =>
      fetchJson<DataProcessingCollectionAssignmentListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/collection-assignments`,
      ),
    enabled: Boolean(researchWorkflowTeamSelected && selectedSourceCollectionRunEffectiveId),
  });
  const autoCanvasViewportStyle = useMemo(() => canvasViewStyle(canvasNodes, canvasFrameSize), [canvasFrameSize, canvasNodes]);
  const canvasViewportStyle = lockedCanvasViewportStyle ?? autoCanvasViewportStyle;
  const canvasScale = canvasStyleScale(canvasViewportStyle);
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, selectedTeam?.teamId),
    [projectBusQuery.data, selectedTeam?.teamId],
  );

  useEffect(() => {
    if (!teamTemplates.length) {
      if (selectedTemplateId) {
        setSelectedTemplateId("");
      }
      return;
    }
    if (!selectedTemplateId || !teamTemplates.some((template) => template.templateId === selectedTemplateId)) {
      setSelectedTemplateId(teamTemplates[0].templateId);
    }
  }, [selectedTemplateId, teamTemplates]);

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

  const createTeamMutation = useMutation({
    mutationFn: (draft: TeamDraft) =>
      fetchJson<Team>("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      }),
    onSuccess: (team) => {
      setSelectedTeamId(team.teamId);
      setSearchParams({ team: team.teamId });
      setTeamDraft({ name: "", purpose: "" });
      setCreateTeamError("");
      void chatWorkspaceCache.afterTeamChanged(team.teamId);
    },
    onError: (error) => {
      setCreateTeamError(error instanceof Error ? error.message : String(error));
    },
  });

  const instantiateTeamTemplateMutation = useMutation({
    mutationFn: (templateId: string) =>
      fetchJson<TeamTemplateInstantiatePayload>(`/api/team-templates/${encodeURIComponent(templateId)}/instantiate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }),
    onSuccess: (payload) => {
      const team = payload.team;
      setSelectedTeamId(team.teamId);
      setSearchParams({ team: team.teamId });
      setSelectedNodeId("");
      setCreateTeamError("");
      queryClient.setQueryData(queryKeys.team(team.teamId), team);
      void chatWorkspaceCache.afterTeamChanged(team.teamId);
      if (team.linkedChatRoom?.roomId) {
        void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
      }
    },
    onError: (error) => {
      setCreateTeamError(error instanceof Error ? error.message : String(error));
    },
  });

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
      if (sourceRunId) {
        setSelectedSourceCollectionRunId(sourceRunId);
        const firstAssignmentId = payload.assignments?.[0]?.assignmentId ?? "";
        if (firstAssignmentId) {
          setSourceCollectionOutputDraft((current) => ({
            ...current,
            assignmentId: firstAssignmentId,
          }));
        }
        if (payload.run) {
          queryClient.setQueryData(queryKeys.dataProcessingRunStatus(sourceRunId), {
            schemaVersion: 1,
            runId: payload.run.runId,
            profileId: payload.run.profileId,
            runStatus: payload.run.status,
            summary: payload.run.summary ?? {
              recordCount: 0,
              assignmentCount: payload.assignmentCount ?? payload.assignments?.length ?? 0,
              openAssignmentCount: payload.continuedSourceRunRef?.openAssignmentCount ?? 0,
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
        if (payload.assignments) {
          queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(sourceRunId), {
            schemaVersion: 1,
            runId: sourceRunId,
            assignments: payload.assignments,
            summary: {
              assignmentCount: payload.assignments.length,
              assignmentStatusCounts: payload.assignments.reduce<Record<string, number>>((counts, assignment) => {
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
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      setSelectedSourceCollectionRunId(payload.runId);
      queryClient.setQueryData(queryKeys.dataProcessingRunStatus(payload.runId), payload.runStatus);
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

  const assessSourceQualityMutation = useMutation({
    mutationFn: (payload: { teamId: string; candidateId: string; decision: "approved" | "needs_revision" }) =>
      fetchJson<TeamWorkflowSourceQualityAssessmentPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/candidates/${encodeURIComponent(payload.candidateId)}/source-quality/assess`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assessedByAgent: sourceCollectionOwnerAgentId,
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

  function renderResearchStageLauncher() {
    if (!researchWorkflowTeamSelected) {
      return null;
    }
    const phaseOrder: ResearchStageType[] = ["knowledge_collection", "experiment", "iteration"];
    const phaseFallback: Record<ResearchStageType, { label: string; primaryAction: string; secondaryAction: string }> = {
      knowledge_collection: {
        label: lang === "zh" ? "知识搜集" : "Knowledge",
        primaryAction: lang === "zh" ? "启动知识搜集" : "Start knowledge",
        secondaryAction: lang === "zh" ? "开启新一轮" : "New round",
      },
      experiment: {
        label: lang === "zh" ? "实验" : "Experiment",
        primaryAction: lang === "zh" ? "启动实验规划" : "Plan experiment",
        secondaryAction: lang === "zh" ? "重新规划" : "Replan",
      },
      iteration: {
        label: lang === "zh" ? "迭代" : "Iteration",
        primaryAction: lang === "zh" ? "启动迭代" : "Start iteration",
        secondaryAction: lang === "zh" ? "新一轮迭代" : "New iteration",
      },
    };
    return (
      <section className={styles.researchStageLauncher} aria-label={lang === "zh" ? "科研三阶段启动台" : "Research stage launcher"}>
        <div className={styles.researchStageLauncherHeader}>
          <div>
            <strong>{lang === "zh" ? "科研三阶段启动台" : "Research stage launcher"}</strong>
            <span>
              {researchStageRoundStatus
                ? `${lang === "zh" ? "当前" : "Current"} ${researchStageRoundStatus.currentStage || "knowledge_collection"}`
                : researchStageRoundStatusQuery.isPending
                ? (lang === "zh" ? "读取阶段状态中" : "Loading stage status")
                : (lang === "zh" ? "等待阶段启动" : "Waiting for stage start")}
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
            const disabled = selectedTeamStartResearchStagePending || (stageType === "knowledge_collection" && !researchStageCanLaunch);
            return (
              <article key={stageType} className={active ? `${styles.researchStageCard} ${styles.researchStageCardActive}` : styles.researchStageCard}>
                <div>
                  <strong>{phase?.label || fallback.label}</strong>
                  <span>
                    {active
                      ? (lang === "zh" ? "运行中" : "running")
                      : latestRound
                      ? `${lang === "zh" ? "最近" : "latest"} ${latestRound.status}`
                      : (lang === "zh" ? "未启动" : "not started")}
                  </span>
                </div>
                <small>{phase?.readiness?.reason || (lang === "zh" ? "由用户决定是否进入本阶段。" : "User decides when to enter this stage.")}</small>
                <div className={styles.researchStageActions}>
                  <button type="button" onClick={() => launchResearchStage(stageType)} disabled={disabled}>
                    <Play size={13} />
                    {phase?.primaryAction || fallback.primaryAction}
                  </button>
                  <button type="button" onClick={() => launchResearchStage(stageType, "new_round")} disabled={disabled}>
                    <Plus size={13} />
                    {phase?.secondaryAction || fallback.secondaryAction}
                  </button>
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

  function renderResearchWorkspaceNav() {
    if (!researchWorkflowTeamSelected) {
      return null;
    }
    return (
      <nav className={styles.researchIndexPanel} aria-label={lang === "zh" ? "科研三阶段索引" : "Research stage index"}>
        <div className={styles.researchIndexHeader}>
          <div>
            <strong>{lang === "zh" ? "科研三阶段索引" : "Research stages"}</strong>
            <span>{lang === "zh" ? "团队专属阶段页" : "Team-specific stage pages"}</span>
          </div>
          <small>{lang === "zh" ? "三阶段" : "3 stages"}</small>
        </div>
        <div className={styles.researchIndexList}>
          {RESEARCH_WORKSPACE_NAV_ITEMS.map((item, index) => (
            <Link
              key={item.view}
              className={researchWorkspaceView === item.view ? `${styles.researchIndexItem} ${styles.researchIndexItemActive}` : styles.researchIndexItem}
              to={researchWorkspaceStageRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID, item.view)}
            >
              <small>{String(index + 1).padStart(2, "0")}</small>
              <strong>{lang === "zh" ? item.zh : item.en}</strong>
              <span>{lang === "zh" ? item.zhDetail : item.enDetail}</span>
              <em>{lang === "zh" ? item.zhModules : item.enModules}</em>
            </Link>
          ))}
        </div>
      </nav>
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
    return (
      <section className={styles.sourceCollectionConversationPanel} aria-label={lang === "zh" ? "搜集对话流" : "Collection conversation"}>
        <div className={styles.sourceCollectionConversationHeader}>
          <div>
            <strong>{lang === "zh" ? "搜集过程" : "Collection process"}</strong>
            <span>
              {lang === "zh"
                ? "像对话一样记录：搜索了什么、得到什么、存到哪里、下一步该做什么。"
                : "Conversation-like trace: what was searched, what was found, where it was stored, and what comes next."}
            </span>
          </div>
          <small>{sourceCollectionTraceMessages.length} {lang === "zh" ? "步" : "steps"}</small>
        </div>
        <div className={styles.sourceCollectionTraceList}>
          {sourceCollectionTraceMessages.map((message, index) => (
            <article key={message.id} className={`${styles.sourceCollectionTraceMessage} ${toneClass[message.tone]}`}>
              <div className={styles.sourceCollectionTraceAvatar}>
                <small>{String(index + 1).padStart(2, "0")}</small>
                <span>{sourceCollectionTraceToneLabel(message.tone, lang)}</span>
              </div>
              <div className={styles.sourceCollectionTraceBody}>
                <div className={styles.sourceCollectionTraceMeta}>
                  <strong>{sourceCollectionTraceToneLabel(message.tone, lang)}</strong>
                  <span>{message.status}</span>
                </div>
                <h3>{message.title}</h3>
                <p>{message.body}</p>
                <div className={styles.sourceCollectionTraceOwner}>
                  <span>{message.agentRole}</span>
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
                        {message.storageRefs.map((ref) => (
                          <span key={ref}>{ref}</span>
                        ))}
                      </div>
                    ) : null}
                  </details>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>
    );
  }

  function renderSourceCollectionRunNotice() {
    if (!selectedSourceCollectionRun || !sourceCollectionRunStatus) {
      return null;
    }
    const recordCount = sourceCollectionRunStatus.summary.recordCount ?? 0;
    const openAssignmentCount = sourceCollectionRunStatus.summary.openAssignmentCount ?? 0;
    const queryCount = sourceCollectionSearchPlanRef?.queryCount ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount ?? 0;
    const externalSearchTriggered = Boolean(sourceCollectionSearchPlanRef?.externalSearchTriggered);
    if (recordCount > 0 || openAssignmentCount <= 0) {
      return null;
    }
    return (
      <div className={styles.workflowNotice}>
        <strong>{lang === "zh" ? "搜集批次已启动，等待功能 Agent 回写" : "Collection run is active and waiting for Agent writeback"}</strong>
        <span>
          {lang === "zh"
            ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} 已规划 ${queryCount} 条 query，当前 ${openAssignmentCount} 个任务仍未完成；现阶段执行 metadata-only 搜索，会记录搜索词、来源元数据、DataRecord 和候选导入，不下载全文网页/PDF，也不写正式知识。`
            : `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} has ${queryCount} planned queries and ${openAssignmentCount} open tasks. The current executor is metadata-only: it records queries, source metadata, DataRecords, and candidate imports without downloading full webpages/PDFs or writing formal knowledge.`}
        </span>
        <small>
          {lang === "zh"
            ? "真实搜索执行器接入后会在这里记录搜索、下载、提炼和落库轨迹"
            : "After the real search executor is connected, this area records search, download, extraction, and ingestion traces."}
        </small>
        <em>
          {externalSearchTriggered
            ? (lang === "zh" ? "已进入 metadata 搜索执行" : "metadata search executed")
            : (lang === "zh" ? "当前仍是计划/回写阶段，未触发外部搜索" : "planning/writeback stage, no external search triggered")}
        </em>
      </div>
    );
  }

  function renderSourceCollectionControlsPanel() {
    const sourceCollectionExecutionTitle = lang === "zh" ? "对话式执行下一批搜索" : "Run next search batch as trace";
    return (
      <section className={styles.sourceCollectionControlPanel} aria-label={lang === "zh" ? "资料搜集控制台" : "Source collection controls"}>
        <div className={styles.workflowIngestionHeader}>
          <div>
            <strong>{lang === "zh" ? "下一步操作" : "Next action"}</strong>
            <span>
              {selectedSourceCollectionRun
                ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionStageFocusLabel}`
                : lang === "zh" ? "等待启动搜集批次" : "Waiting for a collection run"}
            </span>
          </div>
          <span className={`${styles.workflowTag} ${workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}`}>
            {sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || (lang === "zh" ? "未启动" : "not started")}
          </span>
        </div>
        <div className={styles.workflowSourceCollectionActionSummary}>
          <div>
            <strong>{sourceCollectionPrimaryActionTitle}</strong>
            <span>{sourceCollectionPrimaryActionBody}</span>
          </div>
        </div>
        <details className={styles.workflowSourceCollectionDetails} open={!selectedSourceCollectionRun}>
          <summary>
            <span>{lang === "zh" ? "启动设置" : "Launch settings"}</span>
            <small>{lang === "zh" ? "主题、目标、query seeds" : "Topic, goal, query seeds"}</small>
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
            <span>Query seeds</span>
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
        {selectedSourceCollectionRun ? (
        <div className={styles.workflowSourceCollectionSearchAction}>
          <div>
            <strong>{sourceCollectionExecutionTitle}</strong>
            <span>
              {lang === "zh"
                ? `会搜索来源元数据、写 DataRecord、导入候选，并把过程写入左侧搜集过程；剩余 ${sourceCollectionOpenAssignmentCount} 个可执行任务。`
                : `Searches source metadata, writes DataRecords, imports candidates, and appends the process trace; ${sourceCollectionOpenAssignmentCount} runnable assignments remain.`}
            </span>
          </div>
          <button
            type="button"
            disabled={!canExecuteSourceCollectionSearch}
            onClick={() => {
              if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !canExecuteSourceCollectionSearch) {
                return;
              }
              const selectedAssignmentIsRunnable = selectedSourceCollectionAssignment
                ? ["open", "in_progress", "returned"].includes(selectedSourceCollectionAssignment.status)
                : false;
              executeSourceCollectionSearchMutation.mutate({
                teamId: selectedTeam.teamId,
                runId: selectedSourceCollectionRunEffectiveId,
                assignmentId: selectedAssignmentIsRunnable ? selectedSourceCollectionAssignment?.assignmentId : "",
                maxQueries: 4,
                maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 2)),
              });
            }}
          >
            <Search size={13} />
            {selectedTeamExecuteSourceCollectionSearchPending
              ? (lang === "zh" ? "搜索中" : "Searching")
              : (lang === "zh" ? "执行下一批搜索" : "Run next search")}
          </button>
        </div>
        ) : null}
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
            <span>{lang === "zh" ? "记录" : "records"} <strong>{sourceCollectionRecordCount}</strong></span>
            <span>{lang === "zh" ? "任务" : "assignments"} <strong>{sourceCollectionAssignmentCount}</strong></span>
            <span>{lang === "zh" ? "未完成" : "open"} <strong>{sourceCollectionOpenAssignmentCount}</strong></span>
            <span>{lang === "zh" ? "查询" : "queries"} <strong>{sourceCollectionQueryCount}</strong></span>
            <span>{lang === "zh" ? "缓存" : "cache"} <strong>{sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}</strong></span>
          </div>
        </div>
        <details className={styles.workflowSourceCollectionDetails}>
          <summary>
            <span>{lang === "zh" ? "查询与分工详情" : "Query and assignment details"}</span>
            <small>
              {sourceCollectionAssignmentCount} {lang === "zh" ? "个任务" : "assignments"} · {sourceCollectionQueryCount} {lang === "zh" ? "条查询" : "queries"}
            </small>
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
                  <strong>{assignment.agentRole}</strong>
                  <span>{assignment.status} · {assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0} queries</span>
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
                  <strong>{query.query}</strong>
                  <small>{query.queryId} · {query.sourceType} · {query.language}</small>
                </span>
              ))}
            </div>
          ) : null}
        </details>
        <details className={styles.workflowSourceCollectionDetails}>
          <summary>
            <span>{lang === "zh" ? "兜底手工回写" : "Fallback manual writeback"}</span>
            <small>{lang === "zh" ? "Agent 未自动回写时使用" : "Use when Agent writeback is unavailable"}</small>
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
            <span>{lang === "zh" ? "生成 DataRecord 后自动导入 source_manifest 候选" : "Creates a DataRecord, then imports a source_manifest candidate"}</span>
          </div>
          <label>
            <span>Assignment</span>
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
        </details>
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
        {selectedTeamExecuteSourceCollectionSearchError ? (
          <div className={styles.messageError}>{selectedTeamExecuteSourceCollectionSearchError.message}</div>
        ) : null}
        {selectedTeamExecuteSourceCollectionSearchResult ? (
          <div className={styles.messageResult}>
            <strong>{lang === "zh" ? "搜索执行已回写" : "Search execution written"}</strong>
            <span>
              {selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} queries / {selectedTeamExecuteSourceCollectionSearchResult.recordCount} DataRecord / {selectedTeamExecuteSourceCollectionSearchResult.importedCount} candidate
            </span>
          </div>
        ) : null}
        {selectedTeamRecordSourceCollectionOutputResult ? (
          <div className={styles.messageResult}>
            <strong>{lang === "zh" ? "已回写" : "Written"}</strong>
            <span>
              {selectedTeamRecordSourceCollectionOutputResult.output.createdRecords.length} DataRecord / {selectedTeamRecordSourceCollectionOutputResult.imported.length} candidate
            </span>
          </div>
        ) : null}
      </section>
    );
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
  const sourceCollectionOpenAssignmentCount =
    sourceCollectionRunStatus?.summary.openAssignmentCount
    ?? sourceCollectionAssignments.filter((assignment) => ["open", "in_progress", "returned"].includes(assignment.status)).length;
  const sourceManifestCandidates = useMemo(
    () => teamWorkflowCandidates.filter((candidate) => candidate.candidateType === "source_manifest"),
    [teamWorkflowCandidates],
  );
  const sourceCollectionRecordCount = sourceCollectionRunStatus?.summary.recordCount ?? 0;
  const sourceCollectionAssignmentCount = sourceCollectionRunStatus?.summary.assignmentCount ?? sourceCollectionAssignments.length;
  const sourceCollectionQueryCount =
    sourceCollectionSearchPlanRef?.queryCount
    ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount
    ?? sourceCollectionAssignments.reduce((total, assignment) => total + (assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0), 0);
  const sourceCollectionApprovedCount = teamWorkflowSourceQualityStatus?.summary.approvedSourceCandidateCount ?? 0;
  const sourceCollectionStageFocusLabel = !selectedSourceCollectionRun
    ? (lang === "zh" ? "待启动" : "not started")
    : sourceCollectionOpenAssignmentCount > 0
      ? (lang === "zh" ? "搜集中" : "collecting")
      : sourceManifestCandidates.length > sourceCollectionApprovedCount
        ? (lang === "zh" ? "待筛选" : "screening needed")
        : sourceManifestCandidates.length > 0
          ? (lang === "zh" ? "可进入治理" : "ready for governance")
          : (lang === "zh" ? "待回写" : "waiting for writeback");
  const sourceCollectionNextActionHint = !selectedSourceCollectionRun
    ? (lang === "zh" ? "先启动资料搜集批次，生成查询计划和功能 Agent 分工。" : "Start a collection run to create query plans and functional-Agent assignments.")
    : sourceCollectionOpenAssignmentCount > 0
      ? (lang === "zh" ? "继续执行下一批搜索，把来源元数据写入候选资料仓库。" : "Run the next search batch and write source metadata into the candidate store.")
      : sourceManifestCandidates.length > sourceCollectionApprovedCount
        ? (lang === "zh" ? "进入资料筛选，决定哪些候选能支持后续科研提炼。" : "Move to source screening and decide which candidates can support research extraction.")
        : (lang === "zh" ? "当前轮可沉淀到后续知识治理或开启新一轮补充搜集。" : "This round can move into governance or start another collection round.");
  const sourceCollectionPrimaryActionTitle = selectedSourceCollectionRun
    ? (lang === "zh" ? "继续搜集" : "Continue collection")
    : (lang === "zh" ? "启动本轮资料搜集" : "Start this collection round");
  const sourceCollectionPrimaryActionBody = selectedSourceCollectionRun
    ? sourceCollectionNextActionHint
    : (lang === "zh" ? "填好主题和目标后，系统会生成 query、分配团队功能 Agent，并建立回写契约。" : "After topic and goal are set, the system creates queries, assigns functional Agents, and stores the writeback contract.");
  const sourceCollectionTraceMessages = useMemo<SourceCollectionTraceMessage[]>(() => {
    const messages: SourceCollectionTraceMessage[] = [];
    const runStorage = selectedSourceCollectionRun?.storage;
    messages.push({
      id: "coordination-plan",
      agentRole: "Research Coordination Agent",
      title: selectedSourceCollectionRun
        ? (lang === "zh" ? "已建立本轮资料搜集批次" : "Created the source collection run")
        : (lang === "zh" ? "等待启动资料搜集批次" : "Waiting for a source collection run"),
      body: selectedSourceCollectionRun
        ? `${lang === "zh" ? "目标" : "Goal"}: ${String(selectedSourceCollectionRun.scope?.goal || sourceCollectionDraft.goal || "-")}`
        : (lang === "zh" ? "点击启动后会生成查询计划、团队 Agent 分工和回写契约。" : "Starting creates a query plan, team-agent assignments, and a writeback contract."),
      status: selectedSourceCollectionRun?.status || (lang === "zh" ? "未启动" : "not started"),
      tone: selectedSourceCollectionRun ? "plan" : "blocked",
      refs: selectedSourceCollectionRun ? [selectedSourceCollectionRun.runId, String(selectedSourceCollectionRun.scope?.topic || sourceCollectionDraft.topic)] : [],
      storageRefs: runStorage ? [runStorage.runPath, runStorage.recordsPath] : [],
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
          ? `本轮使用 ${sourceCollectionPromptCachePolicy?.modelName || sourceCollectionPromptCachePolicyRef?.modelId || SOURCE_COLLECTION_PROMPT_CACHE_POLICY.modelId}，稳定前缀只放团队规则、schema 和回写边界；每次搜索只传当前 query、结果引用和存储位置，避免反复重放网页全文。`
          : `This run uses ${sourceCollectionPromptCachePolicy?.modelName || sourceCollectionPromptCachePolicyRef?.modelId || SOURCE_COLLECTION_PROMPT_CACHE_POLICY.modelId}. The stable prefix keeps team rules, schemas, and writeback boundaries; each search sends only the current query, result refs, and storage location.`,
        status: sourceCollectionPromptCacheStatusLabel(promptCacheGateStatus, lang),
        tone: promptCacheGateStatus === "blocked" ? "blocked" : "cache",
        refs: [
          `requirement: ${sourceCollectionPromptCacheRequirement}`,
          promptCacheMode ? `mode: ${promptCacheMode}` : "",
          "stable prefix: team rules + schema + boundary",
          "dynamic delta: query/result refs only",
        ].filter(Boolean),
        storageRefs: promptCacheRolePartitions.slice(0, 4).map((item) => `${item.agentRole}: ${item.promptCachePartition}`),
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
          ? `当前可见 ${plannedQueries.length || sourceCollectionSearchPlanRef?.queryCount || selectedTeamStartSourceCollectionResult?.searchPlan.queryCount || 0} 条 query，按资料类型和语言分配给功能 Agent；query 是动态增量，不会挤进稳定缓存前缀。`
          : `${plannedQueries.length || sourceCollectionSearchPlanRef?.queryCount || selectedTeamStartSourceCollectionResult?.searchPlan.queryCount || 0} visible queries are assigned by source type and language; queries are dynamic deltas outside the stable cached prefix.`,
        status: "planned",
        tone: "search",
        refs: plannedQueries.slice(0, 5).map((query) => `${query.query} · ${query.sourceType}/${query.language}`),
        storageRefs: [
          selectedSourceCollectionRun?.scope?.dataSearchPlanRef?.planId ? String(selectedSourceCollectionRun.scope.dataSearchPlanRef.planId) : "",
          ...plannedQueryCacheRefs.slice(0, 3).map((partition) => `KV ${partition}`),
        ].filter(Boolean),
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
          ? `本批执行 ${selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} 条 query，写入 ${selectedTeamExecuteSourceCollectionSearchResult.recordCount} 条 DataRecord，导入 ${selectedTeamExecuteSourceCollectionSearchResult.importedCount} 个 source_manifest 候选${failedCount ? `，${failedCount} 条需要补救` : ""}。`
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
          ? `${sourceCollectionAssignments.length} 个任务已分配，${sourceCollectionOpenAssignmentCount} 个仍可执行；功能 Agent 需要按对话式轨迹回写搜索词、来源、提炼结果和候选位置。`
          : `${sourceCollectionAssignments.length} assignments are allocated and ${sourceCollectionOpenAssignmentCount} remain runnable; functional Agents must write back searched terms, sources, extracted results, and candidate locations as trace messages.`,
        status: sourceCollectionOpenAssignmentCount ? "open" : "ready_for_screening",
        tone: sourceCollectionOpenAssignmentCount ? "acquire" : "quality",
        refs: [
          ...visibleAssignments.map((assignment) => `${assignment.agentRole}: ${assignment.status}`),
          ...assignedQueries.slice(0, 4).map((query) => query.query),
        ],
        storageRefs: visibleAssignments
          .map((assignment) => assignment.scope.promptCachePartition ? `${assignment.agentRole}: KV ${assignment.scope.promptCachePartition}` : assignment.assignmentId)
          .filter(Boolean),
      });
    }
    if (selectedTeamRecordSourceCollectionOutputResult) {
      const records = selectedTeamRecordSourceCollectionOutputResult.output.createdRecords;
      const outputRecord = selectedTeamRecordSourceCollectionOutputResult.output.output;
      messages.push({
        id: `writeback-${outputRecord.outputId}`,
        agentRole: outputRecord.agentRole || "Source Intake Agent",
        title: lang === "zh" ? "已把搜集结果写成 DataRecord" : "Wrote collected result as DataRecord",
        body: lang === "zh"
          ? `本次回写 ${records.length} 条 DataRecord，并导入 ${selectedTeamRecordSourceCollectionOutputResult.imported.length} 个 source_manifest 候选。`
          : `This writeback created ${records.length} DataRecords and imported ${selectedTeamRecordSourceCollectionOutputResult.imported.length} source_manifest candidates.`,
        status: outputRecord.status,
        tone: "storage",
        refs: records.slice(0, 4).map((record) => `${record.title || record.recordId} · ${record.sourceRef || record.rawLocation || record.sourceType}`),
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
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamStartResearchStageResult,
    selectedTeamStartSourceCollectionResult,
    sourceCollectionAssignments,
    sourceCollectionDraft.goal,
    sourceCollectionDraft.topic,
    sourceCollectionOpenAssignmentCount,
    sourceCollectionPromptCachePolicy,
    sourceCollectionPromptCachePolicyRef,
    sourceCollectionPromptCacheRequirement,
    sourceCollectionPromptCacheStatus,
    sourceCollectionSearchPlanRef,
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
    && sourceCollectionOpenAssignmentCount > 0
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
  const showWorkflowPanel = !aiSearchScopeTeamSelected && (!researchWorkflowTeamSelected || (!researchCanvasVisible && researchWorkspaceView !== "discussion"));
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
          <div>
            <p>{lang === "zh" ? "ai科学研究团队 / 知识搜集阶段" : "AI research team / knowledge collection stage"}</p>
            <h1>{lang === "zh" ? "知识搜集工作台" : "Knowledge collection workspace"}</h1>
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
            <section className={styles.sourceCollectionCommandBar}>
              <div>
                <strong>{selectedSourceCollectionRun?.title || sourceCollectionDraft.title}</strong>
                <span>
                  {selectedSourceCollectionRun
                    ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun.status}`
                    : (lang === "zh" ? "还没有启动本轮资料搜集。" : "No source collection run has started yet.")}
                </span>
                <p className={styles.sourceCollectionCommandInsight}>{sourceCollectionNextActionHint}</p>
              </div>
              <div className={styles.sourceCollectionCommandStats}>
                <span>{lang === "zh" ? "当前" : "stage"} <strong>{sourceCollectionStageFocusLabel}</strong></span>
                <span>{lang === "zh" ? "待处理" : "open"} <strong>{sourceCollectionOpenAssignmentCount}</strong></span>
                <span>{lang === "zh" ? "候选" : "candidates"} <strong>{sourceManifestCandidates.length}</strong></span>
                <span>{lang === "zh" ? "查询" : "queries"} <strong>{sourceCollectionQueryCount}</strong></span>
                <span>{lang === "zh" ? "缓存" : "cache"} <strong>{sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}</strong></span>
              </div>
            </section>
            {renderSourceCollectionRunNotice()}
            <section className={styles.sourceCollectionStageModules} aria-label={lang === "zh" ? "知识搜集内部模块" : "Knowledge collection modules"}>
              {(lang === "zh"
                ? [
                    ["资料搜集", "搜索、回写、入候选"],
                    ["资料筛选", "可信度与相关性"],
                    ["候选入库", "候选仍待审"],
                    ["候选图谱", "只看关系预览"],
                    ["共享记忆前审", "正式写入前门禁"],
                  ]
                : [
                    ["Source collection", "Search, writeback, candidate import"],
                    ["Source screening", "Reliability and relevance"],
                    ["Candidate ingestion", "Candidates still need review"],
                    ["Candidate graph", "Preview relations only"],
                    ["Shared-memory precheck", "Gate before formal write"],
                  ]
              ).map(([moduleName, moduleHint], index) => (
                <span
                  key={moduleName}
                  className={(
                    (index === 0 && (sourceCollectionOpenAssignmentCount > 0 || !sourceManifestCandidates.length))
                    || (index === 1 && sourceManifestCandidates.length > sourceCollectionApprovedCount && sourceCollectionOpenAssignmentCount <= 0)
                    || (index === 2 && sourceCollectionApprovedCount > 0)
                  ) ? styles.sourceCollectionStageModuleActive : ""}
                >
                  <strong>{String(index + 1).padStart(2, "0")}</strong>
                  <span className={styles.sourceCollectionStageModuleText}>
                    <b>{moduleName}</b>
                    <small>{moduleHint}</small>
                  </span>
                </span>
              ))}
            </section>
            <div className={styles.sourceCollectionPageGrid}>
              {renderSourceCollectionConversation()}
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
      <div className={workspaceClassName}>
        <aside className={styles.teamPanel}>
          <form
            className={styles.createForm}
            onSubmit={(event) => {
              event.preventDefault();
              const name = teamDraft.name.trim();
              if (!name) {
                setCreateTeamError(lang === "zh" ? "先填写团队名称，再创建团队。" : "Enter a team name before creating a Team.");
                teamNameInputRef.current?.focus();
                return;
              }
              setCreateTeamError("");
              createTeamMutation.mutate({ ...teamDraft, name });
            }}
          >
            <input
              ref={teamNameInputRef}
              value={teamDraft.name}
              onChange={(event) => {
                setTeamDraft((current) => ({ ...current, name: event.target.value }));
                if (createTeamError) {
                  setCreateTeamError("");
                }
              }}
              placeholder={lang === "zh" ? "新团队名称" : "New team name"}
              aria-invalid={Boolean(createTeamError && !teamDraft.name.trim())}
              aria-describedby="team-create-feedback"
            />
            <input
              value={teamDraft.purpose}
              onChange={(event) => setTeamDraft((current) => ({ ...current, purpose: event.target.value }))}
              placeholder={lang === "zh" ? "团队目的" : "Team purpose"}
            />
            <button type="submit" disabled={createTeamMutation.isPending}>
              <Plus size={14} />
              {createTeamMutation.isPending ? (lang === "zh" ? "创建中" : "Creating") : lang === "zh" ? "创建" : "Create"}
            </button>
            <p id="team-create-feedback" className={createTeamError ? styles.formError : styles.formHint}>
              {createTeamError || (lang === "zh" ? "填写团队名称后即可创建；成员可稍后在画布中绑定。" : "Enter a team name to create it; members can be bound later on the canvas.")}
            </p>
          </form>
          <section className={styles.templatePanel}>
            <div className={styles.templatePanelHeader}>
              <strong>{lang === "zh" ? "从模板创建" : "Create from template"}</strong>
              <span>{teamTemplatesQuery.data?.summary.templateCount ?? 0}</span>
            </div>
            {teamTemplatesQuery.isPending ? (
              <div className={styles.templateEmpty}>{lang === "zh" ? "正在读取团队模板..." : "Loading team templates..."}</div>
            ) : selectedTemplate ? (
              <div className={styles.templatePicker}>
                <select
                  className={styles.templateSelect}
                  value={selectedTemplate.templateId}
                  onChange={(event) => setSelectedTemplateId(event.target.value)}
                  aria-label={lang === "zh" ? "选择团队模板" : "Select team template"}
                >
                  {teamTemplates.map((template) => (
                    <option key={template.templateId} value={template.templateId}>
                      {template.name} · {template.roleCount} agents
                    </option>
                  ))}
                </select>
                <div className={styles.templatePreview}>
                  <div className={styles.templatePreviewHeader}>
                    <strong>{selectedTemplate.name}</strong>
                    <span>{selectedTemplate.roleCount} agents</span>
                  </div>
                  <p>{selectedTemplate.purpose || selectedTemplate.description}</p>
                  <div className={styles.templateMeta}>
                    <span>{selectedTemplate.chatRoom.mode}</span>
                    <span>{selectedTemplate.chatRoom.purpose}</span>
                  </div>
                </div>
                <button
                  type="button"
                  className={styles.templateCreateButton}
                  disabled={instantiateTeamTemplateMutation.isPending}
                  onClick={() => instantiateTeamTemplateMutation.mutate(selectedTemplate.templateId)}
                >
                  <Bot size={14} />
                  {instantiateTeamTemplateMutation.isPending
                    ? (lang === "zh" ? "创建中" : "Creating")
                    : (lang === "zh" ? "创建 Demo 团队" : "Create demo team")}
                </button>
              </div>
            ) : (
              <div className={styles.templateEmpty}>{lang === "zh" ? "暂无团队模板。" : "No team templates."}</div>
            )}
          </section>
          <div className={styles.teamList}>
            {visibleTeams.map((team) => (
              <button
                key={team.teamId}
                type="button"
                className={team.teamId === selectedTeam?.teamId ? `${styles.teamRow} ${styles.teamRowActive}` : styles.teamRow}
                onClick={() => selectTeamRecord(team)}
              >
                <strong>{team.name}</strong>
                <span>{team.purpose || team.teamId}</span>
                <small>{team.memberCount} agents · {formatTime(team.updatedAt, lang)}</small>
              </button>
            ))}
          </div>
        </aside>

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
                <strong>{lang === "zh" ? "先创建团队，再进入组织画布" : "Create a team before opening the canvas"}</strong>
                <p>
                  {lang === "zh"
                    ? "左侧可直接创建空团队或用模板生成 Demo 团队；创建后这里会切换为节点画布。"
                    : "Use the left rail to create a blank team or instantiate a demo template; the node canvas appears after creation."}
                </p>
                <div className={styles.emptyCanvasSteps}>
                  <span>{lang === "zh" ? "1 填团队名称" : "1 Name team"}</span>
                  <span>{lang === "zh" ? "2 创建或套模板" : "2 Create/template"}</span>
                  <span>{lang === "zh" ? "3 绑定 Agent" : "3 Bind agents"}</span>
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
                {renderResearchWorkspaceNav()}
                {renderResearchStageLauncher()}
              </>
            ) : null}
            {showNodeBindingPanel && !selectedTeam ? (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`}>
                <div className={styles.empty}>
                  {lang === "zh"
                    ? "暂无团队。请先在左侧创建团队或使用模板。"
                    : "No team yet. Create one or use a template from the left rail."}
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
                                ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionRunStatus?.summary.recordCount ?? 0} records / ${sourceCollectionAssignments.length} assignments`
                                : sourceCollectionRunsQuery.isPending
                                ? (lang === "zh" ? "读取批次中" : "loading runs")
                                : (lang === "zh" ? "等待启动批次" : "waiting for run")}
                            </span>
                          </div>
                          <span className={`${styles.workflowTag} ${workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}`}>
                            {sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || (lang === "zh" ? "未启动" : "not started")}
                          </span>
                        </div>
                        {renderSourceCollectionRunNotice()}
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
                            <span>{lang === "zh" ? "记录" : "records"} <strong>{sourceCollectionRunStatus?.summary.recordCount ?? 0}</strong></span>
                            <span>{lang === "zh" ? "任务" : "assignments"} <strong>{sourceCollectionRunStatus?.summary.assignmentCount ?? sourceCollectionAssignments.length}</strong></span>
                            <span>{lang === "zh" ? "未完成" : "open"} <strong>{sourceCollectionRunStatus?.summary.openAssignmentCount ?? 0}</strong></span>
                            <span>{lang === "zh" ? "queries" : "queries"} <strong>{sourceCollectionSearchPlanRef?.queryCount ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount ?? 0}</strong></span>
                            <span>KV <strong>{sourceCollectionPromptCacheStatusLabel(sourceCollectionPromptCacheStatus, lang)}{sourceCollectionPromptCacheMode ? ` · ${sourceCollectionPromptCacheMode}` : ""}</strong></span>
                          </div>
                        </div>
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
                        {selectedTeamAssessSourceQualityError ? (
                          <div className={styles.messageError}>{selectedTeamAssessSourceQualityError.message}</div>
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
                                        if (!selectedTeam?.teamId || assessSourceQualityMutation.isPending) {
                                          return;
                                        }
                                        assessSourceQualityMutation.mutate({
                                          teamId: selectedTeam.teamId,
                                          candidateId: candidate.candidateId,
                                          decision: "approved",
                                        });
                                      }}
                                      disabled={!selectedTeam?.teamId || assessSourceQualityMutation.isPending}
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
                                        if (!selectedTeam?.teamId || assessSourceQualityMutation.isPending) {
                                          return;
                                        }
                                        assessSourceQualityMutation.mutate({
                                          teamId: selectedTeam.teamId,
                                          candidateId: candidate.candidateId,
                                          decision: "needs_revision",
                                        });
                                      }}
                                      disabled={!selectedTeam?.teamId || assessSourceQualityMutation.isPending}
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
