import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CirclePlus,
  FastForward,
  GitBranchPlus,
  Link2,
  Lock,
  MousePointer2,
  Play,
  Redo2,
  Save,
  Trash2,
  Undo2,
  Unlock,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent, WheelEvent } from "react";
import { Link, type BlockerFunction, useBlocker } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  type WorkbenchExitGuardDetail,
  WORKBENCH_EXIT_GUARD_EVENT,
} from "../app/workbenchExitGuard";
import {
  ResearchAgentConfig,
  ResearchFlowCanvas,
  ResearchFlowEdge,
  ResearchFlowExecutionResponse,
  ResearchFlowNode,
  ResearchFlowValidation,
  ResearchFlowValidationIssue,
  ResearchDiscoverySessionList,
  ResearchPromptWorkspace,
} from "../api/types";
import styles from "./ResearchFlowCanvasRoute.module.css";

export type CanvasSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

export type CanvasHistory = {
  past: ResearchFlowCanvas[];
  future: ResearchFlowCanvas[];
};

type CommitDraftOptions = {
  selection?: CanvasSelection;
};

type ConnectState = {
  active: boolean;
  sourceId: string | null;
};

type DragState = {
  nodeId: string;
  originX: number;
  originY: number;
  startX: number;
  startY: number;
};

type PanState = {
  originX: number;
  originY: number;
  startOffsetX: number;
  startOffsetY: number;
};

type CanvasOffset = {
  x: number;
  y: number;
};

type EdgeEndpoint = "source" | "target";

type ReconnectState = {
  edgeId: string;
  endpoint: EdgeEndpoint;
  hoverNodeId: string | null;
};

type InspectorView = "properties" | "issues";

const NODE_WIDTH = 220;
const NODE_HEIGHT = 112;
const EDGE_NODE_GAP = 12;
const EDGE_CONTROL_MIN = 72;
const EDGE_CONTROL_MAX = 220;
const CANVAS_ZOOM_MIN = 0.5;
const CANVAS_ZOOM_MAX = 1.8;
const CANVAS_ZOOM_STEP = 0.1;
const CANVAS_HISTORY_LIMIT = 50;
const RESEARCH_CUSTOM_TEMPLATES_STORAGE_KEY = "vibelution.researchFlowCanvas.customTemplates.v1";

const STATUS_OPTIONS = [
  { value: "idle", label: "未开始" },
  { value: "ready", label: "就绪" },
  { value: "running", label: "运行中" },
  { value: "done", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "stale", label: "需复核" },
  { value: "needs_review", label: "待审查" },
  { value: "needs_input", label: "待输入" },
  { value: "needs_evidence", label: "缺证据" },
  { value: "blocked", label: "阻塞" },
  { value: "skipped", label: "跳过" },
] as const;

const NODE_TYPE_OPTIONS = [
  { value: "agent", label: "Agent" },
  { value: "decision", label: "判断" },
  { value: "artifact", label: "产物" },
  { value: "human", label: "人工" },
  { value: "tool", label: "工具" },
  { value: "evaluation", label: "评估" },
] as const;

const EDGE_TYPE_OPTIONS = [
  { value: "success", label: "正向推进", condition: "completed" },
  { value: "evidence_loop", label: "补证据回路", condition: "needs_evidence" },
  { value: "approval_gate", label: "审查通过", condition: "approved" },
  { value: "human_handoff", label: "人工确认", condition: "completed" },
  { value: "selection", label: "选题结果", condition: "selected" },
  { value: "failure", label: "失败分支", condition: "failed" },
  { value: "blocked", label: "阻塞分支", condition: "blocked" },
] as const;

const EDGE_CONDITION_OPTIONS = [
  { value: "completed", label: "节点完成" },
  { value: "needs_evidence", label: "证据不足" },
  { value: "approved", label: "审查通过" },
  { value: "selected", label: "人工已选" },
  { value: "failed", label: "执行失败" },
  { value: "blocked", label: "流程阻塞" },
] as const;

export const RESEARCH_EDGE_TEMPLATES: ResearchEdgeTemplate[] = [
  {
    key: "main_flow",
    group: "主流程",
    label: "主线推进",
    type: "success",
    condition: "completed",
    edgeLabel: "完成后继续",
    description: "节点正常完成后触发，向下游继续推进。",
  },
  {
    key: "evidence_backtrack",
    group: "主流程",
    label: "证据回路",
    type: "evidence_loop",
    condition: "needs_evidence",
    edgeLabel: "缺口补搜",
    description: "证据审查发现缺口时触发，回到上游补充证据。",
  },
  {
    key: "approval_gate",
    group: "主流程",
    label: "审查通过",
    type: "approval_gate",
    condition: "approved",
    edgeLabel: "审查通过",
    description: "证据审查返回通过结果时触发，进入下一步。",
  },
  {
    key: "human_handoff",
    group: "人工/异常",
    label: "人工确认",
    type: "human_handoff",
    condition: "completed",
    edgeLabel: "等待人工",
    description: "流程交给人工判断时触发，等待用户确认。",
  },
  {
    key: "selection",
    group: "人工/异常",
    label: "选题结果",
    type: "selection",
    condition: "selected",
    edgeLabel: "已选主题",
    description: "用户选定目标后触发，继续生成主题卡或产物。",
  },
  {
    key: "failure",
    group: "人工/异常",
    label: "失败分支",
    type: "failure",
    condition: "failed",
    edgeLabel: "执行失败",
    description: "节点执行失败时触发，用于错误收敛或修复路径。",
  },
  {
    key: "blocked",
    group: "人工/异常",
    label: "阻塞分支",
    type: "blocked",
    condition: "blocked",
    edgeLabel: "流程阻塞",
    description: "依赖不满足或条件不足时触发，表示流程暂时走不下去。",
  },
];

const FLOW_CONDITION_EDGE_TYPES: Record<string, string[]> = {
  completed: ["success", "human_handoff"],
  needs_evidence: ["evidence_loop"],
  approved: ["approval_gate"],
  selected: ["selection"],
  failed: ["failure"],
  blocked: ["blocked"],
};

const FLOW_NODE_ACTION_ALIASES: Record<string, string> = {
  broad_search: "broad",
  deep_search: "deep",
  evidence_review: "review",
  theme_generation: "themes",
  theme_card: "card",
  human_choice: "human_choice",
  knowledge_store: "knowledge_store",
  knowledge_lookup: "knowledge_lookup",
  literature_project_parse: "literature_project_parse",
  semantic_cluster: "semantic_cluster",
  novelty_reverse_check: "novelty_reverse_check",
};

type FlowContract = {
  inputs: string[][];
  outputs: Record<string, string[]>;
  terminal: boolean;
  expectedOutcomes?: string[];
};

const RESEARCH_FLOW_NODE_CONTRACTS: Record<string, FlowContract> = {
  broad: {
    inputs: [],
    outputs: {
      completed: ["sources", "research_leads", "knowledge_candidates"],
      needs_evidence: ["sources", "evidence_requests"],
    },
    terminal: false,
  },
  knowledge_store: {
    inputs: [["sources"], ["knowledge_candidates"]],
    outputs: {
      completed: ["knowledge_entries", "knowledge_context"],
    },
    terminal: false,
  },
  knowledge_lookup: {
    inputs: [["knowledge_entries"], ["sources"], ["knowledge_context"]],
    outputs: {
      completed: ["knowledge_context", "sources"],
    },
    terminal: false,
  },
  deep: {
    inputs: [["knowledge_context"], ["sources"], ["evidence_requests"], ["research_leads"]],
    outputs: {
      completed: ["sources", "evidence_context", "research_leads"],
    },
    terminal: false,
  },
  literature_project_parse: {
    inputs: [["sources"]],
    outputs: {
      completed: ["parsed_records", "source_signals"],
    },
    terminal: false,
  },
  semantic_cluster: {
    inputs: [["parsed_records"]],
    outputs: {
      completed: ["clusters", "gaps"],
    },
    terminal: false,
  },
  novelty_reverse_check: {
    inputs: [["clusters"], ["gaps"]],
    outputs: {
      completed: ["novelty_evidence", "evidence_context"],
    },
    terminal: false,
  },
  review: {
    inputs: [["novelty_evidence"], ["evidence_context"], ["sources"], ["parsed_records"]],
    outputs: {
      approved: ["approved_evidence"],
      needs_evidence: ["evidence_requests"],
      completed: ["approved_evidence"],
    },
    terminal: false,
    expectedOutcomes: ["approved", "needs_evidence"],
  },
  themes: {
    inputs: [["approved_evidence"]],
    outputs: {
      completed: ["candidate_themes"],
    },
    terminal: false,
  },
  human_choice: {
    inputs: [["candidate_themes"]],
    outputs: {
      selected: ["selected_theme"],
    },
    terminal: false,
  },
  card: {
    inputs: [["selected_theme"]],
    outputs: {
      completed: ["theme_card"],
    },
    terminal: true,
  },
};

type ResearchModuleTemplate = Pick<
  ResearchFlowNode,
  "label" | "type" | "status" | "agentKey" | "promptKey" | "llmConfigId" | "description" | "routeCondition"
> & {
  key: string;
  baseId: string;
  group: "能力模块" | "Agent模块" | "人工/产物" | "自定义模板";
};

type ResearchEdgeTemplate = {
  key: string;
  group: "主流程" | "人工/异常" | "自定义模板";
  label: string;
  type: ResearchFlowEdge["type"];
  condition: string;
  edgeLabel: string;
  description: string;
};

type ResearchCustomTemplates = {
  moduleTemplates: ResearchModuleTemplate[];
  edgeTemplates: ResearchEdgeTemplate[];
};

type ResearchTemplateStorage = Pick<Storage, "getItem" | "setItem">;

const DEFAULT_RESEARCH_MODULE_TEMPLATE_KEY = "knowledge_lookup";
const RESEARCH_MODULE_TEMPLATE_GROUPS: ResearchModuleTemplate["group"][] = ["能力模块", "Agent模块", "人工/产物", "自定义模板"];
const RESEARCH_EDGE_TEMPLATE_GROUPS: ResearchEdgeTemplate["group"][] = ["主流程", "人工/异常", "自定义模板"];

export const RESEARCH_MODULE_TEMPLATES: ResearchModuleTemplate[] = [
  {
    key: "knowledge_store",
    baseId: "knowledge_store",
    group: "能力模块",
    label: "科研知识入库",
    type: "tool",
    status: "idle",
    agentKey: "knowledge_store",
    promptKey: "",
    llmConfigId: "",
    description: "把搜索得到的来源、论断、证据和缺口写入 ResearchKnowledgeBase，供后续调研、自进化记忆和避免重复搜索复用。",
    routeCondition: "搜索完成后自动写入知识库。",
  },
  {
    key: "knowledge_lookup",
    baseId: "knowledge_lookup",
    group: "能力模块",
    label: "知识库检索",
    type: "tool",
    status: "idle",
    agentKey: "knowledge_lookup",
    promptKey: "",
    llmConfigId: "",
    description: "从本地科研知识库检索已有来源、论断、证据和缺口，给后续搜索提供上下文并减少重复搜索。",
    routeCondition: "知识入库完成后先查本地知识库。",
  },
  {
    key: "literature_project_parse",
    baseId: "literature_project_parse",
    group: "能力模块",
    label: "文献/项目解析",
    type: "tool",
    status: "idle",
    agentKey: "literature_project_parse",
    promptKey: "",
    llmConfigId: "",
    description: "对论文、PDF、GitHub README 和项目结构做结构化解析，提取方法、数据集、指标、限制和可复用组件。",
    routeCondition: "深搜拿到文献、项目或数据集来源后解析。",
  },
  {
    key: "semantic_cluster",
    baseId: "semantic_cluster",
    group: "能力模块",
    label: "语义去重与聚类",
    type: "tool",
    status: "idle",
    agentKey: "semantic_cluster",
    promptKey: "",
    llmConfigId: "",
    description: "对来源、论断和候选问题做去重、聚类和低密度空白识别，减少重复证据并暴露交叉创新点。",
    routeCondition: "解析完成后进行语义去重和簇级空白发现。",
  },
  {
    key: "novelty_reverse_check",
    baseId: "novelty_reverse_check",
    group: "能力模块",
    label: "新颖性反查",
    type: "tool",
    status: "idle",
    agentKey: "novelty_reverse_check",
    promptKey: "",
    llmConfigId: "",
    description: "围绕候选问题、关键词和机制组合反向检索论文、网页和 GitHub，标记已有相似工作与仍未覆盖的缺口。",
    routeCondition: "聚类后对高潜力空白做反向查重。",
  },
  {
    key: "broad_search",
    baseId: "broad_search",
    group: "Agent模块",
    label: "广撒网探索",
    type: "agent",
    status: "idle",
    agentKey: "broad",
    promptKey: "broad",
    llmConfigId: "research_broad",
    description: "从开放目标出发，让 agent 使用真实网络和工具发现跨学科候选方向。",
    routeCondition: "输入开放目标、约束和偏好后启动。",
  },
  {
    key: "deep_search",
    baseId: "deep_search",
    group: "Agent模块",
    label: "定向深搜",
    type: "agent",
    status: "idle",
    agentKey: "deep",
    promptKey: "deep",
    llmConfigId: "research_deep",
    description: "围绕上一阶段发现的关键缺口、论文、GitHub 项目和数据集补充证据。",
    routeCondition: "有候选线索或知识上下文后继续。",
  },
  {
    key: "evidence_review",
    baseId: "evidence_review",
    group: "Agent模块",
    label: "证据审查",
    type: "agent",
    status: "idle",
    agentKey: "review",
    promptKey: "review",
    llmConfigId: "research_review",
    description: "审查来源可靠性、论断可追溯性和缺失证据，决定是否回到补搜。",
    routeCondition: "证据链或新颖性反查结果准备完成后进入。",
  },
  {
    key: "theme_generation",
    baseId: "theme_generation",
    group: "Agent模块",
    label: "主题生成",
    type: "agent",
    status: "idle",
    agentKey: "themes",
    promptKey: "themes",
    llmConfigId: "research_themes",
    description: "基于证据链生成可证伪、新颖且扣题的科研主题候选。",
    routeCondition: "证据审查通过或用户手动确认继续。",
  },
  {
    key: "human_choice",
    baseId: "human_choice",
    group: "人工/产物",
    label: "人工选题确认",
    type: "human",
    status: "idle",
    agentKey: "",
    promptKey: "",
    llmConfigId: "",
    description: "用户比较候选主题卡，选择最值得推进的方向。",
    routeCondition: "主题候选生成后等待确认。",
  },
  {
    key: "theme_card",
    baseId: "theme_card",
    group: "人工/产物",
    label: "正式主题卡",
    type: "artifact",
    status: "idle",
    agentKey: "card",
    promptKey: "card",
    llmConfigId: "research_card",
    description: "产出赛题要求的科学假设与研究计划结构，包括数据集、方法、实验、指标和参考文献。",
    routeCondition: "用户确认主题后生成。",
  },
];

function cloneCanvas(canvas: ResearchFlowCanvas): ResearchFlowCanvas {
  return {
    ...canvas,
    viewport: { ...canvas.viewport },
    nodes: canvas.nodes.map((node) => ({ ...node })),
    edges: canvas.edges.map((edge) => ({ ...edge })),
  };
}

function canvasSignature(canvas: ResearchFlowCanvas | null) {
  if (!canvas) {
    return "";
  }
  return JSON.stringify({
    viewport: canvas.viewport,
    nodes: canvas.nodes,
    edges: canvas.edges,
  });
}

export function pushCanvasHistory(history: CanvasHistory, snapshot: ResearchFlowCanvas, limit = CANVAS_HISTORY_LIMIT): CanvasHistory {
  const previous = history.past.at(-1);
  if (previous && canvasSignature(previous) === canvasSignature(snapshot)) {
    return history;
  }
  return {
    past: [...history.past, cloneCanvas(snapshot)].slice(-limit),
    future: [],
  };
}

