import type { NodeProps } from "@xyflow/react";
import { UserCheck } from "lucide-react";

import type {
  WorkflowNodeRunStatus,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowKnowledgeBadge } from "./WorkflowKnowledgeBadge";
import { readWorkflowReconnectMagnets } from "./workflowEdgeAnchors";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

export function WorkflowHumanGateNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const isCurrent = Boolean(props.data.isRuntimeCurrent);
  const pending = Boolean(props.data.hasPendingHumanTask) || status === "waiting_human";
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  const layoutMode = props.data.layoutMode === "serpentine" ? "serpentine" : "stage-columns";
  const description = props.data.description ? String(props.data.description) : "";
  const knowledgeBadge = (props.data.knowledgeBadge ?? null) as
    | import("../../../product/workflow/workflowCanvasTypes").WorkflowKnowledgeBadgeInput
    | null;
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="human_gate"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={isCurrent}
      attempt={attempt}
      primaryRoleKey={props.data.primaryRoleKey ? String(props.data.primaryRoleKey) : undefined}
      subtitle={layoutMode === "serpentine" ? description || (pending ? "需人工确认后才能继续" : "人工审查与冻结") : pending ? "需人工确认" : "人工门禁"}
      portSides={portSides}
      title={workflowNodeTooltip({
        label,
        status,
        attempt,
        blockedReason: props.data.blockedReason ? String(props.data.blockedReason) : null,
      })}
      badge={
        <>
          <span className="inline-flex items-center gap-0.5 rounded-full border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--state-warning)]">
            <UserCheck className="h-3 w-3" aria-hidden />
            人工
          </span>
          <WorkflowKnowledgeBadge badge={knowledgeBadge} />
        </>
      }
      layoutMode={layoutMode}
      reconnectMagnets={readWorkflowReconnectMagnets(props.data)}
    />
  );
}
