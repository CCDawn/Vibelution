import type { NodeProps } from "@xyflow/react";

import type {
  WorkflowNodeRunStatus,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowSystemTaskNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  const layoutMode = props.data.layoutMode === "serpentine" ? "serpentine" : "stage-columns";
  const description = props.data.description ? String(props.data.description) : "";
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="system_task"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      attempt={attempt}
      subtitle={layoutMode === "serpentine" ? description || "受控系统执行" : "系统执行"}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status, attempt })}
      className="bg-[var(--vui-surface-row)]"
      layoutMode={layoutMode}
    />
  );
}