export function stepCanvasHistory(
  history: CanvasHistory,
  current: ResearchFlowCanvas,
  direction: "undo" | "redo",
  limit = CANVAS_HISTORY_LIMIT,
): { canvas: ResearchFlowCanvas; history: CanvasHistory } | null {
  if (direction === "undo") {
    const previous = history.past.at(-1);
    if (!previous) {
      return null;
    }
    return {
      canvas: cloneCanvas(previous),
      history: {
        past: history.past.slice(0, -1),
        future: [cloneCanvas(current), ...history.future],
      },
    };
  }
  const next = history.future[0];
  if (!next) {
    return null;
  }
  return {
    canvas: cloneCanvas(next),
    history: {
      past: [...history.past, cloneCanvas(current)].slice(-limit),
      future: history.future.slice(1),
    },
  };
}

export function clampCanvasZoom(zoom: number) {
  return Math.max(CANVAS_ZOOM_MIN, Math.min(CANVAS_ZOOM_MAX, Number(zoom.toFixed(2))));
}

export function canvasViewportFromView(offset: CanvasOffset, zoom: number) {
  return {
    x: Math.round(offset.x),
    y: Math.round(offset.y),
    zoom: clampCanvasZoom(zoom),
  };
}

export function isValidEdgeReconnectTarget(edge: Pick<ResearchFlowEdge, "source" | "target">, endpoint: EdgeEndpoint, nodeId: string) {
  if (!nodeId) {
    return false;
  }
  return endpoint === "source" ? nodeId !== edge.target : nodeId !== edge.source;
}

export function shouldBlockCanvasLeave({
  dirty,
  saving,
  currentPathname,
  nextPathname,
}: {
  dirty: boolean;
  saving: boolean;
  currentPathname: string;
  nextPathname: string;
}) {
  return (dirty || saving) && currentPathname !== nextPathname;
}

export function researchFlowExecutionBlockReason({
  sessionId,
  sessionLoading,
  canvasLocked,
  dirty,
  executing,
  validationErrorCount,
}: {
  sessionId: string;
  sessionLoading: boolean;
  canvasLocked: boolean;
  dirty: boolean;
  executing: boolean;
  validationErrorCount: number;
}) {
  if (executing) {
    return "节点正在执行中，请等待当前执行完成。";
  }
  if (!sessionId) {
    return sessionLoading ? "科研会话正在加载，加载完成后即可执行。" : "先选择一个科研会话后再执行。";
  }
  if (dirty) {
    return "画布有未保存修改，先保存后再执行。";
  }
  if (validationErrorCount > 0) {
    return "当前画布存在契约错误，先修复输入输出和路由规则。";
  }
  if (!canvasLocked) {
    return "先锁定画布进入观察模式，再执行科研流程。";
  }
  return "";
}

export function researchFlowLockBlockReason({
  draftReady,
  dirty,
  saving,
  executing,
  validationErrorCount,
}: {
  draftReady: boolean;
  dirty: boolean;
  saving: boolean;
  executing: boolean;
  validationErrorCount: number;
}) {
  if (!draftReady) {
    return "画布加载完成后才能锁定观察。";
  }
  if (executing) {
    return "节点执行中，完成后才能解除锁定。";
  }
  if (saving) {
    return "画布正在保存，保存完成后才能锁定。";
  }
  if (dirty) {
    return "画布有未保存修改，先保存后再锁定。";
  }
  if (validationErrorCount > 0) {
    return "当前画布存在契约错误，先修复后再锁定。";
  }
  return "";
}

export function summarizeDeleteImpact(canvas: Pick<ResearchFlowCanvas, "nodes" | "edges"> | null, selection: CanvasSelection) {
  if (!canvas || !selection) {
    return {
      canDelete: false,
      subject: "未选择对象",
      detail: "先选择一个模块或路由。",
      connectedEdgeCount: 0,
    };
  }
  if (selection.kind === "node") {
    const node = canvas.nodes.find((item) => item.id === selection.id);
    if (!node) {
      return {
        canDelete: false,
        subject: "模块不存在",
        detail: "当前选择已不在画布中。",
        connectedEdgeCount: 0,
      };
    }
    if (canvas.nodes.length <= 1) {
      return {
        canDelete: false,
        subject: `模块「${node.label || node.id}」`,
        detail: "至少保留一个模块，不能把画布删空。",
        connectedEdgeCount: 0,
      };
    }
    const connectedEdgeCount = canvas.edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
    return {
      canDelete: true,
      subject: `模块「${node.label || node.id}」`,
      detail: connectedEdgeCount ? `将同时删除 ${connectedEdgeCount} 条关联路由。` : "不会删除其他路由。",
      connectedEdgeCount,
    };
  }
  const edge = canvas.edges.find((item) => item.id === selection.id);
  if (!edge) {
    return {
      canDelete: false,
      subject: "路由不存在",
      detail: "当前选择已不在画布中。",
      connectedEdgeCount: 0,
    };
  }
  return {
    canDelete: true,
    subject: `路由「${edge.label || edge.id}」`,
    detail: "只删除这条路由，不影响两端模块。",
    connectedEdgeCount: 0,
  };
}

export function deleteCanvasSelection<T extends Pick<ResearchFlowCanvas, "nodes" | "edges">>(canvas: T, selection: CanvasSelection): T {
  if (!selection) {
    return canvas;
  }
  if (selection.kind === "node") {
    return {
      ...canvas,
      nodes: canvas.nodes.filter((node) => node.id !== selection.id),
      edges: canvas.edges.filter((edge) => edge.source !== selection.id && edge.target !== selection.id),
    };
  }
  return {
    ...canvas,
    edges: canvas.edges.filter((edge) => edge.id !== selection.id),
  };
}

function selectionExists(canvas: ResearchFlowCanvas, selection: CanvasSelection) {
  if (!selection) {
    return false;
  }
  return selection.kind === "node"
    ? canvas.nodes.some((node) => node.id === selection.id)
    : canvas.edges.some((edge) => edge.id === selection.id);
}

export function sameCanvasSelection(left: CanvasSelection, right: CanvasSelection) {
  return Boolean(left && right && left.kind === right.kind && left.id === right.id);
}

function viewportOffset(viewport: ResearchFlowCanvas["viewport"]): CanvasOffset {
  return {
    x: Number.isFinite(viewport?.x) ? viewport.x : 0,
    y: Number.isFinite(viewport?.y) ? viewport.y : 0,
  };
}

function pointInNode(point: CanvasPoint, node: ResearchFlowNode) {
  return point.x >= node.x && point.x <= node.x + NODE_WIDTH && point.y >= node.y && point.y <= node.y + NODE_HEIGHT;
}

type CanvasPoint = {
  x: number;
  y: number;
};

type EdgeGeometry = {
  start: CanvasPoint;
  end: CanvasPoint;
  controlStart: CanvasPoint;
  controlEnd: CanvasPoint;
  label: CanvasPoint;
  points: CanvasPoint[];
  arrowHead: string;
  path: string;
  laneIndex: number;
  overlapCount: number;
};

type EdgeLane = {
  laneIndex: number;
  overlapCount: number;
};

type EdgeVisualStyle = {
  stroke: string;
  fill: string;
  strokeDasharray?: string;
  strokeWidth: number;
};

function nodeCenter(node: ResearchFlowNode): CanvasPoint {
  return {
    x: node.x + NODE_WIDTH / 2,
    y: node.y + NODE_HEIGHT / 2,
  };
}

function boundaryAnchor(from: ResearchFlowNode, to: ResearchFlowNode, direction: 1 | -1): CanvasPoint {
  const fromCenter = nodeCenter(from);
  const toCenter = nodeCenter(to);
  const dx = (toCenter.x - fromCenter.x) * direction;
  const dy = (toCenter.y - fromCenter.y) * direction;
  if (dx === 0 && dy === 0) {
    return { x: fromCenter.x, y: fromCenter.y };
  }
  const halfWidth = NODE_WIDTH / 2;
  const halfHeight = NODE_HEIGHT / 2;
  const scaleX = dx === 0 ? Number.POSITIVE_INFINITY : halfWidth / Math.abs(dx);
  const scaleY = dy === 0 ? Number.POSITIVE_INFINITY : halfHeight / Math.abs(dy);
  const scale = Math.min(scaleX, scaleY);
  const length = Math.hypot(dx, dy) || 1;
  const boundary = {
    x: fromCenter.x + dx * scale,
    y: fromCenter.y + dy * scale,
  };
  return {
    x: boundary.x + (dx / length) * EDGE_NODE_GAP,
    y: boundary.y + (dy / length) * EDGE_NODE_GAP,
  };
}

function cubicPoint(p0: CanvasPoint, p1: CanvasPoint, p2: CanvasPoint, p3: CanvasPoint, t: number): CanvasPoint {
  const inv = 1 - t;
  return {
    x: inv ** 3 * p0.x + 3 * inv ** 2 * t * p1.x + 3 * inv * t ** 2 * p2.x + t ** 3 * p3.x,
    y: inv ** 3 * p0.y + 3 * inv ** 2 * t * p1.y + 3 * inv * t ** 2 * p2.y + t ** 3 * p3.y,
  };
}

function sampleCubic(start: CanvasPoint, controlStart: CanvasPoint, controlEnd: CanvasPoint, end: CanvasPoint): CanvasPoint[] {
  return Array.from({ length: 17 }, (_, index) => cubicPoint(start, controlStart, controlEnd, end, index / 16));
}

function arrowHeadPoints(tip: CanvasPoint, control: CanvasPoint) {
  const dx = tip.x - control.x;
  const dy = tip.y - control.y;
  const length = Math.hypot(dx, dy) || 1;
  const unit = { x: dx / length, y: dy / length };
  const normal = { x: -unit.y, y: unit.x };
  const arrowLength = 15;
  const arrowWidth = 10;
  const base = {
    x: tip.x - unit.x * arrowLength,
    y: tip.y - unit.y * arrowLength,
  };
  const left = {
    x: base.x + normal.x * (arrowWidth / 2),
    y: base.y + normal.y * (arrowWidth / 2),
  };
  const right = {
    x: base.x - normal.x * (arrowWidth / 2),
    y: base.y - normal.y * (arrowWidth / 2),
  };
  return `${tip.x},${tip.y} ${left.x},${left.y} ${right.x},${right.y}`;
}

function edgeGeometry(source: ResearchFlowNode, target: ResearchFlowNode, lane: EdgeLane = { laneIndex: 0, overlapCount: 0 }): EdgeGeometry {
  const sourceCenter = nodeCenter(source);
  const targetCenter = nodeCenter(target);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const directionX = dx >= 0 ? 1 : -1;
  const directionY = dy >= 0 ? 1 : -1;
  const length = Math.hypot(dx, dy) || 1;
  const normal = { x: -dy / length, y: dx / length };
  const laneOffset = lane.laneIndex * 30 + lane.overlapCount * 16 * (lane.laneIndex >= 0 ? 1 : -1);
  const startBase = boundaryAnchor(source, target, 1);
  const endBase = boundaryAnchor(target, source, 1);
  const start = { x: startBase.x + normal.x * laneOffset, y: startBase.y + normal.y * laneOffset };
  const end = { x: endBase.x + normal.x * laneOffset, y: endBase.y + normal.y * laneOffset };
  const spread = Math.min(
    EDGE_CONTROL_MAX,
    Math.max(EDGE_CONTROL_MIN, horizontal ? Math.abs(end.x - start.x) / 2 : Math.abs(end.y - start.y) / 2),
  );
  const arcOffset = Math.abs(laneOffset) + (lane.overlapCount ? 28 : 0);
  const controlStart = horizontal
    ? { x: start.x + directionX * spread, y: start.y + normal.y * arcOffset }
    : { x: start.x + normal.x * arcOffset, y: start.y + directionY * spread };
  const controlEnd = horizontal
    ? { x: end.x - directionX * spread, y: end.y + normal.y * arcOffset }
    : { x: end.x + normal.x * arcOffset, y: end.y - directionY * spread };
  const labelCenter = {
    x: (start.x + controlStart.x + controlEnd.x + end.x) / 4,
    y: (start.y + controlStart.y + controlEnd.y + end.y) / 4,
  };
  const labelDirection = lane.laneIndex < 0 ? -1 : 1;
  const labelOffset = 42 + Math.min(30, Math.abs(laneOffset));
  const label = {
    x: labelCenter.x + normal.x * labelOffset * labelDirection,
    y: labelCenter.y + normal.y * labelOffset * labelDirection,
  };
  const points = sampleCubic(start, controlStart, controlEnd, end);
  return {
    start,
    end,
    controlStart,
    controlEnd,
    label,
    points,
    arrowHead: arrowHeadPoints(end, controlEnd),
    path: `M ${start.x} ${start.y} C ${controlStart.x} ${controlStart.y}, ${controlEnd.x} ${controlEnd.y}, ${end.x} ${end.y}`,
    laneIndex: lane.laneIndex,
    overlapCount: lane.overlapCount,
  };
}

function pointInsideNode(point: CanvasPoint, node: ResearchFlowNode, padding = 10) {
  return (
    point.x >= node.x - padding &&
    point.x <= node.x + NODE_WIDTH + padding &&
    point.y >= node.y - padding &&
    point.y <= node.y + NODE_HEIGHT + padding
  );
}

function pathIntersectsNode(points: CanvasPoint[], node: ResearchFlowNode) {
  return points.some((point) => pointInsideNode(point, node));
}

function distancePointToSegment(point: CanvasPoint, start: CanvasPoint, end: CanvasPoint) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared));
  const projection = { x: start.x + t * dx, y: start.y + t * dy };
  return Math.hypot(point.x - projection.x, point.y - projection.y);
}

function detectEdgeOverlap(left: CanvasPoint[], right: CanvasPoint[]) {
  return left.some((point) =>
    right.slice(1).some((segmentEnd, index) => distancePointToSegment(point, right[index], segmentEnd) < 14),
  );
}

function resolveEdgeLanes(edges: ResearchFlowEdge[], nodes: ResearchFlowNode[]) {
  const lanes = new Map<string, EdgeLane>();
  const byPair = new Map<string, ResearchFlowEdge[]>();
  for (const edge of edges) {
    const pairKey = [edge.source, edge.target].sort().join("::");
    byPair.set(pairKey, [...(byPair.get(pairKey) ?? []), edge]);
  }
  for (const pairEdges of byPair.values()) {
    const sorted = [...pairEdges].sort((left, right) => `${left.source}:${left.target}:${left.id}`.localeCompare(`${right.source}:${right.target}:${right.id}`));
    sorted.forEach((edge, index) => {
      lanes.set(edge.id, { laneIndex: sorted.length === 1 ? 0 : index - (sorted.length - 1) / 2, overlapCount: 0 });
    });
  }

  const geometries: Array<{ edge: ResearchFlowEdge; geometry: EdgeGeometry }> = [];
  for (const edge of edges) {
    const source = nodes.find((node) => node.id === edge.source);
    const target = nodes.find((node) => node.id === edge.target);
    if (!source || !target) {
      continue;
    }
    const lane = lanes.get(edge.id) ?? { laneIndex: 0, overlapCount: 0 };
    let geometry = edgeGeometry(source, target, lane);
    const crossesNode = nodes.some((node) => node.id !== edge.source && node.id !== edge.target && pathIntersectsNode(geometry.points, node));
    const overlapsEdge = geometries.some((item) => item.edge.source !== edge.source || item.edge.target !== edge.target ? detectEdgeOverlap(geometry.points, item.geometry.points) : false);
    if (crossesNode || overlapsEdge) {
      const nextLane = { laneIndex: lane.laneIndex || 1, overlapCount: lane.overlapCount + 1 };
      lanes.set(edge.id, nextLane);
      geometry = edgeGeometry(source, target, nextLane);
    }
    geometries.push({ edge, geometry });
  }
  return lanes;
}

