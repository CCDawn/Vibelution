import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, Bot, Link2, Play, Plus, RefreshCw, Save, Send, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

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
  ChatRoomDetail,
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
  TeamTemplateInstantiatePayload,
  TeamTemplateListPayload,
  TeamWorkflowCandidateListPayload,
  TeamWorkflowOrchestration,
} from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
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
const LINKED_ROOM_ACTIVE_REFETCH_MS = 5_000;
const LINKED_ROOM_IDLE_REFETCH_MS = 30_000;
const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 8;
const TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT = 20;
const WORKFLOW_GRAPH_WIDTH = 620;
const WORKFLOW_GRAPH_MIN_HEIGHT = 170;
const WORKFLOW_GRAPH_NODE_WIDTH = 124;
const WORKFLOW_GRAPH_NODE_HEIGHT = 42;
const WORKFLOW_GRAPH_NODE_GAP = 18;
const WORKFLOW_GRAPH_MARGIN_X = 22;
const WORKFLOW_GRAPH_MARGIN_Y = 28;

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

function canvasFromTeam(team: Team | null): TeamOrganizationCanvas | null {
  if (!team || !team.canvas || !("nodes" in team.canvas)) {
    return null;
  }
  return team.canvas as TeamOrganizationCanvas;
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
    needs_revision: "需修订",
    needs_evidence: "补证据",
    needs_review: "待审核",
    in_progress: "推进中",
    pending: "待启动",
    ready: "已跑通",
  };
  const en: Record<string, string> = {
    empty: "empty",
    blocked: "blocked",
    needs_revision: "revision",
    needs_evidence: "evidence",
    needs_review: "review",
    in_progress: "in progress",
    pending: "pending",
    ready: "ready",
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

function workflowIngestionTone(value: string) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "ready" || normalized === "operational") {
    return styles.workflowTagReady;
  }
  if (normalized === "blocked" || normalized === "needs_revision") {
    return styles.workflowTagDanger;
  }
  if (normalized === "needs_review" || normalized === "needs_evidence" || normalized === "pending") {
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

export function TeamsRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const [searchParams, setSearchParams] = useSearchParams();
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
  const hasTeams = teams.length > 0;
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
  const effectiveTeamId = selectedTeamId || requestedTeamId || requestedAgentTeamId || teams[0]?.teamId || "";
  const teamDetailQuery = useQuery({
    queryKey: queryKeys.team(effectiveTeamId),
    queryFn: () => fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}`),
    enabled: Boolean(effectiveTeamId),
  });
  const selectedTeam = teamDetailQuery.data ?? teams.find((team) => team.teamId === effectiveTeamId) ?? null;
  const researchWorkflowTeamSelected = isResearchWorkflowTeam(selectedTeam);
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
    if (requestedTeamId && teams.some((team) => team.teamId === requestedTeamId)) {
      setSelectedTeamId(requestedTeamId);
      return;
    }
    if (requestedAgentTeamId && teams.some((team) => team.teamId === requestedAgentTeamId)) {
      setSelectedTeamId(requestedAgentTeamId);
      return;
    }
    if (!selectedTeamId && teams[0]) {
      setSelectedTeamId(teams[0].teamId);
    }
  }, [requestedAgentTeamId, requestedTeamId, selectedTeamId, teams]);

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
    onSuccess: (_team, teamId) => {
      setSelectedTeamId("");
      setSelectedNodeId("");
      setSearchParams({});
      void chatWorkspaceCache.afterTeamChanged(teamId);
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
  const selectedTeamBuildCandidateGraphPending =
    buildCandidateGraphMutation.isPending && buildCandidateGraphMutation.variables === selectedTeam?.teamId;
  const selectedTeamBuildCandidateGraphError =
    buildCandidateGraphMutation.variables === selectedTeam?.teamId && buildCandidateGraphMutation.error instanceof Error
      ? buildCandidateGraphMutation.error
      : null;
  const activeWorkflowItemCount = teamWorkflow?.activeWorkflowItems.length ?? 0;

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
        <span>{lang === "zh" ? "团队" : "Teams"} <strong>{teamsQuery.data?.summary.activeTeamCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "成员引用" : "Members"} <strong>{teamsQuery.data?.summary.memberCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "失效引用" : "Stale"} <strong>{teamsQuery.data?.summary.staleMemberCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "成员源" : "Member source"} <strong>Agent Center</strong></span>
      </div>

      <div className={hasTeams ? styles.workspace : `${styles.workspace} ${styles.workspaceEmpty}`}>
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
            {teams.map((team) => (
              <button
                key={team.teamId}
                type="button"
                className={team.teamId === selectedTeam?.teamId ? `${styles.teamRow} ${styles.teamRowActive}` : styles.teamRow}
                onClick={() => {
                  setSelectedTeamId(team.teamId);
                  setSearchParams({ team: team.teamId });
                  setSelectedNodeId("");
                }}
              >
                <strong>{team.name}</strong>
                <span>{team.purpose || team.teamId}</span>
                <small>{team.memberCount} agents · {formatTime(team.updatedAt, lang)}</small>
              </button>
            ))}
          </div>
        </aside>

        <main className={styles.canvasPanel}>
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

        <aside className={styles.inspector}>
          <div className={styles.inspectorHeader}>
            <strong>{lang === "zh" ? "节点绑定" : "Node binding"}</strong>
            {validation && !validation.valid ? <AlertTriangle size={16} /> : <Link2 size={16} />}
          </div>
          <div className={styles.inspectorBody}>
            {!selectedTeam ? (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`}>
                <div className={styles.empty}>
                  {lang === "zh"
                    ? "暂无团队。请先在左侧创建团队或使用模板。"
                    : "No team yet. Create one or use a template from the left rail."}
                </div>
              </section>
            ) : selectedNode ? (
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
            ) : (
              <section className={`${styles.nodeBindingSection} ${styles.nodeBindingPlaceholder}`} aria-busy={teamDetailQuery.isPending || workspaceQuery.isPending}>
                <div className={styles.empty}>
                  {teamDetailQuery.isPending || workspaceQuery.isPending
                    ? (lang === "zh" ? "正在读取团队节点..." : "Loading team nodes...")
                    : (lang === "zh" ? "创建或选择一个团队节点。" : "Create or select a team node.")}
                </div>
              </section>
            )}
              <section className={styles.workflowPanel}>
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
                      <div className={styles.workflowCoordinationPanel}>
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
                                        {item.transferId ? `${item.fromNode || "-"} -> ${item.toNode || "-"}` : workflowStateLabel(item.currentState, lang)}
                                        {" · "}
                                        {item.title || item.candidateType || item.candidateId}
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
                      <div className={styles.workflowIngestionPanel}>
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
                      <div className={styles.workflowGraphPanel}>
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
                      {teamWorkflowCandidates.length ? (
                        <div className={styles.workflowCandidateList}>
                          {teamWorkflowCandidates.map((candidate) => (
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
                              </div>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className={styles.empty}>
                          {lang === "zh" ? "候选仓库还没有资料、笔记或机制候选。" : "No sources, notes, or mechanism candidates yet."}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className={styles.empty}>{lang === "zh" ? "科研流程尚未初始化。" : "Research workflow is not initialized yet."}</div>
                  )
                ) : (
                  <div className={styles.empty}>
                    {lang === "zh" ? "选择 research-team / 科研团队后显示挑战杯科研流程。" : "Select research-team to view the Challenge Cup workflow."}
                  </div>
                )}
                {teamWorkflowQuery.error instanceof Error ? (
                  <div className={styles.messageError}>{teamWorkflowQuery.error.message}</div>
                ) : null}
                {teamWorkflowCandidatesQuery.error instanceof Error ? (
                  <div className={styles.messageError}>{teamWorkflowCandidatesQuery.error.message}</div>
                ) : null}
              </section>
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
        </aside>
      </div>
    </section>
  );
}
