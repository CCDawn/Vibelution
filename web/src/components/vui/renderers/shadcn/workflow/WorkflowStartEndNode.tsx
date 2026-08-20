import type { NodeProps } from "@xyflow/react";

import type {
  WorkflowNodeRunStatus,
  WorkflowNodeVisualKind,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { readWorkflowReconnectMagnets } from "./workflowEdgeAnchors";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowStartEndNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const kind = (props.data.visualKind as WorkflowNodeVisualKind) || "start";
  const visualKind = kind === "end" ? "end" : "start";
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  const layoutMode = props.data.layoutMode === "serpentine" ? "serpentine" : "stage-columns";
  const description = props.data.description ? String(props.data.description) : "";
  // Start polarity stays "no target handle" by default, but a display-layer
  // edge into the start node (e.g. the hypothesis-first region's readiness
  // edge onto source_finding) makes ELK assign a real target port — mirror it
  // or React Flow silently drops the edge for a missing handle.
  const hasAssignedTargetPort = Object.keys(portSides?.target ?? {}).length > 0;
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind={visualKind}
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      primaryRoleKey={props.data.primaryRoleKey ? String(props.data.primaryRoleKey) : undefined}
      subtitle={layoutMode === "serpentine" ? description || (visualKind === "start" ? "研究流程起点" : "形成可提交结果包") : visualKind === "start" ? "起点" : "终点"}
      showTargetHandle={visualKind !== "start" || hasAssignedTargetPort}
      showSourceHandle={visualKind !== "end"}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status })}
      className={
        visualKind === "start"
          ? "border-[color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))]"
          : ""
      }
      layoutMode={layoutMode}
      reconnectMagnets={readWorkflowReconnectMagnets(props.data)}
    />
  );
}