function statusLabel(status: string) {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

function statusClass(status: string) {
  return styles[`status_${status}` as keyof typeof styles] ?? styles.status_idle;
}

function nodeStatusToneClass(status: string) {
  return styles[`nodeStatus_${status}` as keyof typeof styles] ?? styles.nodeStatus_idle;
}

function edgeTypeLabel(type: string) {
  return EDGE_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? "正向推进";
}

export function normalizeEdgeCondition(condition: string) {
  const normalized = condition.trim().toLowerCase();
  return EDGE_CONDITION_OPTIONS.some((option) => option.value === normalized) ? normalized : "completed";
}

function edgeConditionLabel(condition: string) {
  const normalized = normalizeEdgeCondition(condition);
  return EDGE_CONDITION_OPTIONS.find((option) => option.value === normalized)?.label ?? "节点完成";
}

export function readableResearchFlowIssueMessage(issue: Pick<ResearchFlowValidationIssue, "message">) {
  return String(issue.message || "")
    .replace(/\bneeds_evidence\b/g, edgeConditionLabel("needs_evidence"))
    .replace(/\bcompleted\b/g, edgeConditionLabel("completed"))
    .replace(/\bapproved\b/g, edgeConditionLabel("approved"))
    .replace(/\bselected\b/g, edgeConditionLabel("selected"))
    .replace(/\bfailed\b/g, edgeConditionLabel("failed"))
    .replace(/\bblocked\b/g, edgeConditionLabel("blocked"));
}

export function researchFlowIssueAdvice(issue: Pick<ResearchFlowValidationIssue, "code" | "severity">) {
  if (issue.code === "node_missing_outcome_route") {
    return "为该模块补一条匹配缺失结果的路由，或调整模块输出契约。";
  }
  if (issue.code === "node_missing_required_input") {
    return "从能产出所需上下文的上游模块连入此模块。";
  }
  if (issue.code === "edge_contract_mismatch") {
    return "检查起点输出、终点输入和触发条件是否匹配。";
  }
  if (issue.code === "edge_condition_type_mismatch") {
    return "让箭头类型和触发条件保持同一种语义。";
  }
  if (issue.code === "flow_missing_start_node") {
    return "保留至少一个没有上游依赖的起点模块。";
  }
  if (issue.code === "node_unreachable") {
    return "把该模块接回从起点可到达的主流程。";
  }
  if (issue.code === "duplicate_edge_pair") {
    return "删除重复路由，或为其中一条设置不同触发条件。";
  }
  if (issue.code === "duplicate_edge_id") {
    return "删除重复路由后重新添加，生成唯一 ID。";
  }
  if (issue.code === "self_loop") {
    return "把这条路由连接到另一个模块，避免模块指向自身。";
  }
  return issue.severity === "error" ? "先修复此项，否则画布不能保存和执行。" : "建议修正此项，避免执行时进入意外分支。";
}

function edgeConditionDescription(condition: string) {
  const normalized = normalizeEdgeCondition(condition);
  if (normalized === "needs_evidence") return "当节点返回缺证据时触发，通常会把流程送回补搜节点。";
  if (normalized === "approved") return "当审查节点返回通过时触发，说明证据已经足够。";
  if (normalized === "selected") return "当人工完成选题时触发，通常继续生成主题卡。";
  if (normalized === "failed") return "当节点执行失败时触发，用于进入失败处理路径。";
  if (normalized === "blocked") return "当依赖不足或流程卡住时触发，表示当前分支暂时走不下去。";
  return "当节点正常完成时触发，是最常见的正向推进条件。";
}

function edgeTypeDescription(type: string) {
  if (type === "evidence_loop") return "回路线：用于证据不足时回到上游补搜。";
  if (type === "approval_gate") return "门禁线：用于审查通过后再进入下一模块。";
  if (type === "human_handoff") return "人工线：用于把流程交给用户确认。";
  if (type === "selection") return "选定线：用于人工已选定之后继续下游流程。";
  if (type === "failure") return "失败线：用于节点异常或执行失败时的兜底分支。";
  if (type === "blocked") return "阻塞线：用于依赖不足或流程走不通时的兜底分支。";
  return "主线：节点正常完成后继续向下游推进。";
}

function edgeTypeClass(type: string) {
  return styles[`edgeType_${type}` as keyof typeof styles] ?? styles.edgeType_success;
}

function edgeVisualStyle(type: string, active = false): EdgeVisualStyle {
  if (active) {
    return { stroke: "#63d7ff", fill: "#63d7ff", strokeWidth: 3.4 };
  }
  if (type === "evidence_loop") {
    return { stroke: "#f5a524", fill: "#f5a524", strokeDasharray: "8 6", strokeWidth: 2.8 };
  }
  if (type === "approval_gate") {
    return { stroke: "#42d392", fill: "#42d392", strokeWidth: 3 };
  }
  if (type === "human_handoff") {
    return { stroke: "#f97316", fill: "#f97316", strokeDasharray: "3 5", strokeWidth: 2.8 };
  }
  if (type === "selection") {
    return { stroke: "#2dd4bf", fill: "#2dd4bf", strokeWidth: 3 };
  }
  if (type === "failure" || type === "blocked") {
    return { stroke: "#f87171", fill: "#f87171", strokeDasharray: "10 5", strokeWidth: 2.9 };
  }
  return { stroke: "#7dd3fc", fill: "#7dd3fc", strokeWidth: 2.8 };
}

function defaultEdgeTypeForCondition(condition: string) {
  const normalized = normalizeEdgeCondition(condition);
  if (normalized === "needs_evidence") return "evidence_loop";
  if (normalized === "approved") return "approval_gate";
  if (normalized === "selected") return "selection";
  if (normalized === "failed") return "failure";
  if (normalized === "blocked") return "blocked";
  return "success";
}

function edgeTypeMatchesCondition(condition: string, type: string) {
  const normalized = normalizeEdgeCondition(condition);
  const allowedTypes = FLOW_CONDITION_EDGE_TYPES[normalized] ?? [];
  return !allowedTypes.length || allowedTypes.includes(type || defaultEdgeTypeForCondition(normalized));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function safeTemplateIdPart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function browserResearchTemplateStorage(): ResearchTemplateStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function normalizeNodeTemplateType(value: unknown): ResearchFlowNode["type"] {
  const text = stringField(value, "agent");
  return NODE_TYPE_OPTIONS.some((option) => option.value === text) ? text : "agent";
}

function normalizeNodeTemplateStatus(value: unknown): ResearchFlowNode["status"] {
  const text = stringField(value, "idle");
  return STATUS_OPTIONS.some((option) => option.value === text) ? text : "idle";
}

function normalizeEdgeTemplateType(value: unknown, condition: string): ResearchFlowEdge["type"] {
  const text = stringField(value, defaultEdgeTypeForCondition(condition));
  return EDGE_TYPE_OPTIONS.some((option) => option.value === text) && edgeTypeMatchesCondition(condition, text)
    ? text
    : defaultEdgeTypeForCondition(condition);
}

function sanitizeCustomModuleTemplate(value: unknown, index: number): ResearchModuleTemplate | null {
  if (!isRecord(value)) {
    return null;
  }
  const baseId = safeTemplateIdPart(stringField(value.baseId, stringField(value.key, `custom_module_${index + 1}`))) || `custom_module_${index + 1}`;
  const key = safeTemplateIdPart(stringField(value.key, `custom_module_${baseId}`)) || `custom_module_${baseId}`;
  return {
    key,
    baseId,
    group: "自定义模板",
    label: stringField(value.label, "自定义模块").trim() || "自定义模块",
    type: normalizeNodeTemplateType(value.type),
    status: normalizeNodeTemplateStatus(value.status),
    agentKey: stringField(value.agentKey),
    promptKey: stringField(value.promptKey),
    llmConfigId: stringField(value.llmConfigId),
    description: stringField(value.description),
    routeCondition: stringField(value.routeCondition),
  };
}

function sanitizeCustomEdgeTemplate(value: unknown, index: number): ResearchEdgeTemplate | null {
  if (!isRecord(value)) {
    return null;
  }
  const condition = normalizeEdgeCondition(stringField(value.condition, "completed"));
  const type = normalizeEdgeTemplateType(value.type, condition);
  const key = safeTemplateIdPart(stringField(value.key, `custom_edge_${index + 1}`)) || `custom_edge_${index + 1}`;
  return {
    key,
    group: "自定义模板",
    label: stringField(value.label, "自定义连线").trim() || "自定义连线",
    type,
    condition,
    edgeLabel: stringField(value.edgeLabel, stringField(value.label, "自定义连线")).trim() || "自定义连线",
    description: stringField(value.description, edgeConditionDescription(condition)),
  };
}

export function readCustomResearchTemplates(storage: ResearchTemplateStorage | null = browserResearchTemplateStorage()): ResearchCustomTemplates {
  if (!storage) {
    return { moduleTemplates: [], edgeTemplates: [] };
  }
  try {
    const raw = storage.getItem(RESEARCH_CUSTOM_TEMPLATES_STORAGE_KEY);
    const payload = raw ? JSON.parse(raw) : null;
    if (!isRecord(payload)) {
      return { moduleTemplates: [], edgeTemplates: [] };
    }
    const moduleTemplates = Array.isArray(payload.moduleTemplates)
      ? payload.moduleTemplates.map(sanitizeCustomModuleTemplate).filter((template): template is ResearchModuleTemplate => Boolean(template))
      : [];
    const edgeTemplates = Array.isArray(payload.edgeTemplates)
      ? payload.edgeTemplates.map(sanitizeCustomEdgeTemplate).filter((template): template is ResearchEdgeTemplate => Boolean(template))
      : [];
    return { moduleTemplates, edgeTemplates };
  } catch {
    return { moduleTemplates: [], edgeTemplates: [] };
  }
}

export function writeCustomResearchTemplates(
  templates: ResearchCustomTemplates,
  storage: ResearchTemplateStorage | null = browserResearchTemplateStorage(),
) {
  if (!storage) {
    return false;
  }
  const sanitized = {
    moduleTemplates: templates.moduleTemplates
      .map(sanitizeCustomModuleTemplate)
      .filter((template): template is ResearchModuleTemplate => Boolean(template)),
    edgeTemplates: templates.edgeTemplates
      .map(sanitizeCustomEdgeTemplate)
      .filter((template): template is ResearchEdgeTemplate => Boolean(template)),
  };
  try {
    storage.setItem(RESEARCH_CUSTOM_TEMPLATES_STORAGE_KEY, JSON.stringify(sanitized));
    return true;
  } catch {
    return false;
  }
}

function nextCustomTemplateKey(prefix: string, rawBase: string, templates: Pick<ResearchModuleTemplate | ResearchEdgeTemplate, "key">[]) {
  const base = safeTemplateIdPart(rawBase) || "template";
  const known = new Set(templates.map((template) => template.key));
  let key = `${prefix}_${base}`;
  let index = 2;
  while (known.has(key)) {
    key = `${prefix}_${base}_${index}`;
    index += 1;
  }
  return key;
}

export function createCustomResearchModuleTemplate(
  node: Pick<ResearchFlowNode, "id" | "label" | "type" | "agentKey" | "promptKey" | "llmConfigId" | "description" | "routeCondition">,
  templates: Pick<ResearchModuleTemplate, "key">[] = [],
): ResearchModuleTemplate {
  const baseId = safeTemplateIdPart(node.id || node.agentKey || node.promptKey || node.label) || "research_module";
  return {
    key: nextCustomTemplateKey("custom_module", baseId, templates),
    baseId,
    group: "自定义模板",
    label: node.label.trim() || "自定义模块",
    type: normalizeNodeTemplateType(node.type),
    status: "idle",
    agentKey: node.agentKey,
    promptKey: node.promptKey,
    llmConfigId: node.llmConfigId,
    description: node.description,
    routeCondition: node.routeCondition,
  };
}

export function createCustomResearchEdgeTemplate(
  edge: Pick<ResearchFlowEdge, "id" | "source" | "target" | "label" | "condition" | "type">,
  sourceLabel = edge.source,
  targetLabel = edge.target,
  templates: Pick<ResearchEdgeTemplate, "key">[] = [],
): ResearchEdgeTemplate {
  const condition = normalizeEdgeCondition(edge.condition);
  const type = normalizeEdgeTemplateType(edge.type, condition);
  const label = edge.label.trim() || `${sourceLabel} → ${targetLabel}`;
  return {
    key: nextCustomTemplateKey("custom_edge", edge.id || `${edge.source}_${edge.target}_${condition}`, templates),
    group: "自定义模板",
    label,
    type,
    condition,
    edgeLabel: label,
    description: `自定义路由：${sourceLabel} → ${targetLabel}。${edgeConditionDescription(condition)}`,
  };
}

function researchModuleTemplateGroups(templates: ResearchModuleTemplate[]) {
  const known = new Set(templates.map((template) => template.group));
  return RESEARCH_MODULE_TEMPLATE_GROUPS.filter((group) => known.has(group));
}

function researchEdgeTemplateGroups(templates: ResearchEdgeTemplate[]) {
  const known = new Set(templates.map((template) => template.group));
  return RESEARCH_EDGE_TEMPLATE_GROUPS.filter((group) => known.has(group));
}

export function researchFlowModuleTemplateKey(
  node: Pick<ResearchFlowNode, "type" | "agentKey" | "promptKey" | "llmConfigId" | "description" | "routeCondition"> & Partial<Pick<ResearchFlowNode, "label">>,
  templates: ResearchModuleTemplate[] = RESEARCH_MODULE_TEMPLATES,
) {
  const matchesTemplate = (template: ResearchModuleTemplate) =>
    template.type === node.type &&
    template.agentKey === node.agentKey &&
    template.promptKey === node.promptKey &&
    template.llmConfigId === node.llmConfigId &&
    template.description === node.description &&
    template.routeCondition === node.routeCondition;
  const exact = node.label ? templates.find((template) => matchesTemplate(template) && template.label === node.label) : null;
  const normalized = exact ?? templates.find(matchesTemplate);
  return normalized?.key ?? "__custom__";
}

export function applyResearchModuleTemplateToNode(template: ResearchModuleTemplate): Partial<ResearchFlowNode> {
  return {
    label: template.label,
    type: template.type,
    agentKey: template.agentKey,
    promptKey: template.promptKey,
    llmConfigId: template.llmConfigId,
    description: template.description,
    routeCondition: template.routeCondition,
  };
}

export function findResearchEdgeTemplate(key: string, templates: ResearchEdgeTemplate[] = RESEARCH_EDGE_TEMPLATES) {
  return templates.find((template) => template.key === key) ?? RESEARCH_EDGE_TEMPLATES[0];
}

export function researchFlowEdgeTemplateKey(
  edge: Pick<ResearchFlowEdge, "type" | "condition"> & Partial<Pick<ResearchFlowEdge, "label">>,
  templates: ResearchEdgeTemplate[] = RESEARCH_EDGE_TEMPLATES,
) {
  const normalized = normalizeEdgeCondition(edge.condition);
  const edgeType = edge.type || defaultEdgeTypeForCondition(normalized);
  const exact = edge.label
    ? templates.find((template) => template.condition === normalized && template.type === edgeType && template.edgeLabel === edge.label)
    : null;
  const match = exact ?? templates.find((template) => template.condition === normalized && template.type === edgeType);
  return match?.key ?? "__custom__";
}

export function applyResearchEdgeTemplateToEdge(template: ResearchEdgeTemplate): Partial<ResearchFlowEdge> {
  return {
    label: template.edgeLabel,
    type: template.type,
    condition: template.condition,
  };
}

export function researchFlowActionKey(node: Pick<ResearchFlowNode, "id" | "agentKey" | "promptKey">) {
  const raw = (node.agentKey || node.promptKey || node.id || "").trim();
  return FLOW_NODE_ACTION_ALIASES[raw] ?? raw;
}

export function researchFlowNodeContract(node: Pick<ResearchFlowNode, "id" | "agentKey" | "promptKey" | "label">) {
  return RESEARCH_FLOW_NODE_CONTRACTS[researchFlowActionKey(node)] ?? null;
}

function researchFlowContractOutputs(contract: FlowContract) {
  return contract.outputs;
}

function researchFlowOutputsForCondition(contract: FlowContract, condition: string) {
  const outputs = researchFlowContractOutputs(contract);
  return outputs[condition] ?? outputs.completed ?? [];
}

function researchFlowContractInputOptions(contract: FlowContract) {
  return contract.inputs.filter((group) => group.length > 0);
}

function researchFlowOutputsSatisfyInputs(outputs: string[], inputOptions: string[][]) {
  return inputOptions.some((required) => required.every((item) => outputs.includes(item)));
}

function researchFlowExpectedOutcomes(contract: FlowContract) {
  return contract.expectedOutcomes ?? Object.keys(contract.outputs);
}

function researchFlowIssue(
  severity: "error" | "warning",
  code: string,
  message: string,
  details: Partial<Pick<ResearchFlowValidationIssue, "nodeId" | "edgeId" | "source" | "target">> = {},
): ResearchFlowValidationIssue {
  return { severity, code, message, ...details };
}

export function validateResearchFlowCanvasContract(canvas: Pick<ResearchFlowCanvas, "nodes" | "edges">): ResearchFlowValidation {
  const nodeById = new Map(canvas.nodes.map((node) => [node.id, node] as const));
  const incoming = new Map<string, ResearchFlowEdge[]>();
  const outgoing = new Map<string, ResearchFlowEdge[]>();
  const issues: ResearchFlowValidationIssue[] = [];
  const edgeIds = new Set<string>();
  const pairIds = new Set<string>();

  for (const node of canvas.nodes) {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
  }

  for (const edge of canvas.edges) {
    const condition = normalizeEdgeCondition(edge.condition);
    const edgeType = edge.type || defaultEdgeTypeForCondition(condition);
    if (edgeIds.has(edge.id)) {
      issues.push(researchFlowIssue("error", "duplicate_edge_id", `路由 ID 重复：${edge.id}`, { edgeId: edge.id }));
    }
    edgeIds.add(edge.id);
    if (edge.source === edge.target) {
      issues.push(researchFlowIssue("error", "self_loop", `路由 ${edge.id || edge.source} 不能连接到自身。`, {
        edgeId: edge.id,
        source: edge.source,
        target: edge.target,
      }));
    }
    const allowedTypes = FLOW_CONDITION_EDGE_TYPES[condition] ?? [];
    if (allowedTypes.length && !allowedTypes.includes(edgeType)) {
      issues.push(
        researchFlowIssue(
          "error",
          "edge_type_condition_mismatch",
          `路由 ${edge.id || edge.source} 的触发条件 ${condition} 与箭头类型 ${edgeType} 不一致。`,
          { edgeId: edge.id, source: edge.source, target: edge.target },
        ),
      );
    }
    const pairKey = `${edge.source}::${edge.target}::${condition}`;
    if (pairIds.has(pairKey)) {
      issues.push(
        researchFlowIssue("warning", "duplicate_edge_pair", `${edge.source} 到 ${edge.target} 已存在同条件路由 ${condition}。`, {
          edgeId: edge.id,
          source: edge.source,
          target: edge.target,
        }),
      );
    }
    pairIds.add(pairKey);
    if (outgoing.has(edge.source)) {
      outgoing.get(edge.source)!.push(edge);
    }
    if (incoming.has(edge.target)) {
      incoming.get(edge.target)!.push(edge);
    }
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) {
      continue;
    }
    const sourceContract = researchFlowNodeContract(sourceNode);
    const targetContract = researchFlowNodeContract(targetNode);
    if (!sourceContract) {
      issues.push(
        researchFlowIssue(
          "warning",
          "unknown_source_contract",
          `模块 ${sourceNode.label || sourceNode.id} 没有已知输出契约，无法完全验证路由 ${edge.id || edge.source}。`,
          { edgeId: edge.id, source: edge.source, target: edge.target },
        ),
      );
    } else if (!Object.keys(researchFlowContractOutputs(sourceContract)).includes(condition)) {
      issues.push(
        researchFlowIssue(
          "error",
          "edge_condition_not_produced",
          `模块 ${sourceNode.label || sourceNode.id} 不会产生 ${condition} 分支。`,
          { edgeId: edge.id, source: edge.source, target: edge.target },
        ),
      );
    }
    if (sourceContract && targetContract) {
      const sourceOutputs = researchFlowOutputsForCondition(sourceContract, condition);
      const targetInputOptions = researchFlowContractInputOptions(targetContract);
      if (targetInputOptions.length && !researchFlowOutputsSatisfyInputs(sourceOutputs, targetInputOptions)) {
        issues.push(
          researchFlowIssue(
            "error",
            "edge_io_mismatch",
            `路由 ${edge.id || edge.source} 输出 ${sourceOutputs.join(", ") || "空"}，无法满足 ${targetNode.label || targetNode.id} 的输入契约。`,
            { edgeId: edge.id, source: edge.source, target: edge.target },
          ),
        );
      }
    } else if (targetContract && researchFlowContractInputOptions(targetContract).length) {
      issues.push(
        researchFlowIssue(
          "warning",
          "target_input_unverified",
          `模块 ${targetNode.label || targetNode.id} 有输入要求，但上游契约未知，无法完全验证。`,
          { edgeId: edge.id, source: edge.source, target: edge.target },
        ),
      );
    }
  }

  const startNodeIds = [...incoming.entries()].filter(([, edges]) => edges.length === 0).map(([nodeId]) => nodeId);
  if (canvas.nodes.length && !startNodeIds.length) {
    issues.push(researchFlowIssue("error", "flow_missing_start_node", "科研流程画布没有起点模块，所有节点都依赖上游输入。"));
  }
  const reachable = new Set<string>();
  const stack = [...startNodeIds];
  while (stack.length) {
    const nodeId = stack.pop()!;
    if (reachable.has(nodeId)) {
      continue;
    }
    reachable.add(nodeId);
    for (const edge of outgoing.get(nodeId) ?? []) {
      if (!reachable.has(edge.target)) {
        stack.push(edge.target);
      }
    }
  }

  for (const node of canvas.nodes) {
    const contract = researchFlowNodeContract(node);
    if (!contract) {
      continue;
    }
    if (researchFlowContractInputOptions(contract).length && !(incoming.get(node.id)?.length ?? 0)) {
      issues.push(
        researchFlowIssue("warning", "node_missing_required_input", `模块 ${node.label || node.id} 需要上游输入，但当前没有任何进入路由。`, {
          nodeId: node.id,
        }),
      );
    }
    if (startNodeIds.length && !reachable.has(node.id)) {
      issues.push(researchFlowIssue("warning", "node_unreachable", `模块 ${node.label || node.id} 无法从起点流程到达。`, { nodeId: node.id }));
    }
    const expectedOutcomes = researchFlowExpectedOutcomes(contract);
    if (!contract.terminal && expectedOutcomes.length) {
      const existingOutcomes = new Set((outgoing.get(node.id) ?? []).map((edge) => normalizeEdgeCondition(edge.condition)));
      const missingOutcomes = expectedOutcomes.filter((condition) => !existingOutcomes.has(condition));
      if (missingOutcomes.length) {
        issues.push(
          researchFlowIssue(
            "warning",
            "node_missing_outcome_route",
            `模块 ${node.label || node.id} 缺少分支路由：${missingOutcomes.join(", ")}。`,
            { nodeId: node.id },
          ),
        );
      }
    }
  }

  const errorCount = issues.filter((issue) => issue.severity === "error").length;
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;
  return {
    valid: errorCount === 0,
    summary: {
      errorCount,
      warningCount,
      issueCount: issues.length,
    },
    issues,
  };
}

export function isValidResearchFlowConnection(
  canvas: Pick<ResearchFlowCanvas, "nodes" | "edges">,
  sourceId: string,
  targetId: string,
  condition = "completed",
  edgeId = "",
  edgeType = defaultEdgeTypeForCondition(condition),
) {
  const targetCondition = normalizeEdgeCondition(condition);
  const targetEdgeType = edgeTypeMatchesCondition(targetCondition, edgeType) ? edgeType : defaultEdgeTypeForCondition(targetCondition);
  const filtered = {
    nodes: canvas.nodes,
    edges: canvas.edges.filter((edge) => edge.id !== edgeId),
  };
  const sourceNode = filtered.nodes.find((node) => node.id === sourceId);
  const targetNode = filtered.nodes.find((node) => node.id === targetId);
  if (!sourceNode || !targetNode || sourceId === targetId) {
    return false;
  }
  const validation = validateResearchFlowCanvasContract({
    nodes: filtered.nodes,
    edges: [...filtered.edges, { id: edgeId || "__probe__", source: sourceId, target: targetId, label: "校验", condition: targetCondition, type: targetEdgeType }],
  });
  return validation.valid;
}

export function findResearchModuleTemplate(key: string, templates: ResearchModuleTemplate[] = RESEARCH_MODULE_TEMPLATES) {
  return (
    templates.find((template) => template.key === key) ??
    RESEARCH_MODULE_TEMPLATES.find((template) => template.key === DEFAULT_RESEARCH_MODULE_TEMPLATE_KEY)!
  );
}

export function nextTemplateNodeId(nodes: Pick<ResearchFlowNode, "id">[], baseId: string) {
  const safeBaseId = baseId.trim() || "research_module";
  const known = new Set(nodes.map((node) => node.id));
  if (!known.has(safeBaseId)) {
    return safeBaseId;
  }
  let index = 2;
  let id = `${safeBaseId}_${index}`;
  while (known.has(id)) {
    index += 1;
    id = `${safeBaseId}_${index}`;
  }
  return id;
}

export function createResearchNodeFromTemplate(
  template: ResearchModuleTemplate,
  nodes: Pick<ResearchFlowNode, "id">[],
  position?: { x: number; y: number },
): ResearchFlowNode {
  const id = nextTemplateNodeId(nodes, template.baseId);
  const duplicateIndex = id === template.baseId ? 1 : Number(id.slice(template.baseId.length + 1));
  const label = Number.isFinite(duplicateIndex) && duplicateIndex > 1 ? `${template.label} ${duplicateIndex}` : template.label;
  return {
    id,
    label,
    type: template.type,
    status: template.status,
    x: position?.x ?? 120 + (nodes.length % 4) * 260,
    y: position?.y ?? 180 + Math.floor(nodes.length / 4) * 170,
    agentKey: template.agentKey,
    promptKey: template.promptKey,
    llmConfigId: template.llmConfigId,
    description: template.description,
    routeCondition: template.routeCondition,
  };
}

function nextEdgeId(edges: ResearchFlowEdge[]) {
  let index = edges.length + 1;
  let id = `custom_edge_${index}`;
  const known = new Set(edges.map((edge) => edge.id));
  while (known.has(id)) {
    index += 1;
    id = `custom_edge_${index}`;
  }
  return id;
}

export function ResearchFlowCanvasRoute() {
  const queryClient = useQueryClient();
  const canvasScrollerRef = useRef<HTMLDivElement | null>(null);
  const suppressCanvasClickRef = useRef(false);
  const dragHistoryRecordedRef = useRef(false);
  const draftRef = useRef<ResearchFlowCanvas | null>(null);
  const draftSignatureRef = useRef("");
  const savedSignatureRef = useRef("");
  const [draft, setDraft] = useState<ResearchFlowCanvas | null>(null);
  const [savedSignature, setSavedSignature] = useState("");
  const [history, setHistory] = useState<CanvasHistory>({ past: [], future: [] });
  const [selection, setSelection] = useState<CanvasSelection>(null);
  const [pendingWorkbenchExit, setPendingWorkbenchExit] = useState<WorkbenchExitGuardDetail | null>(null);
  const [connect, setConnect] = useState<ConnectState>({ active: false, sourceId: null });
  const [drag, setDrag] = useState<DragState | null>(null);
  const [pan, setPan] = useState<PanState | null>(null);
  const [reconnect, setReconnect] = useState<ReconnectState | null>(null);
  const [canvasOffset, setCanvasOffset] = useState<CanvasOffset>({ x: 0, y: 0 });
  const [canvasZoom, setCanvasZoom] = useState(1);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [executionMessage, setExecutionMessage] = useState("");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "warning" | "error">("idle");
  const [customTemplates, setCustomTemplates] = useState<ResearchCustomTemplates>(() => readCustomResearchTemplates());
  const [canvasLocked, setCanvasLocked] = useState(false);
  const [flowRunActive, setFlowRunActive] = useState(false);
  const [selectedModuleTemplateKey, setSelectedModuleTemplateKey] = useState(DEFAULT_RESEARCH_MODULE_TEMPLATE_KEY);
  const [newEdgeTemplateKey, setNewEdgeTemplateKey] = useState("main_flow");
  const [inspectorView, setInspectorView] = useState<InspectorView>("properties");

  const canvasQuery = useQuery({
    queryKey: queryKeys.researchFlowCanvas(),
    queryFn: () => fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas"),
    refetchInterval: canvasLocked || flowRunActive ? 1000 : false,
    refetchIntervalInBackground: false,
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoverySessions(),
    queryFn: () => fetchJson<ResearchDiscoverySessionList>("/api/research/theme-discovery/sessions"),
  });

  const promptsQuery = useQuery({
    queryKey: queryKeys.researchThemeDiscoveryPrompts(),
    queryFn: () => fetchJson<ResearchPromptWorkspace>("/api/research/theme-discovery/prompts"),
  });

  useEffect(() => {
    draftRef.current = draft;
    draftSignatureRef.current = canvasSignature(draft);
  }, [draft]);

  useEffect(() => {
    savedSignatureRef.current = savedSignature;
  }, [savedSignature]);

  useEffect(() => {
    if (canvasQuery.data) {
      const next = cloneCanvas(canvasQuery.data);
      const observing = canvasLocked || flowRunActive;
      if (observing && draftSignatureRef.current) {
        next.viewport = canvasViewportFromView(canvasOffset, canvasZoom);
      }
      const nextSignature = canvasSignature(next);
      const hasLocalDraft =
        Boolean(draftSignatureRef.current) &&
        Boolean(savedSignatureRef.current) &&
        draftSignatureRef.current !== savedSignatureRef.current;
      if (hasLocalDraft) {
        setSaveMessage("远端画布已刷新，已保留本地未保存修改。保存后再同步远端状态。");
        setSaveStatus("warning");
        return;
      }
      draftSignatureRef.current = nextSignature;
      savedSignatureRef.current = nextSignature;
      setDraft(next);
      setSavedSignature(nextSignature);
      setHistory({ past: [], future: [] });
      setSaveStatus("idle");
      if (!observing) {
        setCanvasOffset(viewportOffset(next.viewport));
        setCanvasZoom(clampCanvasZoom(next.viewport?.zoom ?? 1));
      }
      setSelection((current) => {
        if (!current) {
          return { kind: "node", id: next.nodes[0]?.id ?? "" };
        }
        if (current.kind === "node" && next.nodes.some((node) => node.id === current.id)) {
          return current;
        }
        if (current.kind === "edge" && next.edges.some((edge) => edge.id === current.id)) {
          return current;
        }
        return { kind: "node", id: next.nodes[0]?.id ?? "" };
      });
    }
  }, [canvasQuery.data]);

  useEffect(() => {
    if (!drag) {
      return undefined;
    }
    const handleMove = (event: PointerEvent | globalThis.PointerEvent) => {
      const deltaX = event.clientX - drag.originX;
      const deltaY = event.clientY - drag.originY;
      if (!dragHistoryRecordedRef.current && Math.hypot(deltaX, deltaY) > 0 && draftRef.current) {
        setHistory((currentHistory) => pushCanvasHistory(currentHistory, draftRef.current as ResearchFlowCanvas));
        setSaveMessage("");
        setSaveStatus("idle");
        dragHistoryRecordedRef.current = true;
      }
      setDraft((current) => {
        if (!current) {
          return current;
        }
        return {
          ...current,
          nodes: current.nodes.map((node) =>
            node.id === drag.nodeId
                ? {
                  ...node,
                  x: Math.max(0, drag.startX + deltaX / canvasZoom),
                  y: Math.max(0, drag.startY + deltaY / canvasZoom),
                }
              : node,
          ),
        };
      });
    };
    const handleUp = () => {
      dragHistoryRecordedRef.current = false;
      setDrag(null);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [canvasZoom, drag]);

  useEffect(() => {
    if (!pan) {
      return undefined;
    }
    const handleMove = (event: PointerEvent | globalThis.PointerEvent) => {
      const deltaX = event.clientX - pan.originX;
      const deltaY = event.clientY - pan.originY;
      if (Math.hypot(deltaX, deltaY) > 3) {
        suppressCanvasClickRef.current = true;
      }
      commitCanvasViewport({
        x: pan.startOffsetX + deltaX,
        y: pan.startOffsetY + deltaY,
      }, canvasZoom);
    };
    const handleUp = () => setPan(null);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [canvasZoom, pan]);

  const dirty = useMemo(() => canvasSignature(draft) !== savedSignature, [draft, savedSignature]);
  const selectedNode = draft && selection?.kind === "node" ? draft.nodes.find((node) => node.id === selection.id) ?? null : null;
  const selectedEdge = draft && selection?.kind === "edge" ? draft.edges.find((edge) => edge.id === selection.id) ?? null : null;
  const agentOptions = promptsQuery.data?.agents ?? [];
  const llmOptions = promptsQuery.data?.llmConfigs ?? [];
  const selectedNodeAgent = selectedNode?.agentKey ? agentOptions.find((agent) => agent.key === selectedNode.agentKey) : undefined;
  const sessions = sessionsQuery.data?.sessions ?? [];
  const activeExecutionSessionId = activeSessionId || sessions[0]?.sessionId || "";
  const moduleTemplates = useMemo(
    () => [...RESEARCH_MODULE_TEMPLATES, ...customTemplates.moduleTemplates],
    [customTemplates.moduleTemplates],
  );
  const edgeTemplates = useMemo(
    () => [...RESEARCH_EDGE_TEMPLATES, ...customTemplates.edgeTemplates],
    [customTemplates.edgeTemplates],
  );
  const moduleTemplateGroups = useMemo(() => researchModuleTemplateGroups(moduleTemplates), [moduleTemplates]);
  const edgeTemplateGroups = useMemo(() => researchEdgeTemplateGroups(edgeTemplates), [edgeTemplates]);
  const edgeLanes = useMemo(() => (draft ? resolveEdgeLanes(draft.edges, draft.nodes) : new Map<string, EdgeLane>()), [draft]);
  const draftValidation = useMemo(() => (draft ? validateResearchFlowCanvasContract(draft) : null), [draft]);
  const reconnectEdge = draft && reconnect ? draft.edges.find((edge) => edge.id === reconnect.edgeId) ?? null : null;
  const deleteImpact = useMemo(() => summarizeDeleteImpact(draft, selection), [draft, selection]);
  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;
  const canvasObservationActive = canvasLocked || flowRunActive;
  const selectedModuleTemplate = useMemo(
    () => findResearchModuleTemplate(selectedModuleTemplateKey, moduleTemplates),
    [moduleTemplates, selectedModuleTemplateKey],
  );
  const selectedNodeContract = useMemo(
    () => (selectedNode ? researchFlowNodeContract(selectedNode) : null),
    [selectedNode],
  );
  const selectedNodeTemplateKey = useMemo(
    () => (selectedNode ? researchFlowModuleTemplateKey(selectedNode, moduleTemplates) : "__custom__"),
    [moduleTemplates, selectedNode],
  );
  const selectedNodeTemplate = useMemo(
    () =>
      selectedNodeTemplateKey === "__custom__"
        ? null
        : findResearchModuleTemplate(selectedNodeTemplateKey, moduleTemplates),
    [moduleTemplates, selectedNodeTemplateKey],
  );
  const selectedEdgeSourceContract = useMemo(
    () => (draft && selectedEdge ? researchFlowNodeContract(draft.nodes.find((node) => node.id === selectedEdge.source) ?? { id: "", agentKey: "", promptKey: "", label: "" }) : null),
    [draft, selectedEdge],
  );
  const selectedEdgeTargetContract = useMemo(
    () => (draft && selectedEdge ? researchFlowNodeContract(draft.nodes.find((node) => node.id === selectedEdge.target) ?? { id: "", agentKey: "", promptKey: "", label: "" }) : null),
    [draft, selectedEdge],
  );
  const selectedEdgeTemplateKey = useMemo(
    () => (selectedEdge ? researchFlowEdgeTemplateKey(selectedEdge, edgeTemplates) : "__custom__"),
    [edgeTemplates, selectedEdge],
  );
  const selectedEdgeTemplate = useMemo(
    () =>
      selectedEdgeTemplateKey === "__custom__"
        ? null
        : findResearchEdgeTemplate(selectedEdgeTemplateKey, edgeTemplates),
    [edgeTemplates, selectedEdgeTemplateKey],
  );
  const newEdgeTemplate = useMemo(() => findResearchEdgeTemplate(newEdgeTemplateKey, edgeTemplates), [edgeTemplates, newEdgeTemplateKey]);
  const validationIssues = draftValidation?.issues ?? [];
  const validationErrors = validationIssues.filter((issue) => issue.severity === "error");
  const validationWarnings = validationIssues.filter((issue) => issue.severity === "warning");
  const selectedEdgeIssues = useMemo(
    () =>
      selectedEdge
        ? validationIssues.filter(
            (issue) => issue.edgeId === selectedEdge.id || (issue.source === selectedEdge.source && issue.target === selectedEdge.target),
          )
        : [],
    [selectedEdge, validationIssues],
  );
  const saveStatusClass =
    saveStatus === "error"
      ? styles.saveStatusError
      : saveStatus === "warning"
        ? styles.saveStatusWarning
        : saveStatus === "success"
          ? styles.saveStatusSuccess
          : styles.saveStatusIdle;

  const pointerToCanvasPoint = (event: globalThis.PointerEvent | PointerEvent<HTMLElement>): CanvasPoint | null => {
    const scroller = canvasScrollerRef.current;
    if (!scroller) {
      return null;
    }
    const rect = scroller.getBoundingClientRect();
    return {
      x: (scroller.scrollLeft + event.clientX - rect.left - canvasOffset.x) / canvasZoom,
      y: (scroller.scrollTop + event.clientY - rect.top - canvasOffset.y) / canvasZoom,
    };
  };

  const findNodeAtPointer = (event: globalThis.PointerEvent | PointerEvent<HTMLElement>) => {
    const point = pointerToCanvasPoint(event);
    if (!point || !draft) {
      return null;
    }
    return [...draft.nodes].reverse().find((node) => pointInNode(point, node)) ?? null;
  };

  useEffect(() => {
    if (!activeSessionId && sessions[0]?.sessionId) {
      setActiveSessionId(sessions[0].sessionId);
    }
  }, [activeSessionId, sessions]);

  useEffect(() => {
    if (!reconnect || !draft) {
      return undefined;
    }
    const handleMove = (event: globalThis.PointerEvent) => {
      const edge = draft.edges.find((item) => item.id === reconnect.edgeId);
      const node = findNodeAtPointer(event);
      setReconnect((current) => {
        if (!current || !edge || !node || !isValidEdgeReconnectTarget(edge, current.endpoint, node.id)) {
          return current ? { ...current, hoverNodeId: null } : current;
        }
        const probe = {
          ...edge,
          [current.endpoint]: node.id,
        } as ResearchFlowEdge;
        if (!isValidResearchFlowConnection(draft, probe.source, probe.target, probe.condition, probe.id, probe.type)) {
          return current ? { ...current, hoverNodeId: null } : current;
        }
        return { ...current, hoverNodeId: node.id };
      });
    };
    const handleUp = (event: globalThis.PointerEvent) => {
      const edge = draft.edges.find((item) => item.id === reconnect.edgeId);
      const node = findNodeAtPointer(event);
      if (edge && node && isValidEdgeReconnectTarget(edge, reconnect.endpoint, node.id)) {
        const probe = {
          ...edge,
          [reconnect.endpoint]: node.id,
        } as ResearchFlowEdge;
        if (!isValidResearchFlowConnection(draft, probe.source, probe.target, probe.condition, probe.id, probe.type)) {
          setConnectionMessage(`无法重连到 ${node.label}，输入输出契约不匹配。`);
          setReconnect(null);
          return;
        }
        setConnectionMessage("");
        updateEdge(edge.id, { [reconnect.endpoint]: node.id } as Partial<ResearchFlowEdge>);
        setSelection({ kind: "edge", id: edge.id });
      }
      setReconnect(null);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [canvasOffset, canvasZoom, draft, reconnect?.edgeId, reconnect?.endpoint]);

  const saveAgentMutation = useMutation({
    mutationFn: async (payload: ResearchAgentConfig) =>
      fetchJson<ResearchPromptWorkspace>("/api/research/theme-discovery/agent-templates", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoveryPrompts() });
      setSaveMessage("科研 Agent 配置已更新，所有画布统一生效。");
      setSaveStatus("success");
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "保存失败";
      setSaveMessage(`科研 Agent 配置保存失败: ${message}`);
      setSaveStatus("error");
    },
  });

  const saveMutation = useMutation({
    mutationFn: async (payload: ResearchFlowCanvas) =>
      fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schemaVersion: payload.schemaVersion,
          viewport: payload.viewport,
          nodes: payload.nodes,
          edges: payload.edges,
        }),
      }),
    onSuccess: async (saved) => {
      const next = cloneCanvas(saved);
      const nextSignature = canvasSignature(next);
      draftSignatureRef.current = nextSignature;
      savedSignatureRef.current = nextSignature;
      setDraft(next);
      setSavedSignature(nextSignature);
      setCanvasOffset(viewportOffset(next.viewport));
      setCanvasZoom(clampCanvasZoom(next.viewport?.zoom ?? 1));
      setSaveMessage(`已保存 ${saved.updatedAt}`);
      setSaveStatus("success");
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "保存失败";
      setSaveMessage(`保存失败: ${message}`);
      setSaveStatus("error");
    },
  });
  const shouldBlockLeave = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) =>
      shouldBlockCanvasLeave({
        dirty,
        saving: saveMutation.isPending,
        currentPathname: currentLocation.pathname,
        nextPathname: nextLocation.pathname,
      }),
    [dirty, saveMutation.isPending],
  );
  const leaveBlocker = useBlocker(shouldBlockLeave);
  const routeLeaveGuardOpen = leaveBlocker.state === "blocked";
  const leaveGuardOpen = routeLeaveGuardOpen || Boolean(pendingWorkbenchExit);
  const leaveGuardSaving = leaveGuardOpen && saveMutation.isPending;
  const workbenchExitLabel = pendingWorkbenchExit?.action === "restart" ? "重启工作台" : "关闭工作台";
  const leaveGuardTitle = pendingWorkbenchExit
    ? `${workbenchExitLabel}前要保存科研流程画布吗？`
    : "离开前要保存科研流程画布吗？";
  const leaveGuardBody = pendingWorkbenchExit
    ? `当前模块、路由或视图状态还没有写回唯一事实来源。保存后会继续${workbenchExitLabel}；不保存会丢弃本次草稿。`
    : "当前模块、路由或视图状态还没有写回唯一事实来源。保存后离开会先提交画布；不保存离开会丢弃本次草稿。";
  const leaveGuardSaveLabel = leaveGuardSaving
    ? "保存中"
    : pendingWorkbenchExit
      ? `保存后${workbenchExitLabel}`
      : "保存后离开";
  const leaveGuardDiscardLabel = pendingWorkbenchExit ? `不保存${workbenchExitLabel}` : "不保存离开";

  useEffect(() => {
    const handleWorkbenchExitGuard = (event: Event) => {
      if (!dirty && !saveMutation.isPending) {
        return;
      }
      const detail = (event as CustomEvent<WorkbenchExitGuardDetail>).detail;
      if (!detail?.proceed) {
        return;
      }
      event.preventDefault();
      setPendingWorkbenchExit(detail);
    };
    window.addEventListener(WORKBENCH_EXIT_GUARD_EVENT, handleWorkbenchExitGuard);
    return () => window.removeEventListener(WORKBENCH_EXIT_GUARD_EVENT, handleWorkbenchExitGuard);
  }, [dirty, saveMutation.isPending]);

  useEffect(() => {
    if (!dirty && !saveMutation.isPending) {
      return undefined;
    }
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty, saveMutation.isPending]);

  useEffect(() => {
    if (!canvasLocked && !flowRunActive) {
      return;
    }
    setConnect({ active: false, sourceId: null });
    setDrag(null);
    setReconnect(null);
  }, [canvasLocked, flowRunActive]);

  const executeMutation = useMutation({
    mutationFn: async (payload: { sessionId: string; nodeId?: string }) =>
      fetchJson<ResearchFlowExecutionResponse>("/api/research/flow-canvas/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onMutate: () => {
      setFlowRunActive(true);
      setExecutionMessage("执行已开始，画布正在实时同步节点状态。");
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    },
    onSuccess: async (result) => {
      const next = cloneCanvas(result.canvas);
      const nextSignature = canvasSignature(next);
      draftSignatureRef.current = nextSignature;
      savedSignatureRef.current = nextSignature;
      setDraft(next);
      setSavedSignature(nextSignature);
      setHistory({ past: [], future: [] });
      setSaveStatus("idle");
      setCanvasOffset(viewportOffset(next.viewport));
      setCanvasZoom(clampCanvasZoom(next.viewport?.zoom ?? 1));
      setExecutionMessage(result.execution.message);
      setSelection({ kind: "node", id: result.execution.nodeId });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySessions() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.researchThemeDiscoverySession(result.execution.sessionId) }),
      ]);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "执行失败";
      setExecutionMessage(message);
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchFlowCanvas() });
    },
    onSettled: () => {
      setFlowRunActive(false);
    },
  });
  const executionBlockReason = researchFlowExecutionBlockReason({
    sessionId: activeExecutionSessionId,
    sessionLoading: sessionsQuery.isLoading,
    canvasLocked,
    dirty,
    executing: executeMutation.isPending,
    validationErrorCount: validationErrors.length,
  });
  const lockBlockReason = researchFlowLockBlockReason({
    draftReady: Boolean(draft),
    dirty,
    saving: saveMutation.isPending,
    executing: executeMutation.isPending || flowRunActive,
    validationErrorCount: validationErrors.length,
  });
  const canvasEditable = !canvasLocked && !executeMutation.isPending && !flowRunActive;
  const primaryBlockAction = dirty
    ? "保存画布"
    : validationErrors.length > 0
      ? "查看问题"
      : !canvasLocked
        ? "锁定观察"
        : "";
  const executionGuideActive = Boolean(executionBlockReason) && !executeMutation.isPending;

  const toggleCanvasLock = () => {
    if (canvasLocked) {
      if (lockBlockReason) {
        setExecutionMessage(lockBlockReason);
        return;
      }
      setCanvasLocked(false);
      setExecutionMessage("画布已解除锁定，可以继续编辑流程结构。");
      setSaveMessage("");
      setSaveStatus("idle");
      return;
    }
    if (lockBlockReason) {
      setSaveMessage(lockBlockReason);
      setSaveStatus("warning");
      return;
    }
    setCanvasLocked(true);
    setConnectionMessage("");
    setSaveMessage("画布已锁定，正在实时观察流程状态。");
    setSaveStatus("success");
    setExecutionMessage("观察模式已开启，可以执行流程并实时查看节点状态变化。");
  };

  const runFlowNode = (nodeId?: string) => {
    if (executionBlockReason) {
      setExecutionMessage(executionBlockReason);
      return;
    }
    setExecutionMessage("");
    executeMutation.mutate({ sessionId: activeExecutionSessionId, nodeId });
  };

  const handleExecutionGuideAction = () => {
    if (dirty) {
      if (draft && !saveMutation.isPending && validationErrors.length === 0 && canvasEditable) {
        saveMutation.mutate(draft);
      }
      return;
    }
    if (validationErrors.length > 0) {
      setInspectorView("issues");
      return;
    }
    if (!canvasLocked) {
      toggleCanvasLock();
      return;
    }
    setExecutionMessage(executionBlockReason);
  };

  const handleSaveAndLeave = async () => {
    const routeProceed = leaveBlocker.state === "blocked" ? leaveBlocker.proceed : null;
    const workbenchExitProceed = pendingWorkbenchExit?.proceed ?? null;
    if ((!routeProceed && !workbenchExitProceed) || !draft || saveMutation.isPending) {
      return;
    }
    if (validationErrors.length > 0) {
      setSaveMessage("当前画布存在契约错误，先修复后再保存离开。");
      setSaveStatus("error");
      return;
    }
    try {
      await saveMutation.mutateAsync(draft);
      setPendingWorkbenchExit(null);
      if (workbenchExitProceed) {
        workbenchExitProceed();
      } else {
        routeProceed?.();
      }
    } catch {
      // saveMutation.onError already surfaces the failure in the inspector and keeps the blocker active.
    }
  };

  const handleDiscardAndLeave = () => {
    if (pendingWorkbenchExit) {
      const proceed = pendingWorkbenchExit.proceed;
      setPendingWorkbenchExit(null);
      proceed();
      return;
    }
    if (leaveBlocker.state === "blocked") {
      leaveBlocker.proceed();
    }
  };

  const handleCancelLeave = () => {
    setPendingWorkbenchExit(null);
    if (leaveBlocker.state === "blocked") {
      leaveBlocker.reset();
    }
  };

  const commitDraftEdit = useCallback((updater: (current: ResearchFlowCanvas) => ResearchFlowCanvas, options: CommitDraftOptions = {}) => {
    if (canvasLocked || flowRunActive) {
      setSaveMessage("画布已锁定为观察模式，解除锁定后才能修改结构。");
      setSaveStatus("warning");
      return;
    }
    const current = draftRef.current;
    if (!current) {
      return;
    }
    const next = updater(current);
    if (canvasSignature(next) === canvasSignature(current)) {
      return;
    }
    setHistory((currentHistory) => pushCanvasHistory(currentHistory, current));
    setSaveMessage("");
    setSaveStatus("idle");
    setDraft(next);
    if ("selection" in options) {
      setSelection(options.selection ?? null);
    }
  }, [canvasLocked, flowRunActive]);

  const restoreCanvasFromHistory = useCallback(
    (direction: "undo" | "redo") => {
      if (!draft || !canvasEditable) {
        return;
      }
      const result = stepCanvasHistory(history, draft, direction);
      if (!result) {
        return;
      }
      const restoredCanvas = {
        ...result.canvas,
        viewport: draft.viewport,
      };
      setHistory(result.history);
      setDraft(restoredCanvas);
      setCanvasOffset(viewportOffset(restoredCanvas.viewport));
      setCanvasZoom(clampCanvasZoom(restoredCanvas.viewport?.zoom ?? 1));
      setSaveMessage(direction === "undo" ? "已撤销上一步编辑。" : "已重做上一步编辑。");
      setSaveStatus("idle");
      setSelection((current) => (selectionExists(restoredCanvas, current) ? current : null));
    },
    [canvasEditable, draft, history],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const targetTag = target?.tagName;
      const editingText =
        target?.isContentEditable ||
        targetTag === "INPUT" ||
        targetTag === "TEXTAREA" ||
        targetTag === "SELECT";
      const hasModifier = event.ctrlKey || event.metaKey;
      if (editingText || !hasModifier) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "z") {
        event.preventDefault();
        restoreCanvasFromHistory(event.shiftKey ? "redo" : "undo");
      }
      if (key === "y") {
        event.preventDefault();
        restoreCanvasFromHistory("redo");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [restoreCanvasFromHistory]);

  const commitCanvasViewport = (offset: CanvasOffset, zoom: number) => {
    const viewport = canvasViewportFromView(offset, zoom);
    setCanvasOffset({ x: viewport.x, y: viewport.y });
    setCanvasZoom(viewport.zoom);
    if (!canvasEditable) {
      return;
    }
    setSaveMessage("");
    setSaveStatus("idle");
    setDraft((current) => (current ? { ...current, viewport } : current));
  };

  const updateNode = (nodeId: string, patch: Partial<ResearchFlowNode>) => {
    commitDraftEdit((current) => ({
      ...current,
      nodes: current.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
    }));
  };

  const updateEdge = (edgeId: string, patch: Partial<ResearchFlowEdge>) => {
    commitDraftEdit((current) => ({
      ...current,
      edges: current.edges.map((edge) => (edge.id === edgeId ? { ...edge, ...patch } : edge)),
    }));
  };

  const persistCustomTemplates = (nextTemplates: ResearchCustomTemplates, successMessage: string) => {
    if (!canvasEditable) {
      setSaveMessage("画布锁定观察中，解除锁定后才能保存模板。");
      setSaveStatus("warning");
      return;
    }
    setCustomTemplates(nextTemplates);
    const persisted = writeCustomResearchTemplates(nextTemplates);
    setSaveMessage(persisted ? successMessage : `${successMessage}（浏览器未允许本地持久化，刷新后可能丢失。）`);
    setSaveStatus(persisted ? "success" : "warning");
  };

  const addNode = () => {
    if (!canvasEditable) {
      return;
    }
    const current = draftRef.current;
    if (!current) {
      return;
    }
    const node = createResearchNodeFromTemplate(selectedModuleTemplate, current.nodes);
    commitDraftEdit((canvas) => ({ ...canvas, nodes: [...canvas.nodes, node] }), { selection: { kind: "node", id: node.id } });
  };

  const saveSelectedNodeAsTemplate = () => {
    if (!selectedNode) {
      return;
    }
    const template = createCustomResearchModuleTemplate(selectedNode, moduleTemplates);
    persistCustomTemplates(
      {
        moduleTemplates: [...customTemplates.moduleTemplates, template],
        edgeTemplates: customTemplates.edgeTemplates,
      },
      `已保存模块模板：${template.label}`,
    );
    setSelectedModuleTemplateKey(template.key);
  };

  const saveSelectedEdgeAsTemplate = () => {
    if (!selectedEdge) {
      return;
    }
    const edgeType = selectedEdge.type || defaultEdgeTypeForCondition(selectedEdge.condition);
    if (!edgeTypeMatchesCondition(selectedEdge.condition, edgeType)) {
      setSaveMessage("当前线的触发条件和箭头类型不一致，先修正后再保存模板。");
      setSaveStatus("error");
      return;
    }
    const sourceNode = draft?.nodes.find((node) => node.id === selectedEdge.source);
    const targetNode = draft?.nodes.find((node) => node.id === selectedEdge.target);
    const template = createCustomResearchEdgeTemplate(
      selectedEdge,
      sourceNode?.label ?? selectedEdge.source,
      targetNode?.label ?? selectedEdge.target,
      edgeTemplates,
    );
    persistCustomTemplates(
      {
        moduleTemplates: customTemplates.moduleTemplates,
        edgeTemplates: [...customTemplates.edgeTemplates, template],
      },
      `已保存线模板：${template.label}`,
    );
    setNewEdgeTemplateKey(template.key);
  };

  const deleteSelected = () => {
    if (!canvasEditable) {
      return;
    }
    if (!selection || !deleteImpact.canDelete) {
      return;
    }
    const removedSubject = deleteImpact.subject;
    const removedDetail =
      selection.kind === "node" && deleteImpact.connectedEdgeCount
        ? `同时删除 ${deleteImpact.connectedEdgeCount} 条关联路由。`
        : selection.kind === "edge"
          ? "只删除这条路由。"
          : "没有关联路由需要删除。";
    commitDraftEdit((current) => deleteCanvasSelection(current, selection), { selection: null });
    setSaveMessage(`已删除 ${removedSubject}，${removedDetail}保存后生效，可撤销。`);
    setSaveStatus("warning");
  };

  const handleCanvasPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    const scroller = canvasScrollerRef.current;
    if (!scroller) {
      return;
    }
    suppressCanvasClickRef.current = false;
    setPan({
      originX: event.clientX,
      originY: event.clientY,
      startOffsetX: canvasOffset.x,
      startOffsetY: canvasOffset.y,
    });
  };

  const handleCanvasClick = () => {
    if (suppressCanvasClickRef.current) {
      suppressCanvasClickRef.current = false;
      return;
    }
    if (!connect.active) {
      setSelection(null);
    }
  };

  const startEdgeReconnect = (event: PointerEvent<HTMLButtonElement>, edge: ResearchFlowEdge, endpoint: EdgeEndpoint) => {
    event.preventDefault();
    event.stopPropagation();
    if (!canvasEditable) {
      return;
    }
    setSelection({ kind: "edge", id: edge.id });
    setReconnect({ edgeId: edge.id, endpoint, hoverNodeId: null });
  };

  const handleNodePointerDown = (event: PointerEvent<HTMLButtonElement>, node: ResearchFlowNode) => {
    event.stopPropagation();
    if (!canvasEditable || connect.active || reconnect) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragHistoryRecordedRef.current = false;
    setSelection({ kind: "node", id: node.id });
    setDrag({
      nodeId: node.id,
      originX: event.clientX,
      originY: event.clientY,
      startX: node.x,
      startY: node.y,
    });
  };

  const handleNodeClick = (node: ResearchFlowNode) => {
    if (!canvasEditable) {
      setSelection({ kind: "node", id: node.id });
      return;
    }
    if (!connect.active) {
      setSelection({ kind: "node", id: node.id });
      return;
    }
    if (!connect.sourceId) {
      setConnect({ active: true, sourceId: node.id });
      setSelection({ kind: "node", id: node.id });
      return;
    }
    const current = draftRef.current;
    if (connect.sourceId === node.id || !current) {
      return;
    }
    const template = newEdgeTemplate;
    const edge: ResearchFlowEdge = {
      id: nextEdgeId(current.edges),
      source: connect.sourceId,
      target: node.id,
      label: template.edgeLabel,
      condition: template.condition,
      type: template.type,
    };
    if (!isValidResearchFlowConnection(current, edge.source, edge.target, edge.condition, edge.id, edge.type)) {
      setConnectionMessage(`无法连接 ${current.nodes.find((item) => item.id === edge.source)?.label || edge.source} → ${node.label}，输入输出契约不匹配。`);
      return;
    }
    setConnectionMessage("");
    commitDraftEdit((canvas) => ({ ...canvas, edges: [...canvas.edges, edge] }), { selection: { kind: "edge", id: edge.id } });
    setConnect({ active: false, sourceId: null });
  };

  const applyCanvasZoom = (nextZoom: number, anchor?: { clientX: number; clientY: number }) => {
    const scroller = canvasScrollerRef.current;
    const currentZoom = canvasZoom;
    const zoom = clampCanvasZoom(nextZoom);
    if (!scroller || !anchor || zoom === currentZoom) {
      commitCanvasViewport(canvasOffset, zoom);
      return;
    }
    const rect = scroller.getBoundingClientRect();
    const anchorX = anchor.clientX - rect.left;
    const anchorY = anchor.clientY - rect.top;
    const canvasX = (scroller.scrollLeft + anchorX - canvasOffset.x) / currentZoom;
    const canvasY = (scroller.scrollTop + anchorY - canvasOffset.y) / currentZoom;
    requestAnimationFrame(() => {
      scroller.scrollLeft = canvasX * zoom + canvasOffset.x - anchorX;
      scroller.scrollTop = canvasY * zoom + canvasOffset.y - anchorY;
    });
    commitCanvasViewport(canvasOffset, zoom);
  };

  const zoomCanvasBy = (delta: number) => {
    applyCanvasZoom(canvasZoom + delta);
  };

  const handleCanvasWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const direction = event.deltaY > 0 ? -1 : 1;
    applyCanvasZoom(canvasZoom + direction * CANVAS_ZOOM_STEP, {
      clientX: event.clientX,
      clientY: event.clientY,
    });
  };

  const fitView = () => {
    commitCanvasViewport({ x: 0, y: 0 }, 1);
    requestAnimationFrame(() => {
      const scroller = canvasScrollerRef.current;
      if (scroller) {
        scroller.scrollLeft = 0;
        scroller.scrollTop = 0;
      }
    });
  };

  const applyAgentBinding = (agent: ResearchAgentConfig | undefined) => {
    if (!selectedNode || !agent) {
      return;
    }
    updateNode(selectedNode.id, {
      agentKey: agent.key,
      promptKey: agent.key,
      llmConfigId: "",
    });
  };

  const focusValidationIssue = (issue: ResearchFlowValidationIssue) => {
    if (!draft) {
      return;
    }
    const edge =
      (issue.edgeId ? draft.edges.find((item) => item.id === issue.edgeId) : null) ??
      draft.edges.find((item) => item.source === issue.source && item.target === issue.target);
    if (edge) {
      setSelection({ kind: "edge", id: edge.id });
      setInspectorView("properties");
      return;
    }
    if (issue.nodeId && draft.nodes.some((node) => node.id === issue.nodeId)) {
      setSelection({ kind: "node", id: issue.nodeId });
      setInspectorView("properties");
    }
  };

  const canvasWidth = Math.max(1480, ...(draft?.nodes.map((node) => node.x + NODE_WIDTH + 120) ?? [1480]));
  const canvasHeight = Math.max(760, ...(draft?.nodes.map((node) => node.y + NODE_HEIGHT + 120) ?? [760]));
  const scaledCanvasWidth = canvasWidth * canvasZoom + Math.abs(canvasOffset.x) + 360;
  const scaledCanvasHeight = canvasHeight * canvasZoom + Math.abs(canvasOffset.y) + 260;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <p>Research Flow Canvas</p>
          <h1>科研流程画布</h1>
          <span>把科研流程改成可配置的动态路线图：模块、状态、路由、Agent 和 LLM 都在这里统一编排。</span>
        </div>
        <div className={styles.headerActions}>
          <Link className={styles.secondaryButton} to="/research">
            <ArrowLeft size={16} />
            返回科研页
          </Link>
          <button
            className={styles.iconButton}
            type="button"
            onClick={() => restoreCanvasFromHistory("undo")}
            disabled={!canUndo || !canvasEditable}
            title="撤销编辑 (Ctrl+Z)"
            aria-label="撤销编辑"
          >
            <Undo2 size={16} />
          </button>
          <button
            className={styles.iconButton}
            type="button"
            onClick={() => restoreCanvasFromHistory("redo")}
            disabled={!canRedo || !canvasEditable}
            title="重做编辑 (Ctrl+Y)"
            aria-label="重做编辑"
          >
            <Redo2 size={16} />
          </button>
          <button className={styles.secondaryButton} type="button" onClick={fitView} disabled={!draft}>
            <MousePointer2 size={16} />
            复位视图
          </button>
          <button
            className={connect.active ? styles.primaryButton : styles.secondaryButton}
            type="button"
            onClick={() => setConnect((current) => ({ active: !current.active, sourceId: null }))}
            disabled={!canvasEditable}
          >
            <Link2 size={16} />
            {connect.active ? (connect.sourceId ? "选择目标" : "选择起点") : "连线"}
          </button>
          <select
            className={styles.moduleTemplateSelect}
            value={newEdgeTemplateKey}
            onChange={(event) => setNewEdgeTemplateKey(event.target.value)}
            disabled={!canvasEditable}
            aria-label="新连线模板"
            title="新连线模板"
          >
            {edgeTemplateGroups.map((group) => (
              <optgroup key={group} label={group}>
                {edgeTemplates.filter((template) => template.group === group).map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <select
            className={styles.moduleTemplateSelect}
            value={selectedModuleTemplateKey}
            onChange={(event) => setSelectedModuleTemplateKey(event.target.value)}
            disabled={!draft || !canvasEditable}
            aria-label="模块库"
            title="模块库"
          >
            {moduleTemplateGroups.map((group) => (
              <optgroup key={group} label={group}>
                {moduleTemplates.filter((template) => template.group === group).map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button className={styles.secondaryButton} type="button" onClick={addNode} disabled={!draft || !canvasEditable}>
            <CirclePlus size={16} />
            添加模块
          </button>
          <button
            className={styles.dangerButton}
            type="button"
            onClick={deleteSelected}
            disabled={!deleteImpact.canDelete || !canvasEditable}
            title={deleteImpact.canDelete ? `${deleteImpact.subject}：${deleteImpact.detail}` : deleteImpact.detail}
          >
            <Trash2 size={16} />
            删除
          </button>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => draft && saveMutation.mutate(draft)}
            disabled={!draft || !dirty || saveMutation.isPending || validationErrors.length > 0 || !canvasEditable}
          >
            <Save size={16} />
            {saveMutation.isPending
              ? "保存中"
              : validationErrors.length > 0
                ? "先修复契约"
                : saveStatus === "error" && dirty
                  ? "重试保存"
                  : dirty
                    ? "保存画布"
                    : "已保存"}
          </button>
          <button
            className={canvasLocked ? `${styles.primaryButton} ${styles.lockButtonActive}` : styles.secondaryButton}
            type="button"
            onClick={toggleCanvasLock}
            disabled={!canvasLocked && Boolean(lockBlockReason)}
            title={canvasLocked ? lockBlockReason || "解除锁定后可以编辑画布。" : lockBlockReason || "锁定后进入观察模式，才能执行流程。"}
            aria-pressed={canvasLocked}
          >
            {canvasLocked ? <Lock size={16} /> : <Unlock size={16} />}
            {canvasLocked ? "已锁定" : "锁定观察"}
          </button>
        </div>
      </header>

      <section className={styles.executionBar} aria-label="科研流程执行路由">
        <div className={styles.executionGroup}>
          <span>科研会话</span>
          <select
            className={styles.sessionSelect}
            value={activeExecutionSessionId}
            onChange={(event) => setActiveSessionId(event.target.value)}
            disabled={sessionsQuery.isLoading || executeMutation.isPending}
          >
            {sessions.length ? null : <option value="">暂无会话</option>}
            {sessions.map((session) => (
              <option key={session.sessionId} value={session.sessionId}>
                {session.openGoal.slice(0, 42) || session.sessionId}
              </option>
            ))}
          </select>
        </div>
        <div className={canvasObservationActive ? `${styles.observerStatus} ${styles.observerStatusActive}` : styles.observerStatus}>
          <span>实时观察</span>
          <strong>{canvasLocked ? "已锁定同步" : flowRunActive ? "同步中" : "未锁定"}</strong>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => runFlowNode()}
          disabled={Boolean(executionBlockReason)}
          title={executionBlockReason || undefined}
        >
          <FastForward size={16} />
          {executeMutation.isPending ? "执行中" : "执行下一节点"}
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => selectedNode && runFlowNode(selectedNode.id)}
          disabled={Boolean(executionBlockReason) || !selectedNode}
          title={executionBlockReason || (!selectedNode ? "先在画布中选择一个节点。" : undefined)}
        >
          <Play size={16} />
          执行选中节点
        </button>
        <p className={styles.executionHint}>
          {executionBlockReason || executionMessage || "执行路由会调用真实科研 agent，并把节点状态写回唯一事实来源。"}
        </p>
      </section>

      {executionGuideActive ? (
        <section className={styles.executionGuide} aria-label="执行前检查">
          <div className={styles.executionGuideCopy}>
            <strong>{executionBlockReason}</strong>
            <span>
              执行需要一份已保存、无契约错误并处于观察锁定的画布。当前阻断项处理后，执行按钮会自动恢复。
            </span>
          </div>
          <div className={styles.executionGuideActions}>
            {primaryBlockAction ? (
              <button
                className={validationErrors.length > 0 ? styles.secondaryButton : styles.primaryButton}
                type="button"
                onClick={handleExecutionGuideAction}
                disabled={dirty && (!draft || saveMutation.isPending || validationErrors.length > 0 || !canvasEditable)}
              >
                {primaryBlockAction}
              </button>
            ) : null}
            {dirty ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => {
                  setInspectorView("properties");
                  setSaveMessage("先保存画布，再锁定观察即可执行。");
                  setSaveStatus("warning");
                }}
              >
                查看事实来源
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      <div className={styles.body}>
        <main className={styles.canvasShell} aria-label="科研流程图画布">
          <div className={styles.zoomControl} aria-label="画布缩放控制">
            <button
              className={styles.iconButton}
              type="button"
              onClick={() => zoomCanvasBy(-CANVAS_ZOOM_STEP)}
              disabled={!draft || canvasZoom <= CANVAS_ZOOM_MIN}
              title="缩小画布"
            >
              <ZoomOut size={16} />
            </button>
            <span>{Math.round(canvasZoom * 100)}%</span>
            <button
              className={styles.iconButton}
              type="button"
              onClick={() => zoomCanvasBy(CANVAS_ZOOM_STEP)}
              disabled={!draft || canvasZoom >= CANVAS_ZOOM_MAX}
              title="放大画布"
            >
              <ZoomIn size={16} />
            </button>
          </div>
          {reconnect && reconnectEdge ? (
            <div className={styles.reconnectHint}>
              正在重连{reconnect.endpoint === "source" ? "起点" : "终点"}：拖到目标模块上松开
            </div>
          ) : null}
          {canvasQuery.isLoading || !draft ? (
            <div className={styles.emptyState}>正在读取 workspace 科研流程画布...</div>
          ) : canvasQuery.isError ? (
            <div className={styles.emptyState}>画布读取失败，请检查后端科研配置接口。</div>
          ) : (
            <div
              ref={canvasScrollerRef}
              className={styles.canvasScroller}
              onWheel={handleCanvasWheel}
              aria-label="画布缩放区域，滚轮可缩放画布"
            >
              <div
                className={styles.canvasViewport}
                style={{ width: scaledCanvasWidth, height: scaledCanvasHeight }}
                onClick={handleCanvasClick}
              >
                <div
                  className={[styles.canvas, pan ? styles.canvasPanning : "", canvasLocked ? styles.canvasLocked : ""].join(" ")}
                  style={{
                    width: canvasWidth,
                    height: canvasHeight,
                    transform: `translate(${canvasOffset.x}px, ${canvasOffset.y}px) scale(${canvasZoom})`,
                  }}
                  onPointerDown={handleCanvasPointerDown}
                >
                <svg className={styles.edges} width={canvasWidth} height={canvasHeight} aria-hidden="true">
                  {draft.edges.map((edge) => {
                    const source = draft.nodes.find((node) => node.id === edge.source);
                    const target = draft.nodes.find((node) => node.id === edge.target);
                    if (!source || !target) {
                      return null;
                    }
                    const geometry = edgeGeometry(source, target, edgeLanes.get(edge.id));
                    const active = selection?.kind === "edge" && selection.id === edge.id;
                    const visual = edgeVisualStyle(edge.type || defaultEdgeTypeForCondition(edge.condition), active);
                    return (
                      <g key={edge.id} className={[active ? styles.edgeActive : styles.edge, edgeTypeClass(edge.type)].join(" ")}>
                        <path className={styles.edgeTrack} d={geometry.path} />
                        <path
                          className={styles.edgePath}
                          d={geometry.path}
                          style={{
                            stroke: visual.stroke,
                            strokeDasharray: visual.strokeDasharray,
                            strokeWidth: visual.strokeWidth,
                          }}
                        />
                        <polygon className={styles.edgeArrowHead} points={geometry.arrowHead} style={{ fill: visual.fill }} />
                      </g>
                    );
                  })}
                </svg>
                {draft.edges.map((edge) => {
                  const source = draft.nodes.find((node) => node.id === edge.source);
                  const target = draft.nodes.find((node) => node.id === edge.target);
                  if (!source || !target) {
                    return null;
                  }
                  const geometry = edgeGeometry(source, target, edgeLanes.get(edge.id));
                  return (
                    <button
                      key={`${edge.id}-hotspot`}
                      type="button"
                      className={[
                        styles.edgeHotspot,
                        selection?.kind === "edge" && selection.id === edge.id ? styles.edgeHotspotActive : "",
                        edgeLanes.get(edge.id)?.overlapCount ? styles.edgeHotspotOffset : "",
                      ].join(" ")}
                      style={{ left: geometry.label.x - 58, top: geometry.label.y - 16 }}
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelection({ kind: "edge", id: edge.id });
                      }}
                    >
                      <span>{edgeTypeLabel(edge.type)} · {edgeConditionLabel(edge.condition)}</span>
                      {edge.label || "路由"}
                    </button>
                  );
                })}
                {draft.edges.map((edge) => {
                  const source = draft.nodes.find((node) => node.id === edge.source);
                  const target = draft.nodes.find((node) => node.id === edge.target);
                  const showHandles = canvasEditable && (selection?.kind === "edge" && selection.id === edge.id || reconnect?.edgeId === edge.id);
                  if (!source || !target || !showHandles) {
                    return null;
                  }
                  const geometry = edgeGeometry(source, target, edgeLanes.get(edge.id));
                  return (
                    <div key={`${edge.id}-endpoints`} className={styles.edgeEndpoints}>
                      <button
                        type="button"
                        className={[
                          styles.edgeEndpointHandle,
                          reconnect?.edgeId === edge.id && reconnect.endpoint === "source" ? styles.edgeEndpointHandleActive : "",
                        ].join(" ")}
                        style={{ left: geometry.start.x - 8, top: geometry.start.y - 8 }}
                        title="拖动切换起点模块"
                        onPointerDown={(event) => startEdgeReconnect(event, edge, "source")}
                      >
                        起
                      </button>
                      <button
                        type="button"
                        className={[
                          styles.edgeEndpointHandle,
                          reconnect?.edgeId === edge.id && reconnect.endpoint === "target" ? styles.edgeEndpointHandleActive : "",
                        ].join(" ")}
                        style={{ left: geometry.end.x - 8, top: geometry.end.y - 8 }}
                        title="拖动切换终点模块"
                        onPointerDown={(event) => startEdgeReconnect(event, edge, "target")}
                      >
                        终
                      </button>
                    </div>
                  );
                })}
                {draft.nodes.map((node) => {
                  const active = selection?.kind === "node" && selection.id === node.id;
                  const pendingSource = connect.sourceId === node.id;
                  const reconnectTarget =
                    reconnectEdge &&
                    reconnect?.hoverNodeId === node.id &&
                    isValidEdgeReconnectTarget(reconnectEdge, reconnect.endpoint, node.id);
                  const nodeIssues = validationIssues.filter((issue) => issue.nodeId === node.id);
                  const nodeErrorCount = nodeIssues.filter((issue) => issue.severity === "error").length;
                  const nodeWarningCount = nodeIssues.length - nodeErrorCount;
                  return (
                    <button
                      key={node.id}
                      type="button"
                      className={[
                        styles.node,
                        nodeStatusToneClass(node.status),
                        nodeIssues.length ? styles.nodeWithIssue : "",
                        nodeErrorCount ? styles.nodeWithError : "",
                        active ? styles.nodeActive : "",
                        pendingSource ? styles.nodeConnectSource : "",
                        reconnectTarget ? styles.nodeReconnectTarget : "",
                      ].join(" ")}
                      style={{ left: node.x, top: node.y }}
                      onPointerDown={(event) => handleNodePointerDown(event, node)}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleNodeClick(node);
                      }}
                    >
                      <span className={styles.nodeTopline}>
                        <span className={styles.nodeStatusCluster}>
                          <span className={styles.nodeStatusDot} aria-hidden="true" />
                          <span className={`${styles.statusPill} ${statusClass(node.status)}`}>{statusLabel(node.status)}</span>
                        </span>
                        <span>{node.type}</span>
                      </span>
                      <strong>{node.label}</strong>
                      <span className={styles.nodeMeta}>
                        <GitBranchPlus size={14} />
                        {node.agentKey || "未绑定 agent"}
                      </span>
                      {nodeIssues.length ? (
                        <span className={nodeErrorCount ? styles.nodeIssueBadgeError : styles.nodeIssueBadgeWarning}>
                          {nodeErrorCount ? `错误 ${nodeErrorCount}` : `警告 ${nodeWarningCount}`}
                        </span>
                      ) : null}
                      <small>{node.routeCondition || "未设置路由条件"}</small>
                    </button>
                  );
                })}
                </div>
              </div>
            </div>
          )}
        </main>

        <aside className={styles.inspector} aria-label="流程模块配置">
          <div className={styles.inspectorHeader}>
            <p>
              {selectedNode
                ? "当前选中模块"
                : selectedEdge
                  ? "当前选中路由"
                  : "唯一事实来源"}
            </p>
            <strong>{draft?.path || "workspace/prompts/research/flow_canvas.json"}</strong>
            {selectedNode ? <span className={styles.selectionSummary}>{selectedNode.label} / {selectedNode.agentKey || selectedNode.id}</span> : null}
            {selectedEdge ? (
              <span className={styles.selectionSummary}>
                {(draft?.nodes.find((node) => node.id === selectedEdge.source)?.label ?? selectedEdge.source)}
                {" -> "}
                {(draft?.nodes.find((node) => node.id === selectedEdge.target)?.label ?? selectedEdge.target)}
              </span>
            ) : null}
            <span className={saveStatusClass}>
              {saveMessage || (validationErrors.length ? `契约错误 ${validationErrors.length} 项` : dirty ? "有未保存修改" : `已同步 ${draft?.updatedAt ?? ""}`)}
            </span>
          </div>

          <div className={styles.inspectorBody}>
            <nav className={styles.inspectorTabs} aria-label="画布侧栏">
              <button
                type="button"
                className={inspectorView === "properties" ? `${styles.inspectorTab} ${styles.inspectorTabActive}` : styles.inspectorTab}
                onClick={() => setInspectorView("properties")}
                aria-pressed={inspectorView === "properties"}
              >
                属性
              </button>
              <button
                type="button"
                className={inspectorView === "issues" ? `${styles.inspectorTab} ${styles.inspectorTabActive}` : styles.inspectorTab}
                onClick={() => setInspectorView("issues")}
                aria-pressed={inspectorView === "issues"}
              >
                错误警告
                <span className={styles.inspectorTabBadge}>
                  {validationErrors.length}/{validationWarnings.length}
                </span>
              </button>
            </nav>

            <div className={styles.inspectorContent}>
              {inspectorView === "issues" ? (
                <section className={styles.issuePanel} aria-label="错误与警告">
              <div className={styles.issueSummary}>
                <div className={validationErrors.length ? styles.issueSummaryError : styles.issueSummaryOk}>
                  <span>错误</span>
                  <strong>{validationErrors.length}</strong>
                </div>
                <div className={validationWarnings.length ? styles.issueSummaryWarning : styles.issueSummaryOk}>
                  <span>警告</span>
                  <strong>{validationWarnings.length}</strong>
                </div>
              </div>
              {connectionMessage ? <p className={styles.validationConnectionNotice}>{connectionMessage}</p> : null}
              {validationIssues.length ? (
                <div className={styles.issueList}>
                  {validationIssues.map((issue, index) => {
                    const relatedNode = issue.nodeId ? draft?.nodes.find((node) => node.id === issue.nodeId) : null;
                    const relatedEdge = issue.edgeId
                      ? draft?.edges.find((edge) => edge.id === issue.edgeId)
                      : issue.source && issue.target
                        ? draft?.edges.find((edge) => edge.source === issue.source && edge.target === issue.target)
                        : null;
                    const relatedSource = relatedEdge ? draft?.nodes.find((node) => node.id === relatedEdge.source) : null;
                    const relatedTarget = relatedEdge ? draft?.nodes.find((node) => node.id === relatedEdge.target) : null;
                    const issueSubject = relatedNode
                      ? `${relatedNode.label} / ${relatedNode.agentKey || relatedNode.id}`
                      : relatedEdge
                        ? `${relatedSource?.label ?? relatedEdge.source} -> ${relatedTarget?.label ?? relatedEdge.target}`
                        : issue.edgeId || issue.nodeId || issue.code;
                    return (
                      <article
                        key={`${issue.code}:${issue.edgeId || issue.nodeId || issue.message}`}
                        className={[
                          styles.issueCard,
                          issue.severity === "error" ? styles.issueCardError : styles.issueCardWarning,
                        ].join(" ")}
                      >
                        <div className={styles.issueCardHeader}>
                          <span className={issue.severity === "error" ? styles.validationIssueError : styles.validationIssueWarning}>
                            {issue.severity === "error" ? `错误 ${index + 1}` : `警告 ${index + 1}`}
                          </span>
                          <code>{issue.code}</code>
                        </div>
                        <div className={styles.issueCardBody}>
                          <span>影响对象</span>
                          <strong>{issueSubject}</strong>
                          <span>原因</span>
                          <p>{readableResearchFlowIssueMessage(issue)}</p>
                          <span>建议处理</span>
                          <p>{researchFlowIssueAdvice(issue)}</p>
                        </div>
                        <div className={styles.issueMeta}>
                          <code>{issue.edgeId || issue.nodeId || (issue.source && issue.target ? `${issue.source}->${issue.target}` : issue.code)}</code>
                          {(issue.edgeId || issue.nodeId || (issue.source && issue.target)) ? (
                            <button className={styles.issueFocusButton} type="button" onClick={() => focusValidationIssue(issue)}>
                              定位
                            </button>
                          ) : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className={styles.issueEmpty}>
                  <strong>契约校验通过</strong>
                  <span>当前画布没有错误或警告，可以保存并执行。</span>
                </div>
              )}
            </section>
          ) : selectedNode ? (
            <fieldset className={styles.editorStack} disabled={!canvasEditable}>
              <label>
                模块名称
                <input value={selectedNode.label} onChange={(event) => updateNode(selectedNode.id, { label: event.target.value })} />
              </label>
              <div className={styles.twoColumns}>
                <label>
                  类型
                  <select
                    value={selectedNode.type}
                    onChange={(event) => updateNode(selectedNode.id, { type: event.target.value })}
                  >
                    {NODE_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  状态
                  <select
                    value={selectedNode.status}
                    onChange={(event) => updateNode(selectedNode.id, { status: event.target.value })}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                Agent 模板
                <select value={selectedNode.agentKey} onChange={(event) => applyAgentBinding(agentOptions.find((agent) => agent.key === event.target.value))}>
                  <option value="">不绑定</option>
                  {agentOptions.map((agent) => (
                    <option key={agent.key} value={agent.key}>
                      {agent.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                LLM 配置
                <select
                  value={selectedNodeAgent?.llmConfigId ?? ""}
                  disabled={!selectedNodeAgent || saveAgentMutation.isPending}
                  onChange={(event) => {
                    if (!selectedNodeAgent) {
                      return;
                    }
                    saveAgentMutation.mutate({ ...selectedNodeAgent, llmConfigId: event.target.value });
                  }}
                >
                  <option value="">未绑定</option>
                  {llmOptions.map((option) => (
                    <option key={option.configId} value={option.configId}>
                      {option.label} / {option.model}
                    </option>
                  ))}
                </select>
              </label>
              {selectedNode.llmConfigId ? (
                <p className={styles.fieldHint}>旧节点级 LLM 已不作为主路径；当前以全局 Agent 配置为准。</p>
              ) : null}
              <div className={styles.twoColumns}>
                <label>
                  Prompt Key
                  <input
                    value={selectedNode.promptKey}
                    onChange={(event) => updateNode(selectedNode.id, { promptKey: event.target.value })}
                  />
                </label>
                <label>
                  Agent Key
                  <input
                    value={selectedNode.agentKey}
                    onChange={(event) => updateNode(selectedNode.id, { agentKey: event.target.value })}
                  />
                </label>
              </div>
              <label>
                进入条件
                <textarea
                  value={selectedNode.routeCondition}
                  onChange={(event) => updateNode(selectedNode.id, { routeCondition: event.target.value })}
                />
              </label>
              <label>
                模块说明
                <textarea
                  value={selectedNode.description}
                  onChange={(event) => updateNode(selectedNode.id, { description: event.target.value })}
                />
              </label>
              <div className={styles.templatePanel}>
                <div className={styles.templateBlock}>
                  <span>当前模块模板</span>
                  <select
                    value={selectedNodeTemplateKey}
                    onChange={(event) => {
                      const template = event.target.value === "__custom__" ? null : findResearchModuleTemplate(event.target.value, moduleTemplates);
                      if (!template) {
                        setSaveMessage("当前模块使用自定义模板。");
                        setSaveStatus("idle");
                        return;
                      }
                      updateNode(selectedNode.id, applyResearchModuleTemplateToNode(template));
                      setSaveMessage(`已套用模块模板：${template.label}`);
                    }}
                  >
                    <option value="__custom__">自定义</option>
                    {moduleTemplateGroups.map((group) => (
                      <optgroup key={group} label={group}>
                        {moduleTemplates.filter((template) => template.group === group).map((template) => (
                          <option key={template.key} value={template.key}>
                            {template.label}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <div className={styles.templateHint} aria-label="模板说明">
                  <strong>{selectedNodeTemplate?.label || selectedNode.label}</strong>
                  <span>
                    {selectedNodeTemplate
                      ? `${selectedNodeTemplate.routeCondition} · ${selectedNodeTemplate.description}`
                      : "当前模块没有完全匹配的预设模板，保留手动编辑。"}
                  </span>
                </div>
                <div className={styles.templateActions}>
                  <button className={styles.secondaryButton} type="button" onClick={saveSelectedNodeAsTemplate}>
                    保存为模块模板
                  </button>
                </div>
              </div>
              <div className={styles.contractPanel}>
                <div className={styles.contractBlock}>
                  <span>输入契约</span>
                  <div className={styles.contractChips}>
                    {selectedNodeContract?.inputs.length ? (
                      selectedNodeContract.inputs.map((group, index) => (
                        <span key={`${selectedNode.id}-input-${index}`} className={styles.contractChip}>
                          {group.join(" / ")}
                        </span>
                      ))
                    ) : (
                      <span className={styles.contractChipMuted}>无</span>
                    )}
                  </div>
                </div>
                <div className={styles.contractBlock}>
                  <span>输出契约</span>
                  <div className={styles.contractChips}>
                    {selectedNodeContract ? (
                      Object.entries(selectedNodeContract.outputs).map(([condition, outputs]) => (
                        <span key={`${selectedNode.id}-output-${condition}`} className={styles.contractChip}>
                          {condition}: {outputs.join(" / ")}
                        </span>
                      ))
                    ) : (
                      <span className={styles.contractChipMuted}>未知模块</span>
                    )}
                  </div>
                </div>
              </div>
            </fieldset>
          ) : selectedEdge ? (
            <fieldset className={styles.editorStack} disabled={!canvasEditable}>
              <label>
                路由名称
                <input value={selectedEdge.label} onChange={(event) => updateEdge(selectedEdge.id, { label: event.target.value })} />
              </label>
              <div className={styles.twoColumns}>
                <label>
                  起点模块
                  <select
                    value={selectedEdge.source}
                    onChange={(event) => {
                      const nextSource = event.target.value;
                      if (!draft || !selectedEdge) {
                        return;
                      }
                      if (!isValidResearchFlowConnection(draft, nextSource, selectedEdge.target, selectedEdge.condition, selectedEdge.id, selectedEdge.type)) {
                        setConnectionMessage(`无法把起点切换到 ${draft.nodes.find((node) => node.id === nextSource)?.label || nextSource}。`);
                        return;
                      }
                      setConnectionMessage("");
                      updateEdge(selectedEdge.id, { source: nextSource });
                    }}
                  >
                    {draft?.nodes.map((node) => (
                      <option
                        key={node.id}
                        value={node.id}
                        disabled={node.id === selectedEdge.target || !isValidResearchFlowConnection(draft ?? { nodes: [], edges: [] }, node.id, selectedEdge.target, selectedEdge.condition, selectedEdge.id, selectedEdge.type)}
                      >
                        {node.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  终点模块
                  <select
                    value={selectedEdge.target}
                    onChange={(event) => {
                      const nextTarget = event.target.value;
                      if (!draft || !selectedEdge) {
                        return;
                      }
                      if (!isValidResearchFlowConnection(draft, selectedEdge.source, nextTarget, selectedEdge.condition, selectedEdge.id, selectedEdge.type)) {
                        setConnectionMessage(`无法把终点切换到 ${draft.nodes.find((node) => node.id === nextTarget)?.label || nextTarget}。`);
                        return;
                      }
                      setConnectionMessage("");
                      updateEdge(selectedEdge.id, { target: nextTarget });
                    }}
                  >
                    {draft?.nodes.map((node) => (
                      <option
                        key={node.id}
                        value={node.id}
                        disabled={node.id === selectedEdge.source || !isValidResearchFlowConnection(draft ?? { nodes: [], edges: [] }, selectedEdge.source, node.id, selectedEdge.condition, selectedEdge.id, selectedEdge.type)}
                      >
                        {node.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                箭头类型
                <select
                  value={selectedEdge.type || defaultEdgeTypeForCondition(selectedEdge.condition)}
                  onChange={(event) => {
                    const option = EDGE_TYPE_OPTIONS.find((item) => item.value === event.target.value);
                    updateEdge(selectedEdge.id, {
                      type: event.target.value,
                      condition: option?.condition ?? selectedEdge.condition,
                    });
                  }}
                >
                  {EDGE_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                触发条件
                <select
                  value={normalizeEdgeCondition(selectedEdge.condition)}
                  onChange={(event) => {
                    const condition = normalizeEdgeCondition(event.target.value);
                    updateEdge(selectedEdge.id, {
                      condition,
                      type: defaultEdgeTypeForCondition(condition),
                    });
                  }}
                >
                  {EDGE_CONDITION_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className={styles.templatePanel}>
                <div className={styles.templateBlock}>
                  <span>线模板</span>
                  <select
                    value={selectedEdgeTemplateKey}
                    onChange={(event) => {
                      const template = event.target.value === "__custom__" ? null : findResearchEdgeTemplate(event.target.value, edgeTemplates);
                      if (!template) {
                        setSaveMessage("当前连线使用自定义模板。");
                        setSaveStatus("idle");
                        return;
                      }
                      if (
                        draft &&
                        !isValidResearchFlowConnection(
                          draft,
                          selectedEdge.source,
                          selectedEdge.target,
                          template.condition,
                          selectedEdge.id,
                          template.type,
                        )
                      ) {
                        setConnectionMessage(`无法套用线模板「${template.label}」，当前起点和终点的输入输出契约不匹配。`);
                        setSaveMessage("线模板未套用。请先切换起点/终点，或选择匹配当前模块契约的模板。");
                        setSaveStatus("error");
                        return;
                      }
                      setConnectionMessage("");
                      updateEdge(selectedEdge.id, applyResearchEdgeTemplateToEdge(template));
                      setSaveMessage(`已套用线模板：${template.label}`);
                    }}
                  >
                    <option value="__custom__">自定义</option>
                    {edgeTemplateGroups.map((group) => (
                      <optgroup key={group} label={group}>
                        {edgeTemplates.filter((template) => template.group === group).map((template) => (
                          <option key={template.key} value={template.key}>
                            {template.label}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <div className={styles.templateHint} aria-label="模板说明">
                  <strong>{selectedEdgeTemplate?.label || edgeTypeLabel(selectedEdge.type || defaultEdgeTypeForCondition(selectedEdge.condition))}</strong>
                  <span>
                    {selectedEdgeTemplate
                      ? `${edgeConditionLabel(selectedEdgeTemplate.condition)} · ${selectedEdgeTemplate.description}`
                      : "当前连线没有完全匹配的模板，可继续手工编辑条件与箭头类型。"}
                  </span>
                </div>
                <div className={styles.templateActions}>
                  <button className={styles.secondaryButton} type="button" onClick={saveSelectedEdgeAsTemplate}>
                    保存为线模板
                  </button>
                </div>
              </div>
              <div className={styles.edgeTypeHint}>
                <strong>{edgeTypeLabel(selectedEdge.type || defaultEdgeTypeForCondition(selectedEdge.condition))}</strong>
                <span>{edgeTypeDescription(selectedEdge.type || defaultEdgeTypeForCondition(selectedEdge.condition))}</span>
              </div>
              <div className={styles.edgeConditionHint}>
                <strong>{edgeConditionLabel(selectedEdge.condition)}</strong>
                <span>{edgeConditionDescription(selectedEdge.condition)}</span>
              </div>
              <div className={styles.edgePair}>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.source)?.label ?? selectedEdge.source}</span>
                <strong>→</strong>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.target)?.label ?? selectedEdge.target}</span>
              </div>
              <div className={styles.contractPanel}>
                <div className={styles.contractBlock}>
                  <span>源输出</span>
                  <div className={styles.contractChips}>
                    {selectedEdgeSourceContract ? (
                      Object.entries(selectedEdgeSourceContract.outputs).map(([condition, outputs]) => (
                        <span key={`${selectedEdge.id}-source-${condition}`} className={styles.contractChip}>
                          {condition}: {outputs.join(" / ")}
                        </span>
                      ))
                    ) : (
                      <span className={styles.contractChipMuted}>未知模块</span>
                    )}
                  </div>
                </div>
                <div className={styles.contractBlock}>
                  <span>目标输入</span>
                  <div className={styles.contractChips}>
                    {selectedEdgeTargetContract?.inputs.length ? (
                      selectedEdgeTargetContract.inputs.map((group, index) => (
                        <span key={`${selectedEdge.id}-target-${index}`} className={styles.contractChip}>
                          {group.join(" / ")}
                        </span>
                      ))
                    ) : (
                      <span className={styles.contractChipMuted}>无</span>
                    )}
                  </div>
                </div>
              </div>
              {selectedEdgeIssues.length ? (
                <div className={styles.edgeIssueList} aria-label="路由契约问题">
                  {selectedEdgeIssues.slice(0, 3).map((issue) => (
                    <div key={`${issue.code}:${issue.edgeId || issue.nodeId || issue.message}`} className={styles.validationIssue}>
                      <span className={issue.severity === "error" ? styles.validationIssueError : styles.validationIssueWarning}>
                        {issue.severity === "error" ? "错误" : "警告"}
                      </span>
                      <p>{issue.message}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </fieldset>
          ) : (
            <div className={styles.emptyInspector}>
              <strong>选择一个模块或路由</strong>
              <span>点击画布节点可编辑状态、提示词、LLM 和进入条件；开启连线后先点起点再点目标。</span>
              </div>
            )}
            </div>
          </div>
        </aside>
      </div>
      {leaveGuardOpen ? (
        <div className={styles.leaveGuardOverlay}>
          <div
            className={styles.leaveGuardPanel}
            role="dialog"
            aria-modal="true"
            aria-labelledby="research-flow-leave-guard-title"
          >
            <div className={styles.leaveGuardCopy}>
              <p>未保存修改</p>
              <h2 id="research-flow-leave-guard-title">{leaveGuardTitle}</h2>
              <span>{leaveGuardBody}</span>
            </div>
            <div className={styles.leaveGuardActions}>
              <button
                className={styles.primaryButton}
                type="button"
                onClick={handleSaveAndLeave}
                disabled={!draft || leaveGuardSaving || validationErrors.length > 0}
              >
                <Save size={16} />
                {validationErrors.length > 0 ? "先修复契约" : leaveGuardSaveLabel}
              </button>
              <button className={styles.dangerButton} type="button" onClick={handleDiscardAndLeave} disabled={leaveGuardSaving}>
                {leaveGuardDiscardLabel}
              </button>
              <button className={styles.secondaryButton} type="button" onClick={handleCancelLeave} disabled={leaveGuardSaving}>
                取消
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
