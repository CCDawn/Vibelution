import type { NodeProps } from "@xyflow/react";
import { UserCheck } from "lucide-react";

import type { WorkflowNodeRunStatus } from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowHumanGateNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const isCurrent = Boolean(props.data.isRuntimeCurrent);
  const pending = Boolean(props.data.hasPendingHumanTask) || status === "waiting_human";
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="human_gate"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={isCurrent}
      attempt={attempt}
      subtitle={pending ? "需人工确认" : "人工门禁"}
      title={workflowNodeTooltip({
        label,
        status,
        attempt,
        blockedReason: props.data.blockedReason ? String(props.data.blockedReason) : null,
      })}
      badge={
        <span className="inline-flex items-center gap-0.5 rounded-full border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--state-warning)]">
          <UserCheck className="h-3 w-3" aria-hidden />
          人工
        </span>
      }
    />
  );
}
