import type { NodeProps } from "@xyflow/react";

import type {
  WorkflowNodeRunStatus,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowAgentTaskNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const agent = props.data.primaryAgentId ? String(props.data.primaryAgentId) : "";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const isCurrent = Boolean(props.data.isRuntimeCurrent);
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  const layoutMode = props.data.layoutMode === "serpentine" ? "serpentine" : "stage-columns";
  const description = props.data.description ? String(props.data.description) : "";
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="agent_task"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={isCurrent}
      primaryAgentId={agent || undefined}
      attempt={attempt}
      subtitle={layoutMode === "serpentine" ? description || (agent ? "科研 Agent 已绑定" : "等待 Agent 绑定") : agent ? agent : "未绑定"}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status, primaryAgentId: agent || undefined, attempt })}
      layoutMode={layoutMode}
    />
  );
}
