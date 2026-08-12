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
  run_forked: "运行已分叉",
  run_blocked: "运行已阻塞",
  run_succeeded: "运行已完成",
  reconciliation_required: "需要对账",
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

export function buildResearchTimelineGroups(
  events: WorkflowEventEnvelope[] = [],
): ResearchTimelineGroup[] {
  const groups = new Map<string, ResearchTimelineGroup>();
  for (const event of events ?? []) {
    const identity = groupIdentity(event);
    const group = groups.get(identity.key) ?? { ...identity, items: [] };
    const eventType = field(event, "type");
    group.items.push({
      key: field(event, "eventId") || `${field(event, "sequence")}:${eventType}`,
      label: EVENT_LABELS[eventType] || "运行状态已更新",
      status: field(event, "status") || field(event, "decision") || field(event, "outcome"),
      occurredAt: field(event, "occurredAt"),
    });
    groups.set(identity.key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: group.items.slice().reverse(),
  })).reverse();
}
