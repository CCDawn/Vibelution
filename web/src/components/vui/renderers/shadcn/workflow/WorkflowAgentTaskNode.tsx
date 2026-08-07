import type { NodeProps } from "@xyflow/react";

import type { WorkflowNodeRunStatus } from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowAgentTaskNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const agent = props.data.primaryAgentId ? String(props.data.primaryAgentId) : "";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const isCurrent = Boolean(props.data.isRuntimeCurrent);
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="agent_task"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={isCurrent}
      primaryAgentId={agent || undefined}
      attempt={attempt}
      subtitle={agent ? agent : "未绑定"}
      title={workflowNodeTooltip({ label, status, primaryAgentId: agent || undefined, attempt })}
    />
  );
}
