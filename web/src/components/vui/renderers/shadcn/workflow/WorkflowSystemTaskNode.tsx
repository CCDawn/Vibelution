import type { NodeProps } from "@xyflow/react";

import type { WorkflowNodeRunStatus } from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowSystemTaskNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="system_task"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      attempt={attempt}
      subtitle="系统执行"
      title={workflowNodeTooltip({ label, status, attempt })}
      className="bg-[var(--vui-surface-row)]"
    />
  );
}
