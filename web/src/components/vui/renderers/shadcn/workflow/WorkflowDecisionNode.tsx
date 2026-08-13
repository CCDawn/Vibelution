import type { NodeProps } from "@xyflow/react";
import { GitBranch } from "lucide-react";

import type {
  WorkflowNodeRunStatus,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { workflowNodeTooltip } from "./workflowCanvasAccessibility";
import { WorkflowNodeChrome } from "./WorkflowNodeChrome";

/** Outcome label map for decision source handles (definition contract). */
export const DECISION_OUTCOME_LABELS: Record<string, string> = {
  rerun: "重跑",
  revise: "修正",
  promote: "晋升",
  rollback: "回滚",
  stop: "停止",
};

export function WorkflowDecisionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const status = (props.data.status as WorkflowNodeRunStatus) || "pending";
  const attempt = Number(props.data.attempt ?? 0) || undefined;
  const portSides = props.data.portSides as
    | { source: Record<string, WorkflowPortSide>; target: Record<string, WorkflowPortSide> }
    | undefined;
  const layoutMode = props.data.layoutMode === "serpentine" ? "serpentine" : "stage-columns";
  const description = props.data.description ? String(props.data.description) : "";
  // Real current-run outgoing handles (definition edge list), never a
  // hardcoded capability list. `revise` has no current-run edge and therefore
  // no handle here; it stays a declared outcome only (P1-4).
  const sourceHandleIds = Array.isArray(props.data.sourceHandleIds)
    ? (props.data.sourceHandleIds as string[])
    : [];
  const sourceHandles = sourceHandleIds.map((id) => ({
    id,
    label: DECISION_OUTCOME_LABELS[id] ?? id,
  }));
  return (
    <WorkflowNodeChrome
      label={label}
      visualKind="decision"
      status={status}
      selected={Boolean(props.selected)}
      isRuntimeCurrent={Boolean(props.data.isRuntimeCurrent)}
      attempt={attempt}
      subtitle={layoutMode === "serpentine" ? description || "基于证据选择晋升、修订、回滚或停止" : "条件分支"}
      decisionLayout
      sourceHandles={sourceHandles}
      portSides={portSides}
      title={workflowNodeTooltip({ label, status, attempt })}
      badge={
        <span className="inline-flex items-center gap-0.5 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--fg-secondary)]">
          <GitBranch className="h-3 w-3" aria-hidden />
          分支
        </span>
      }
      layoutMode={layoutMode}
    />
  );
}
