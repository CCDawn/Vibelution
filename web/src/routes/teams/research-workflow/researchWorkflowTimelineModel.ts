import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { getNodeAdapter } from "./nodeAdapterModel";

export type ResearchTimelineItem = {
  key: string;
  label: string;
  status: string;
  occurredAt: string;
};

export type ResearchTimelineGroup = {
  key: string;
  title: string;
  items: ResearchTimelineItem[];
};

const EVENT_LABELS: Record<string, string> = {
  run_created: "运行已创建",
  command_accepted: "命令已接受",
  command_failed: "命令失败",
  node_starting: "节点启动中",
  node_running: "节点执行中",
  node_waiting_human: "等待人工确认",
  node_succeeded: "节点已完成",
  node_failed: "节点失败",
  node_blocked: "节点已阻塞",
  handoff_ready: "交接已就绪",
  handoff_accepted: "交接已接受",
  handoff_rejected: "交接已拒绝",
  budget_reserved: "预算已预留",
  budget_settled: "预算已结算",
  execution_anchor_bound: "执行锚点已绑定",
  artifact_verified: "产物已核验",
  "workflow.session_scope.resolved": "会话范围已确定",
  "workflow.child_session.created": "子会话已创建",
  "workflow.child_session.resumed": "子会话已恢复",
  "workflow.scope_attempt.retried": "范围尝试已重试",
  "workflow.hypothesis_fragment.recorded": "假说片段已记录",
  "workflow.hypothesis_aggregation.blocked": "假说聚合已阻塞",
  "workflow.hypothesis_aggregation.completed": "假说聚合已完成",
  run_forked: "运行已分叉",
  revision_forked: "修订分支已创建",
  run_blocked: "运行已阻塞",
  run_succeeded: "运行已完成",
  reconciliation_required: "需要对账",
  delivery_orchestration_completed: "交付编排已完成",
  delivery_orchestration_blocked: "交付编排已阻塞",
  delivery_orchestration_failed: "交付编排失败",
};

function field(event: WorkflowEventEnvelope, key: string): string {
  const direct = (event as unknown as Record<string, unknown>)[key];
  if (direct !== null && direct !== undefined && typeof direct !== "object") {
    return String(direct);
  }
  const nested = event.payload?.[key];
  if (nested !== null && nested !== undefined && typeof nested !== "object") {
    return String(nested);
  }
  return "";
}

function groupIdentity(event: WorkflowEventEnvelope): { key: string; title: string } {
  const nodeId = field(event, "nodeId");
  const attempt = field(event, "attempt") || field(event, "nodeAttempt");
  if (nodeId) {
    const label = getNodeAdapter(nodeId)?.label || nodeId.replace(/_/g, " ");
    return {
      key: `node:${nodeId}:attempt:${attempt || "current"}`,
      title: attempt ? `${label} · 第 ${attempt} 次尝试` : label,
    };
  }
  const handoffId = field(event, "handoffId");
  if (handoffId) return { key: `handoff:${handoffId}`, title: "节点交接" };
  const checkpointId = field(event, "checkpointId");
  if (checkpointId) return { key: `checkpoint:${checkpointId}`, title: "检查点与恢复" };
  return { key: "run", title: "运行治理" };
}

function eventLabel(event: WorkflowEventEnvelope): string {
  const eventType = field(event, "type");
  const base = EVENT_LABELS[eventType] || "运行状态已更新";
  const reason = field(event, "reason") || field(event, "detail");
  if ((eventType === "node_blocked" || eventType === "run_blocked") && reason) {
    return `${base} · ${reason}`;
  }
  return base;
}

export function buildResearchTimelineGroups(
  events: WorkflowEventEnvelope[] = [],
  options?: {
    nodeRuns?: Record<string, { nodeId: string; status?: string; attempt?: number }>;
    blockedReason?: string | null;
  },
): ResearchTimelineGroup[] {
  const projected = projectMissingBlockEvents(events, options);
  const groups = new Map<string, ResearchTimelineGroup>();
  for (const event of projected) {
    const identity = groupIdentity(event);
    const group = groups.get(identity.key) ?? { ...identity, items: [] };
    const eventType = field(event, "type");
    group.items.push({
      key: field(event, "eventId") || `${field(event, "sequence")}:${eventType}`,
      label: eventLabel(event),
      status: field(event, "status") || field(event, "decision") || field(event, "outcome") || field(event, "reason"),
      occurredAt: field(event, "occurredAt"),
    });
    groups.set(identity.key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: group.items.slice().reverse(),
  })).reverse();
}

function projectMissingBlockEvents(
  events: WorkflowEventEnvelope[],
  options?: {
    nodeRuns?: Record<string, { nodeId: string; status?: string; attempt?: number }>;
    blockedReason?: string | null;
  },
): WorkflowEventEnvelope[] {
  const nodeRuns = options?.nodeRuns;
  if (!nodeRuns) return events ?? [];
  const blockedEventNodes = new Set(
    (events ?? [])
      .filter((event) => field(event, "type") === "node_blocked")
      .map((event) => field(event, "nodeId"))
      .filter(Boolean),
  );
  const extra: WorkflowEventEnvelope[] = [];
  for (const node of Object.values(nodeRuns)) {
    if (node.status !== "blocked" || !node.nodeId || blockedEventNodes.has(node.nodeId)) {
      continue;
    }
    extra.push({
      eventId: `projected-block:${node.nodeId}:a${node.attempt ?? 0}`,
      sequence: Number.MAX_SAFE_INTEGER,
      runId: "",
      teamId: "",
      runVersion: 0,
      type: "node_blocked",
      correlationId: "",
      occurredAt: "",
      payload: {
        nodeId: node.nodeId,
        attempt: node.attempt,
        reason: options?.blockedReason || "节点已阻塞",
      },
    });
  }
  return extra.length ? [...(events ?? []), ...extra] : (events ?? []);
}
