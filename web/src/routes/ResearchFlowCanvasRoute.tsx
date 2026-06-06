import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  GitBranchPlus,
  Link2,
  Lock,
  MessageSquareText,
  MousePointer2,
  RefreshCw,
  Send,
  ShieldCheck,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent, WheelEvent } from "react";
import { Link } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  ResearchAgentConfig,
  ResearchFlowCanvas,
  ResearchFlowEdge,
  ResearchFlowNode,
  ResearchFlowValidation,
  ResearchFlowValidationIssue,
  ResearchOrganization,
  ResearchOrgMessageResponse,
  ResearchOrgProposalResponse,
} from "../api/types";
import { agentDisplayInfo } from "./agentDisplay";
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

type InspectorView = "properties" | "issues" | "organization";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 124;
const EDGE_NODE_GAP = 12;
const EDGE_CONTROL_MIN = 96;
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

const RESEARCH_ORG_MESSAGE_TYPE_OPTIONS = [
  { value: "notice", label: "通知" },
  { value: "request", label: "请求" },
  { value: "task", label: "任务" },
  { value: "report", label: "汇报" },
  { value: "escalation", label: "升级" },
  { value: "decision", label: "决策" },
];

const RESEARCH_ORG_DELIVERY_MODE_OPTIONS = [
  { value: "private", label: "私聊" },
  { value: "broadcast", label: "广播" },
  { value: "zone", label: "区域广播" },
];

const FLOW_CONDITION_EDGE_TYPES: Record<string, string[]> = {
  completed: ["success", "human_handoff"],
  needs_evidence: ["evidence_loop"],
  approved: ["approval_gate"],
  selected: ["selection"],
  failed: ["failure"],
  blocked: ["blocked"],
};

const FLOW_CANVAS_KIND = "research_flow_canvas";

const FLOW_NODE_ACTION_ALIASES: Record<string, string> = {
  research_ceo_entry: "research_ceo",
  organization_advisor_entry: "organization_advisor",
  broad_search: "broad",
  deep_search: "deep",
  evidence_review: "review",
  theme_generation: "themes",
  theme_card: "card",
};

type FlowContract = {
  inputs: string[][];
  outputs: Record<string, string[]>;
  terminal: boolean;
  expectedOutcomes?: string[];
};

const RESEARCH_FLOW_NODE_CONTRACTS: Record<string, FlowContract> = {
  research_ceo: {
    inputs: [],
    outputs: {
      completed: ["research_goal", "organization_task", "proposal_request"],
    },
    terminal: false,
  },
  organization_advisor: {
    inputs: [["research_goal"], ["organization_task"], ["proposal_request"]],
    outputs: {
      completed: ["organization_proposal", "staffing_plan"],
    },
    terminal: true,
  },
  broad: {
    inputs: [],
    outputs: {
      completed: ["sources", "research_leads", "evidence_context"],
    },
    terminal: false,
  },
  deep: {
    inputs: [["evidence_context"], ["sources"], ["evidence_requests"], ["research_leads"]],
    outputs: {
      completed: ["sources", "evidence_context", "research_leads"],
    },
    terminal: false,
  },
  review: {
    inputs: [["evidence_context"], ["sources"], ["research_leads"]],
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
      selected: ["selected_theme"],
    },
    terminal: false,
  },
  card: {
    inputs: [["candidate_themes"], ["selected_theme"]],
    outputs: {
      completed: ["theme_card"],
    },
    terminal: true,
  },
};

type ResearchModuleTemplate = Pick<
  ResearchFlowNode,
  "label" | "type" | "status" | "agentId" | "agentKey" | "promptKey" | "description" | "routeCondition"
