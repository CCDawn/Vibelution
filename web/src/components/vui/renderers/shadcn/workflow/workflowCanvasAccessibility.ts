import type { WorkflowNodeRunStatus, WorkflowNodeVisualKind } from "../../../product/workflow/workflowCanvasTypes";
import { nodeStatusLabel } from "./workflowCanvasState";

const KIND_LABEL: Record<WorkflowNodeVisualKind, string> = {
  agent_task: "Agent 任务",
  human_gate: "人工门禁",
  system_task: "系统任务",
  decision: "条件决策",
  start: "流程起点",
  end: "流程终点",
};

export function workflowNodeAriaLabel(options: {
  label: string;
  visualKind: WorkflowNodeVisualKind;
  status: WorkflowNodeRunStatus;
  isRuntimeCurrent?: boolean;
  primaryAgentId?: string;
  attempt?: number;
}): string {
  const parts = [
    options.label,
    KIND_LABEL[options.visualKind] ?? options.visualKind,
    nodeStatusLabel(options.status),
  ];
  if (options.isRuntimeCurrent) parts.push("运行当前");
  if (options.primaryAgentId) parts.push(`负责 ${options.primaryAgentId}`);
  if (options.attempt && options.attempt > 1) parts.push(`第 ${options.attempt} 次`);
  return parts.join("，");
}

export function workflowNodeTooltip(options: {
  label: string;
  status: WorkflowNodeRunStatus;
  primaryAgentId?: string;
  attempt?: number;
  blockedReason?: string | null;
}): string {
  const lines = [
    options.label,
    `状态：${nodeStatusLabel(options.status)}`,
    options.primaryAgentId ? `Agent：${options.primaryAgentId}` : "Agent：未绑定",
  ];
  if (options.attempt && options.attempt > 0) lines.push(`执行次数：${options.attempt}`);
  if (options.blockedReason) lines.push(`原因：${options.blockedReason}`);
  return lines.join("\n");
}
