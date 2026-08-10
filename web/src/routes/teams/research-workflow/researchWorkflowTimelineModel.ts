import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { getNodeAdapter } from "./nodeAdapterModel";

type WorkflowEvent = NonNullable<WorkflowRunRecord["events"]>[number];

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
  "run.queued": "运行已创建",
  LeaseAcquired: "执行租约已获取",
  LeaseHeartbeat: "执行心跳",
  LeaseExpired: "执行租约超时",
  NodeRunTransitioned: "节点状态已更新",
  ArtifactProduced: "产物已生成",
  ArtifactReused: "验证产物已复用",
  QualityGateEvaluated: "质量门已评估",
  BudgetReserved: "预算已预留",
  BudgetSettled: "预算已结算",
  BudgetExceeded: "预算已耗尽",
  HumanDecisionRecorded: "人工决策已记录",
  TaskBundleCancelled: "并行任务组已取消",
  ActionIssued: "系统动作已发出",
  ObservationRecorded: "系统观测已记录",
  CommandReceiptRecorded: "命令回执已记录",
  RunForked: "修订运行已分叉",
  "iteration.decision_applied": "迭代决策已执行",
  "binding.rebind_node": "节点 Agent 已换绑",
  "session_binding.bound": "精确会话已绑定",
  "node.command.applied": "节点命令已执行",
};

function text(event: WorkflowEvent, key: string): string {
  const value = event[key];
  return value === null || value === undefined ? "" : String(value);
}

function groupIdentity(event: WorkflowEvent): { key: string; title: string } {
  const nodeId = text(event, "nodeId");
  const attempt = text(event, "nodeAttempt") || text(event, "attempt");
  if (nodeId) {
    const label = getNodeAdapter(nodeId)?.label || nodeId.replace(/_/g, " ");
    return {
      key: `node:${nodeId}:attempt:${attempt || "current"}`,
      title: attempt ? `${label} · 第 ${attempt} 次尝试` : label,
    };
  }
  const handoffId = text(event, "handoffId");
  if (handoffId) return { key: `handoff:${handoffId}`, title: "节点交接" };
  const checkpointId = text(event, "checkpointId");
  if (checkpointId) return { key: `checkpoint:${checkpointId}`, title: "检查点与恢复" };
  return { key: "run", title: "运行治理" };
}

export function buildResearchTimelineGroups(
  events: WorkflowRunRecord["events"] = [],
): ResearchTimelineGroup[] {
  const groups = new Map<string, ResearchTimelineGroup>();
  for (const event of events ?? []) {
    const identity = groupIdentity(event);
    const group = groups.get(identity.key) ?? { ...identity, items: [] };
    const eventType = text(event, "type");
    group.items.push({
      key: text(event, "eventId") || `${text(event, "sequence")}:${eventType}`,
      label: EVENT_LABELS[eventType] || "运行状态已更新",
      status: text(event, "status") || text(event, "decision") || text(event, "outcome"),
      occurredAt: text(event, "occurredAt") || text(event, "createdAt") || text(event, "capturedAt"),
    });
    groups.set(identity.key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: group.items.slice().reverse(),
  })).reverse();
}
