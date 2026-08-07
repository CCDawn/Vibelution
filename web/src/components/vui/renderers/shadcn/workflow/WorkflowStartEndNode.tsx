import type { NodeProps } from "@xyflow/react";

import type {
  WorkflowNodeRunStatus,
  WorkflowNodeVisualKind,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowStartEndNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const kind = (props.data.visualKind as WorkflowNodeVisualKind) || "start";
  const visualKind = kind === "end" ? "end" : "start";
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind={visualKind}
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      subtitle={visualKind === "start" ? "起点" : "终点"}
      showTargetHandle={visualKind !== "start"}
      showSourceHandle={visualKind !== "end"}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status })}
      className={
        visualKind === "start"
          ? "border-[color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))]"
          : ""
      }
    />
  );
}
