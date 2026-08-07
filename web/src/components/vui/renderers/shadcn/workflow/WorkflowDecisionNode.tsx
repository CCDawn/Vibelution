import type { NodeProps } from "@xyflow/react";
import { GitBranch } from "lucide-react";

import type {
  WorkflowNodeRunStatus,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowDecisionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="decision"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      attempt={attempt}
      subtitle="条件分支"
      decisionLayout
      sourceHandles={[
        { id: "rerun", label: "重跑" },
        { id: "promote", label: "晋升" },
        { id: "rollback", label: "回滚" },
        { id: "stop", label: "停止" },
      ]}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status, attempt })}
      badge={
        <span className="inline-flex items-center gap-0.5 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--fg-secondary)]">
          <GitBranch className="h-3 w-3" aria-hidden />
          分支
        </span>
      }
    />
  );
}