> & {
  key: string;
  baseId: string;
  group: "Agent模块" | "自定义模板";
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

const DEFAULT_RESEARCH_MODULE_TEMPLATE_KEY = "broad_search";
const RESEARCH_MODULE_TEMPLATE_GROUPS: ResearchModuleTemplate["group"][] = ["Agent模块", "自定义模板"];
const RESEARCH_EDGE_TEMPLATE_GROUPS: ResearchEdgeTemplate["group"][] = ["主流程", "人工/异常", "自定义模板"];

const RESEARCH_MODULE_TEMPLATE_CANDIDATES = [
  {
    key: "research_ceo_entry",
    baseId: "research_ceo_entry",
    group: "Agent模块",
    label: "CEO Agent",
    type: "agent",
    status: "ready",
    agentKey: "research_ceo",
    promptKey: "research_ceo",
    description: "默认科研团队入口。CEO 接收用户研究目标，拆成组织任务，并决定是否让顾问提出新增研究员方案。",
    routeCondition: "用户提出科研目标后由 CEO 统筹。",
  },
  {
    key: "organization_advisor_entry",
    baseId: "organization_advisor_entry",
    group: "Agent模块",
    label: "组织顾问 Agent",
    type: "agent",
    status: "idle",
    agentKey: "organization_advisor",
    promptKey: "organization_advisor",
    description: "顾问根据 CEO 的组织任务设计临时科研组织，形成新增研究员、权限和通信边的提案。",
    routeCondition: "CEO 需要扩充科研团队时委托顾问。",
  },
  {
    key: "broad_search",
    baseId: "broad_search",
    group: "Agent模块",
    label: "广撒网 agent",
    type: "agent",
    status: "idle",
    agentKey: "broad",
    promptKey: "broad",
    description: "从开放目标出发，让 agent 使用真实网络和工具发现跨学科候选方向。",
    routeCondition: "输入开放目标、约束和偏好后启动。",
  },
  {
    key: "deep_search",
    baseId: "deep_search",
    group: "Agent模块",
    label: "定向深搜 agent",
    type: "agent",
    status: "idle",
    agentKey: "deep",
    promptKey: "deep",
    description: "围绕上一阶段发现的关键缺口、论文、GitHub 项目和数据集补充证据。",
    routeCondition: "有候选线索或知识上下文后继续。",
  },
  {
    key: "evidence_review",
    baseId: "evidence_review",
    group: "Agent模块",
    label: "证据审查 agent",
    type: "agent",
    status: "idle",
    agentKey: "review",
    promptKey: "review",
    description: "审查来源可靠性、论断可追溯性和缺失证据，决定是否回到补搜。",
    routeCondition: "深搜完成后进入；若证据不足则回到定向深搜。",
  },
  {
    key: "theme_generation",
    baseId: "theme_generation",
    group: "Agent模块",
    label: "主题生成 agent",
    type: "agent",
    status: "idle",
    agentKey: "themes",
    promptKey: "themes",
    description: "基于证据链生成可证伪、新颖且扣题的科研主题候选。",
    routeCondition: "证据审查通过或用户手动确认继续。",
  },
  {
    key: "theme_card",
    baseId: "theme_card",
    group: "Agent模块",
    label: "主题卡 agent",
    type: "agent",
    status: "idle",
    agentKey: "card",
    promptKey: "card",
    description: "产出赛题要求的科学假设与研究计划结构，包括数据集、方法、实验、指标和参考文献。",
    routeCondition: "用户确认主题生成 agent 的候选方向后生成正式主题卡。",
  },
];

export const RESEARCH_MODULE_TEMPLATES: ResearchModuleTemplate[] = RESEARCH_MODULE_TEMPLATE_CANDIDATES.filter((template) =>
  template.group === "Agent模块",
) as ResearchModuleTemplate[];

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
  executing = false,
  validationErrorCount,
}: {
  sessionId?: string;
  sessionLoading?: boolean;
  canvasLocked: boolean;
  dirty: boolean;
  executing?: boolean;
  validationErrorCount: number;
}) {
  if (executing) {
    return "节点正在执行中，请等待当前执行完成。";
  }
  if (typeof sessionId !== "undefined" || typeof sessionLoading !== "undefined") {
    if (!sessionId) {
      return sessionLoading ? "科研会话正在加载，加载完成后即可执行。" : "先选择一个科研会话后再执行。";
    }
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
    return "节点执行中，完成后才能锁定观察。";
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

export function researchFlowUnlockBlockReason({
  saving,
  executing,
}: {
  saving: boolean;
  executing: boolean;
}) {
  if (executing) {
    return "节点执行中，完成后才能取消锁定。";
  }
  if (saving) {
    return "画布正在保存，保存完成后才能取消锁定。";
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

export function edgeGeometry(source: ResearchFlowNode, target: ResearchFlowNode, lane: EdgeLane = { laneIndex: 0, overlapCount: 0 }): EdgeGeometry {
  const sourceCenter = nodeCenter(source);
  const targetCenter = nodeCenter(target);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const directionX = dx >= 0 ? 1 : -1;
  const directionY = dy >= 0 ? 1 : -1;
  const length = Math.hypot(dx, dy) || 1;
  const normal = { x: -dy / length, y: dx / length };
  const laneSign = lane.laneIndex < 0 ? -1 : 1;
  const laneMagnitude = Math.abs(lane.laneIndex);
  const laneOffset = lane.laneIndex === 0 ? 0 : laneSign * (20 + laneMagnitude * 28 + lane.overlapCount * 12);
  const startBase = boundaryAnchor(source, target, 1);
  const endBase = boundaryAnchor(target, source, 1);
  const start = { x: startBase.x + normal.x * laneOffset, y: startBase.y + normal.y * laneOffset };
  const end = { x: endBase.x + normal.x * laneOffset, y: endBase.y + normal.y * laneOffset };
  const spread = Math.min(
    EDGE_CONTROL_MAX,
    Math.max(EDGE_CONTROL_MIN, horizontal ? Math.abs(end.x - start.x) / 2 : Math.abs(end.y - start.y) / 2),
  );
  const arcOffset = Math.abs(laneOffset) + (lane.laneIndex === 0 ? 10 : 18) + (lane.overlapCount ? 12 : 0);
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
  const labelOffset = 22 + Math.min(24, Math.abs(laneOffset) / 2);
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

export function resolveEdgeLanes(edges: ResearchFlowEdge[], nodes: ResearchFlowNode[]) {
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
    if (crossesNode) {
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

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

function agentDisplayForFlowNode(node: ResearchFlowNode, organization?: ResearchOrganization) {
  const orgNode = organization?.agents.find((agent) => agent.agentId === node.agentId || agent.nodeId === node.id);
  const agent = orgNode?.agent as AgentInstance | null | undefined;
  return agentDisplayInfo(
    agent ?? {
      agentId: node.agentId || node.id,
      displayName: node.label,
      primaryMode: "research",
      roleKey: node.agentKey,
      promptTemplateId: node.promptKey,
      metadata: { functionalDisplayName: node.routeCondition },
    },
    "zh",
    { name: node.label, templateId: node.promptKey },
  );
}

function edgeTypeLabel(type: string) {
  return EDGE_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? "正向推进";
}

export function normalizeEdgeCondition(condition: string) {
  const normalized = condition.trim().toLowerCase();
  return EDGE_CONDITION_OPTIONS.some((option) => option.value === normalized) || FLOW_CONDITION_EDGE_TYPES[normalized]
    ? normalized
    : "completed";
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
  if (issue.code === "edge_contract_mismatch" || issue.code === "edge_io_mismatch" || issue.code === "edge_condition_not_produced" || issue.code === "target_input_unverified" || issue.code === "unknown_source_contract") {
    return "检查起点输出、终点输入和触发条件是否匹配。";
  }
  if (issue.code === "edge_condition_type_mismatch" || issue.code === "edge_type_condition_mismatch") {
    return "让箭头类型和触发条件保持同一种语义。";
  }
  if (issue.code === "flow_missing_start_node" || issue.code === "node_unreachable") {
    return "把该模块接回从起点可到达的主流程。";
  }
  if (issue.code === "duplicate_edge_pair") {
    return "删除重复路由，或为其中一条设置不同触发条件。";
  }
  if (issue.code === "duplicate_edge_id") {
    return "删除重复路由后重新添加，生成唯一 ID。";
  }
  if (issue.code === "edge_missing_endpoint") {
    return "把路由两端都连接到存在的模块。";
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
    agentId: stringField(value.agentId),
    agentKey: stringField(value.agentKey),
    promptKey: stringField(value.promptKey),
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
  node: Pick<ResearchFlowNode, "id" | "label" | "type" | "agentId" | "agentKey" | "promptKey" | "description" | "routeCondition">,
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
    agentId: node.agentId,
    agentKey: node.agentKey,
    promptKey: node.promptKey,
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
  node: Pick<ResearchFlowNode, "type" | "agentKey" | "promptKey" | "description" | "routeCondition"> & Partial<Pick<ResearchFlowNode, "label">>,
  templates: ResearchModuleTemplate[] = RESEARCH_MODULE_TEMPLATES,
) {
  const matchesTemplate = (template: ResearchModuleTemplate) =>
    template.type === node.type &&
    template.agentKey === node.agentKey &&
    template.promptKey === node.promptKey &&
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
    agentId: template.agentId,
    agentKey: template.agentKey,
    promptKey: template.promptKey,
    description: template.description,
    routeCondition: template.routeCondition,
  };
}

function researchAgentInstanceId(agent: Pick<ResearchAgentConfig, "agentId" | "agentInstanceId"> | undefined) {
  return (agent?.agentId || agent?.agentInstanceId || "").trim();
}

export function applyResearchAgentBindingToNode(agent: ResearchAgentConfig | undefined): Partial<ResearchFlowNode> {
  if (!agent) {
    return {};
  }
  return {
    agentId: researchAgentInstanceId(agent),
    agentKey: agent.key,
    promptKey: agent.key,
  };
}

type ResearchFlowNodeWithLegacyFields = ResearchFlowNode & {
  llmConfigId?: string;
};

export function normalizeResearchFlowNodesForSave(
  nodes: ResearchFlowNodeWithLegacyFields[],
  agents: ResearchAgentConfig[],
): ResearchFlowNode[] {
  const byKey = new Map(agents.map((agent) => [agent.key, agent]));
  const byId = new Map(
    agents
      .map((agent) => [researchAgentInstanceId(agent), agent] as const)
      .filter(([agentId]) => Boolean(agentId)),
  );
  return nodes.map((node) => {
    const { llmConfigId: _legacyLlmConfigId, ...nodeForSave } = node;
    const agent = (node.agentId ? byId.get(node.agentId) : undefined) ?? (node.agentKey ? byKey.get(node.agentKey) : undefined);
    if (!agent) {
      return nodeForSave;
    }
    return {
      ...nodeForSave,
      agentId: researchAgentInstanceId(agent),
      agentKey: nodeForSave.agentKey || agent.key,
      promptKey: nodeForSave.promptKey || agent.key,
    };
  });
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
  return outputs[normalizeEdgeCondition(condition)] ?? outputs.completed ?? [];
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

export function validateResearchFlowCanvasContract(canvas: Pick<ResearchFlowCanvas, "nodes" | "edges"> & Partial<Pick<ResearchFlowCanvas, "canvasKind">>): ResearchFlowValidation {
  const nodeById = new Map(canvas.nodes.map((node) => [node.id, node] as const));
  const incoming = new Map<string, ResearchFlowEdge[]>();
  const outgoing = new Map<string, ResearchFlowEdge[]>();
  const issues: ResearchFlowValidationIssue[] = [];
  const edgeIds = new Set<string>();
  const pairIds = new Set<string>();

  for (const node of canvas.nodes) {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
    if (!NODE_TYPE_OPTIONS.some((option) => option.value === node.type)) {
      issues.push(researchFlowIssue("error", "node_type_not_supported", `模块 ${node.label || node.id} 使用了不支持的类型：${node.type}。`, {
        nodeId: node.id,
      }));
    }
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
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) {
      issues.push(
        researchFlowIssue(
          "error",
          "edge_missing_endpoint",
          `路由 ${edge.id || edge.source} 必须连接两个存在的模块。`,
          { edgeId: edge.id, source: edge.source, target: edge.target },
        ),
      );
      continue;
    }
    outgoing.get(edge.source)?.push(edge);
    incoming.get(edge.target)?.push(edge);
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
  canvas: Pick<ResearchFlowCanvas, "nodes" | "edges"> & Partial<Pick<ResearchFlowCanvas, "canvasKind">>,
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
    canvasKind: canvas.canvasKind ?? FLOW_CANVAS_KIND,
    nodes: filtered.nodes,
    edges: [...filtered.edges, { id: edgeId || "__probe__", source: sourceId, target: targetId, label: "校验", condition: targetCondition, type: targetEdgeType }],
  });
  return validation.valid;
}

export function findResearchModuleTemplate(key: string, templates: ResearchModuleTemplate[] = RESEARCH_MODULE_TEMPLATES) {
  return (
    templates.find((template) => template.key === key) ??
    templates.find((template) => template.key === DEFAULT_RESEARCH_MODULE_TEMPLATE_KEY) ??
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
    agentId: template.agentId,
    agentKey: template.agentKey,
    promptKey: template.promptKey,
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
  const [connect, setConnect] = useState<ConnectState>({ active: false, sourceId: null });
  const [drag, setDrag] = useState<DragState | null>(null);
  const [pan, setPan] = useState<PanState | null>(null);
  const [reconnect, setReconnect] = useState<ReconnectState | null>(null);
  const [canvasOffset, setCanvasOffset] = useState<CanvasOffset>({ x: 0, y: 0 });
  const [canvasZoom, setCanvasZoom] = useState(1);
  const [observationMessage, setObservationMessage] = useState("");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "warning" | "error">("idle");
  const [canvasLocked, setCanvasLocked] = useState(true);
  const [inspectorView, setInspectorView] = useState<InspectorView>("properties");
  const [orgDeliveryMode, setOrgDeliveryMode] = useState("private");
  const [orgTargetAgentId, setOrgTargetAgentId] = useState("");
  const [orgZoneId, setOrgZoneId] = useState("");
  const [orgMessageType, setOrgMessageType] = useState("task");
  const [orgMessageContent, setOrgMessageContent] = useState("");
  const [orgMailboxOnly, setOrgMailboxOnly] = useState(false);
  const [orgMessageFeedback, setOrgMessageFeedback] = useState("");

  const canvasQuery = useQuery({
    queryKey: queryKeys.researchFlowCanvas(),
    queryFn: () => fetchJson<ResearchFlowCanvas>("/api/research/flow-canvas"),
    refetchInterval: canvasLocked ? 2000 : false,
    refetchIntervalInBackground: false,
  });

  const organizationQuery = useQuery({
    queryKey: queryKeys.researchOrganization(),
    queryFn: () => fetchJson<ResearchOrganization>("/api/research/organization"),
    refetchInterval: inspectorView === "organization" ? 2000 : false,
    refetchIntervalInBackground: false,
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
      const observing = canvasLocked;
      const hadDraft = Boolean(draftSignatureRef.current);
      if (observing && hadDraft) {
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
      if (!observing || !hadDraft) {
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
  }, [canvasLocked, canvasOffset, canvasQuery.data, canvasZoom]);

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
  const edgeLanes = useMemo(() => (draft ? resolveEdgeLanes(draft.edges, draft.nodes) : new Map<string, EdgeLane>()), [draft]);
  const draftValidation = useMemo(() => (draft ? validateResearchFlowCanvasContract(draft) : null), [draft]);
  const reconnectEdge = draft && reconnect ? draft.edges.find((edge) => edge.id === reconnect.edgeId) ?? null : null;
  const canvasObservationActive = canvasLocked;
  const organization = organizationQuery.data;
  const projectBinding = draft?.projectBinding;
  const canvasProjectLabel = String(projectBinding?.teamName || (projectBinding?.teamId === "research-team" ? "科研团队" : projectBinding?.projectId || "科研团队"));
  const organizationSourcePath = draft?.organizationPath || organization?.path || "workspace/research/organization_graph.json";
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
  const organizationAgents = organization?.agents ?? [];
  const activeOrganizationAgents = organizationAgents.filter((agent) => agent.status !== "archived");
  const pendingOrganizationProposals = (organization?.proposals ?? []).filter((proposal) => proposal.status !== "applied");
  const recentOrganizationAudit = [...(organization?.auditEvents ?? [])].slice(-12).reverse();
  const recentOrganizationMessages = [...(organization?.messages ?? [])].slice(-6).reverse();
  const organizationZones = organization?.zones ?? [];
  const defaultOrganizationTargetId = orgTargetAgentId || activeOrganizationAgents.find((agent) => agent.role === "ceo")?.agentId || activeOrganizationAgents[0]?.agentId || "";
  const canSendOrganizationMessage =
    Boolean(orgMessageContent.trim()) &&
    (orgDeliveryMode !== "private" || Boolean(defaultOrganizationTargetId)) &&
    (orgDeliveryMode !== "zone" || Boolean(orgZoneId));
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
          setConnectionMessage(`无法重连到 ${node.label}，路由契约不匹配。`);
          setReconnect(null);
          return;
        }
        setConnectionMessage("");
        commitDraftEdit((canvas) => ({
          ...canvas,
          edges: canvas.edges.map((item) =>
            item.id === edge.id ? { ...item, [reconnect.endpoint]: node.id } : item,
          ),
        }));
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

  useEffect(() => {
    if (!canvasLocked) {
      return;
    }
    setConnect({ active: false, sourceId: null });
    setDrag(null);
    setReconnect(null);
  }, [canvasLocked]);

  const sendOrgMessageMutation = useMutation({
    mutationFn: async () => {
      const targetAgentId = orgTargetAgentId || organizationQuery.data?.agents.find((agent) => agent.role === "ceo")?.agentId || "";
      return fetchJson<ResearchOrgMessageResponse>("/api/research/organization/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceType: "user",
          targetAgentId: orgDeliveryMode === "private" ? targetAgentId : "",
          deliveryMode: orgDeliveryMode,
          zoneId: orgDeliveryMode === "zone" ? orgZoneId : "",
          messageType: orgMessageType,
          content: orgMessageContent,
          wakeTarget: !orgMailboxOnly,
          mailboxOnly: orgMailboxOnly,
          humanOverride: true,
          createdBy: "user",
        }),
      });
    },
    onSuccess: async (result) => {
      const blockedCount = result.message.deliveries.filter((delivery) => !delivery.allowed).length;
      const deliveredCount = result.message.deliveries.length - blockedCount;
      setOrgMessageFeedback(`已投递 ${deliveredCount} 个 Agent${blockedCount ? `，拦截 ${blockedCount} 个` : ""}。`);
      setOrgMessageContent("");
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchOrganization() });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "发送失败";
      setOrgMessageFeedback(`组织通信失败: ${message}`);
    },
  });

  const applyOrgProposalMutation = useMutation({
    mutationFn: async (proposalId: string) =>
      fetchJson<ResearchOrgProposalResponse>(`/api/research/organization/proposals/${encodeURIComponent(proposalId)}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: async (result) => {
      setOrgMessageFeedback(`已应用组织提案：${result.proposal.title}`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchOrganization() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "应用失败";
      setOrgMessageFeedback(`组织提案应用失败: ${message}`);
    },
  });

  const retryOrgWakeMutation = useMutation({
    mutationFn: async (messageId: string) =>
      fetchJson<ResearchOrgMessageResponse>(`/api/research/organization/messages/${encodeURIComponent(messageId)}/retry-wake`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: async (result) => {
      const statuses = result.message.deliveries.map((delivery) => delivery.wakeStatus).filter(Boolean);
      setOrgMessageFeedback(`已重试唤醒：${statuses.join(" / ") || "无可重试消息"}`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.researchOrganization() });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "重试失败";
      setOrgMessageFeedback(`重试唤醒失败: ${message}`);
    },
  });

  const canvasEditable = false;

  const toggleCanvasLock = () => {
    setCanvasLocked(true);
    setConnectionMessage("");
    setSaveMessage("画布持续锁定，正在从科研组织图实时同步。");
    setSaveStatus("success");
    setObservationMessage("拓扑由项目组织架构决定；流程线与组织通信线保持同源。");
  };

  const commitDraftEdit = useCallback((updater: (current: ResearchFlowCanvas) => ResearchFlowCanvas, options: CommitDraftOptions = {}) => {
    void updater;
    void options;
    setSaveMessage("画布持续锁定，拓扑请通过科研组织架构调整。");
    setSaveStatus("warning");
  }, []);

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

  const handleNodePointerDown = (event: PointerEvent<HTMLDivElement>, node: ResearchFlowNode) => {
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
    setConnectionMessage("画布持续锁定，通信线请通过科研组织图调整。");
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
          <p>Project Organization Canvas</p>
          <h1>科研组织画布</h1>
          <span>持续锁定到项目组织架构；Agent 节点和通信线实时来自科研团队事实源。</span>
        </div>
        <div className={styles.headerActions}>
          <Link className={styles.secondaryButton} to="/research">
            <ArrowLeft size={16} />
            返回科研页
          </Link>
          <button className={styles.secondaryButton} type="button" onClick={fitView} disabled={!draft}>
            <MousePointer2 size={16} />
            复位视图
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => {
              canvasQuery.refetch();
              organizationQuery.refetch();
              setObservationMessage("已请求刷新科研组织图。");
            }}
            disabled={canvasQuery.isFetching || organizationQuery.isFetching}
          >
            <RefreshCw size={16} />
            刷新组织图
          </button>
          <button
            className={`${styles.primaryButton} ${styles.lockButtonActive}`}
            type="button"
            onClick={toggleCanvasLock}
            title="画布持续锁定，拓扑来自项目组织架构。"
            aria-pressed="true"
          >
            <Lock size={16} />
            持续锁定
          </button>
        </div>
      </header>

      <section className={styles.executionBar} aria-label="科研组织画布观察状态">
        <div className={styles.executionGroup}>
          <span>绑定团队</span>
          <strong>{canvasProjectLabel}</strong>
        </div>
        <div className={canvasObservationActive ? `${styles.observerStatus} ${styles.observerStatusActive}` : styles.observerStatus}>
          <span>事实来源</span>
          <strong>{organizationSourcePath}</strong>
        </div>
        <div className={styles.observerStatus}>
          <span>组织结构</span>
          <strong>{`${draft?.nodes.length ?? 0} Agent / ${draft?.edges.length ?? 0} 通信线`}</strong>
        </div>
        <p className={styles.executionHint}>
          {observationMessage || "画布持续只读同步；流程线与组织通信线使用同一份项目组织数据。"}
        </p>
      </section>

      <div className={styles.body}>
        <main className={styles.canvasShell} aria-label="科研组织画布">
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
          {!draft && canvasQuery.isLoading ? (
            <div className={styles.emptyState}>正在读取科研团队组织架构...</div>
          ) : !draft && canvasQuery.isError ? (
            <div className={styles.emptyState}>组织画布读取失败，请检查后端科研组织接口。</div>
          ) : !draft ? (
            <div className={styles.emptyState}>暂无可展示的科研团队组织架构。</div>
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
                  const display = agentDisplayForFlowNode(node, organization);
                  const canInlineEditNodeTitle = active && canvasEditable && !connect.active && !reconnect;
                  const pendingSource = connect.sourceId === node.id;
                  const reconnectTarget =
                    reconnectEdge &&
                    reconnect?.hoverNodeId === node.id &&
                    isValidEdgeReconnectTarget(reconnectEdge, reconnect.endpoint, node.id);
                  const nodeIssues = validationIssues.filter((issue) => issue.nodeId === node.id);
                  const nodeErrorCount = nodeIssues.filter((issue) => issue.severity === "error").length;
                  const nodeWarningCount = nodeIssues.length - nodeErrorCount;
                  return (
                    <div
                      key={node.id}
                      role="button"
                      tabIndex={0}
                      aria-pressed={active}
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
                      onKeyDown={(event) => {
                        if ((event.target as HTMLElement).tagName === "INPUT") {
                          return;
                        }
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          handleNodeClick(node);
                        }
                      }}
                    >
                      <span className={styles.nodeTopline}>
                        <span className={styles.nodeStatusCluster}>
                          <span className={styles.nodeStatusDot} aria-hidden="true" />
                          <span className={`${styles.statusPill} ${statusClass(node.status)}`}>{statusLabel(node.status)}</span>
                        </span>
                        <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                          {display.functionLabel}
                        </span>
                      </span>
                      {canInlineEditNodeTitle ? (
                        <input
                          className={styles.nodeTitleInput}
                          aria-label={`模块名称：${node.label || node.id}`}
                          value={node.label}
                          placeholder="模块名称"
                          onPointerDown={(event) => event.stopPropagation()}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) =>
                            commitDraftEdit((canvas) => ({
                              ...canvas,
                              nodes: canvas.nodes.map((item) =>
                                item.id === node.id ? { ...item, label: event.target.value } : item,
                              ),
                            }))
                          }
                        />
                      ) : (
                        <strong>{node.label || node.id}</strong>
                      )}
                      <span className={styles.nodeMeta}>
                        <GitBranchPlus size={14} />
                        {display.meta || node.agentKey || "科研 Agent"}
                      </span>
                      {nodeIssues.length ? (
                        <span className={nodeErrorCount ? styles.nodeIssueBadgeError : styles.nodeIssueBadgeWarning}>
                          {nodeErrorCount ? `错误 ${nodeErrorCount}` : `警告 ${nodeWarningCount}`}
                        </span>
                      ) : null}
                      <small>{node.description || node.routeCondition || "由科研组织架构同步"}</small>
                    </div>
                  );
                })}
                </div>
              </div>
            </div>
          )}
        </main>

        <aside className={styles.inspector} aria-label="科研组织配置">
          <div className={styles.inspectorHeader}>
            <p>
              {inspectorView === "organization"
                ? "科研组织通信"
                : selectedNode
                ? "当前选中 Agent"
                : selectedEdge
                  ? "当前通信线"
                  : "唯一事实来源"}
            </p>
            <strong>
              {inspectorView === "organization"
                ? organization?.path || "workspace/research/organization_graph.json"
                : organizationSourcePath}
            </strong>
            {selectedNode ? <span className={styles.selectionSummary}>{selectedNode.label} / {selectedNode.agentKey || selectedNode.id}</span> : null}
            {selectedEdge ? (
              <span className={styles.selectionSummary}>
                {(draft?.nodes.find((node) => node.id === selectedEdge.source)?.label ?? selectedEdge.source)}
                {" -> "}
                {(draft?.nodes.find((node) => node.id === selectedEdge.target)?.label ?? selectedEdge.target)}
              </span>
            ) : null}
            <span className={saveStatusClass}>
              {saveMessage || `组织图已同步 ${draft?.updatedAt ?? ""}`}
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
                详情
              </button>
              <button
                type="button"
                className={inspectorView === "issues" ? `${styles.inspectorTab} ${styles.inspectorTabActive}` : styles.inspectorTab}
                onClick={() => setInspectorView("issues")}
                aria-pressed={inspectorView === "issues"}
              >
                同步检查
                <span className={styles.inspectorTabBadge}>
                  {validationErrors.length}/{validationWarnings.length}
                </span>
              </button>
              <button
                type="button"
                className={inspectorView === "organization" ? `${styles.inspectorTab} ${styles.inspectorTabActive}` : styles.inspectorTab}
                onClick={() => setInspectorView("organization")}
                aria-pressed={inspectorView === "organization"}
              >
                组织通信
                <span className={styles.inspectorTabBadge}>
                  {pendingOrganizationProposals.length}/{organization?.auditEvents.length ?? 0}
                </span>
              </button>
            </nav>

            <div className={styles.inspectorContent}>
              {inspectorView === "organization" ? (
                <section className={styles.organizationPanel} aria-label="科研组织通信">
                  <div className={styles.organizationSummaryGrid}>
                    <div className={styles.organizationMetric}>
                      <ShieldCheck size={16} />
                      <span>Agent</span>
                      <strong>{organizationAgents.length}</strong>
                    </div>
                    <div className={styles.organizationMetric}>
                      <GitBranchPlus size={16} />
                      <span>通信边</span>
                      <strong>{organization?.edges.length ?? 0}</strong>
                    </div>
                    <div className={styles.organizationMetric}>
                      <CheckCircle2 size={16} />
                      <span>待确认</span>
                      <strong>{pendingOrganizationProposals.length}</strong>
                    </div>
                  </div>

                  {organizationQuery.isLoading ? (
                    <div className={styles.issueEmpty}>
                      <strong>正在读取组织图</strong>
                      <span>事实源来自 workspace/research/organization_graph.json。</span>
                    </div>
                  ) : null}

                  <div className={styles.organizationSectionHeader}>
                    <strong>组织图成员</strong>
                    <span>节点只表示 Agent；成员、角色和工具权限不在这里编辑，分别回到团队/Agent 管理处理。</span>
                  </div>
                  <div className={styles.organizationAgentList}>
                    {organizationAgents.map((agent) => (
                      <article key={agent.agentId} className={styles.organizationAgentCard}>
                        <div>
                          <strong>{agent.agentCode ? `${agent.agentCode} · ${agent.displayName}` : agent.displayName}</strong>
                          <span className={styles.organizationAgentMeta}>
                            {agent.employeeRank || "member"} / {agent.role || "research_agent"} / {agent.status}
                          </span>
                        </div>
                        <div className={styles.organizationBadgeRow}>
                          {agent.protected ? <span className={styles.organizationBadgeProtected}>核心保护</span> : null}
                          <span className={styles.organizationBadge}>{agent.allowedTools.length ? `${agent.allowedTools.length} tools` : "未显式授权"}</span>
                        </div>
                      </article>
                    ))}
                  </div>

                  <form
                    className={styles.organizationForm}
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (canSendOrganizationMessage && !sendOrgMessageMutation.isPending) {
                        sendOrgMessageMutation.mutate();
                      }
                    }}
                  >
                  <div className={styles.organizationSectionHeader}>
                    <strong>发送组织消息</strong>
                    <span>仅用于科研组织上下文消息；通用项目总群、@Agent 和撤回仍在对话页处理。</span>
                  </div>
                    <div className={styles.twoColumns}>
                      <label>
                        通信方式
                        <select value={orgDeliveryMode} onChange={(event) => setOrgDeliveryMode(event.target.value)}>
                          {RESEARCH_ORG_DELIVERY_MODE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        消息类型
                        <select value={orgMessageType} onChange={(event) => setOrgMessageType(event.target.value)}>
                          {RESEARCH_ORG_MESSAGE_TYPE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {orgDeliveryMode === "private" ? (
                      <label>
                        目标 Agent
                        <select value={defaultOrganizationTargetId} onChange={(event) => setOrgTargetAgentId(event.target.value)}>
                          {activeOrganizationAgents.map((agent) => (
                            <option key={agent.agentId} value={agent.agentId}>
                              {agent.agentCode ? `${agent.agentCode} · ${agent.displayName}` : agent.displayName}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    {orgDeliveryMode === "zone" ? (
                      <label>
                        目标区域
                        <select value={orgZoneId} onChange={(event) => setOrgZoneId(event.target.value)}>
                          <option value="">选择区域</option>
                          {organizationZones.map((zone) => (
                            <option key={zone.zoneId} value={zone.zoneId}>
                              {zone.label || zone.zoneId}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    <label>
                      消息正文
                      <textarea
                        value={orgMessageContent}
                        onChange={(event) => setOrgMessageContent(event.target.value)}
                        placeholder="例如：请 CEO 组织一次新颖科研主题发现，并让组织顾问评估需要新增哪些专家 Agent。"
                      />
                    </label>
                    <label className={styles.inlineToggle}>
                      <input
                        type="checkbox"
                        checked={orgMailboxOnly}
                        onChange={(event) => setOrgMailboxOnly(event.target.checked)}
                      />
                      只投递邮箱，不立即唤醒
                    </label>
                    <div className={styles.organizationActionRow}>
                      <button
                        className={styles.primaryButton}
                        type="submit"
                        disabled={!canSendOrganizationMessage || sendOrgMessageMutation.isPending}
                      >
                        <Send size={16} />
                        {sendOrgMessageMutation.isPending ? "发送中" : "发送消息"}
                      </button>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() => queryClient.invalidateQueries({ queryKey: queryKeys.researchOrganization() })}
                      >
                        <RefreshCw size={16} />
                        刷新
                      </button>
                    </div>
                    {orgMessageFeedback ? <p className={styles.fieldHint}>{orgMessageFeedback}</p> : null}
                  </form>

                  <div className={styles.organizationSectionHeader}>
                    <strong>提案面板</strong>
                    <span>这里只确认科研组织提案；通用 Agent 配置和工具权限仍由 Agent 管理承接。</span>
                  </div>
                  <div className={styles.organizationProposalList}>
                    {pendingOrganizationProposals.length ? (
                      pendingOrganizationProposals.map((proposal) => (
                        <article key={proposal.proposalId} className={styles.organizationProposalCard}>
                          <div>
                            <strong>{proposal.title}</strong>
                            <span>{proposal.riskLevel} / {proposal.status} / {proposal.actions.length} actions</span>
                          </div>
                          <button
                            className={styles.primaryButton}
                            type="button"
                            disabled={applyOrgProposalMutation.isPending}
                            onClick={() => applyOrgProposalMutation.mutate(proposal.proposalId)}
                          >
                            确认应用
                          </button>
                        </article>
                      ))
                    ) : (
                      <div className={styles.issueEmpty}>
                        <strong>暂无待确认提案</strong>
                        <span>组织顾问后续提出的增删 Agent、调权限和改通信边会出现在这里。</span>
                      </div>
                    )}
                  </div>

                  <div className={styles.organizationSectionHeader}>
                    <strong>通信消息</strong>
                    <span>优先展示投递、拦截、唤醒和重试状态。</span>
                  </div>
                  <div className={styles.organizationMessageList}>
                    {recentOrganizationMessages.map((message) => {
                      const retryable = message.deliveries.some((delivery) => delivery.wakeStatus === "skipped_busy");
                      return (
                        <article key={message.messageId} className={styles.organizationAuditCard}>
                          <div className={styles.organizationAuditHeader}>
                            <MessageSquareText size={16} />
                            <strong>{message.messageType} / {message.deliveryMode}</strong>
                            <span>{new Date(message.createdAt).toLocaleTimeString()}</span>
                          </div>
                          <p>{message.summary || message.content}</p>
                          <div className={styles.organizationBadgeRow}>
                            {message.deliveries.map((delivery) => (
                              <span key={`${message.messageId}-${delivery.targetAgentId}`} className={delivery.allowed ? styles.organizationBadge : styles.organizationBadgeBlocked}>
                                {delivery.targetAgentCode || delivery.targetAgentName || delivery.targetAgentId}: {delivery.allowed ? delivery.wakeStatus || "delivered" : delivery.reason}
                              </span>
                            ))}
                          </div>
                          {retryable ? (
                            <button
                              className={styles.secondaryButton}
                              type="button"
                              disabled={retryOrgWakeMutation.isPending}
                              onClick={() => retryOrgWakeMutation.mutate(message.messageId)}
                            >
                              <RefreshCw size={16} />
                              重试唤醒
                            </button>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>

                  <div className={styles.organizationSectionHeader}>
                    <strong>审计流</strong>
                    <span>谁发给谁、是否允许、命中哪条边、是否唤醒。</span>
                  </div>
                  <div className={styles.organizationAuditList}>
                    {recentOrganizationAudit.map((event) => (
                      <article
                        key={event.auditEventId}
                        className={[
                          styles.organizationAuditCard,
                          event.allowed ? styles.organizationAuditAllowed : styles.organizationAuditBlocked,
                        ].join(" ")}
                      >
                        <div className={styles.organizationAuditHeader}>
                          <strong>{event.eventType}</strong>
                          <span>{event.allowed ? "allowed" : "blocked"}</span>
                        </div>
                        <p>{event.summary || event.reason || "无摘要"}</p>
                        <code>
                          {event.sourceAgentId || event.sourceType || "user"} {"->"} {event.targetAgentId || event.proposalId || "organization"}
                          {event.edgeId ? ` / ${event.edgeId}` : ""}
                          {event.wakeStatus ? ` / ${event.wakeStatus}` : ""}
                        </code>
                      </article>
                    ))}
                  </div>
                </section>
              ) : inspectorView === "issues" ? (
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
                  <strong>结构校验通过</strong>
                  <span>当前流程画布没有错误或警告，可以保存并锁定观察。</span>
                </div>
              )}
            </section>
          ) : selectedNode ? (
            <section className={styles.editorStack} aria-label="Agent 详情">
              {(() => {
                const display = agentDisplayForFlowNode(selectedNode, organization);
                const orgNode = organization?.agents.find((agent) => agent.agentId === selectedNode.agentId || agent.nodeId === selectedNode.id);
                return (
                  <>
                    <div className={styles.readonlyDetailHeader}>
                      <strong>{display.name}</strong>
                      <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>{display.functionLabel}</span>
                    </div>
                    <div className={styles.readonlySpecGrid}>
                      <span>Agent ID</span>
                      <code>{selectedNode.agentId || selectedNode.id}</code>
                      <span>组织角色</span>
                      <strong>{orgNode?.role || selectedNode.agentKey || "research_agent"}</strong>
                      <span>职级</span>
                      <strong>{orgNode?.employeeRank || "member"}</strong>
                      <span>状态</span>
                      <strong>{statusLabel(selectedNode.status)}</strong>
                      <span>工具权限</span>
                      <strong>{orgNode?.allowedTools.length ? `${orgNode.allowedTools.length} tools` : "未显式授权"}</strong>
                    </div>
                    <p className={styles.readonlyDescription}>{selectedNode.description || "该 Agent 来自科研团队组织架构。"}</p>
                    <p className={styles.fieldHint}>画布持续锁定；成员/角色回团队页，工具权限回 Agent 管理，科研通信线通过组织提案确认。</p>
                  </>
                );
              })()}
            </section>
          ) : selectedEdge ? (
            <section className={styles.editorStack} aria-label="通信线详情">
              <div className={styles.edgeTypeHint}>
                <strong>{selectedEdge.label || "组织通信线"}</strong>
                <span>流程线与通讯线相同，均由科研组织图 edge 派生。</span>
              </div>
              <div className={styles.edgePair}>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.source)?.label ?? selectedEdge.source}</span>
                <strong>→</strong>
                <span>{draft?.nodes.find((node) => node.id === selectedEdge.target)?.label ?? selectedEdge.target}</span>
              </div>
              <div className={styles.readonlySpecGrid}>
                <span>Edge ID</span>
                <code>{selectedEdge.id}</code>
                <span>来源</span>
                <strong>organization_graph.json</strong>
                <span>线语义</span>
                <strong>通信线 / 流程线</strong>
              </div>
              {selectedEdgeIssues.length ? (
                <div className={styles.edgeIssueList} aria-label="路由结构问题">
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
            </section>
          ) : (
            <div className={styles.emptyInspector}>
              <strong>选择一个 Agent 或通信线</strong>
              <span>画布持续锁定到科研团队组织架构，只展示项目当前的 Agent 成员和通信关系。</span>
              </div>
            )}
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
