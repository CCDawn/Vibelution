/**
 * Shared chrome for workflow task nodes (status icon, selection, runtime current).
 */
import type { ReactNode } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  AlertTriangle,
  Ban,
  Check,
  Circle,
  GitBranch,
  Minus,
  Package,
  Play,
  SkipForward,
  UserCheck,
  X,
} from "lucide-react";

import { cn } from "../../../lib/cn";
import type { WorkflowNodeRunStatus, WorkflowNodeVisualKind } from "../../../product/workflow/workflowCanvasTypes";
import { resolveNodeStatusVisual } from "./workflowCanvasState";
import { workflowNodeAriaLabel } from "./workflowCanvasAccessibility";

export type WorkflowNodeChromeProps = {
  label: string;
  visualKind: WorkflowNodeVisualKind;
  status: WorkflowNodeRunStatus;
  selected?: boolean;
  isRuntimeCurrent?: boolean;
  primaryAgentId?: string;
  attempt?: number;
  subtitle?: string;
  badge?: ReactNode;
  title?: string;
  className?: string;
  children?: ReactNode;
  showTargetHandle?: boolean;
  showSourceHandle?: boolean;
  sourceHandles?: Array<{ id: string; label?: string }>;
  decisionLayout?: boolean;
};

function StatusIcon({ icon }: { icon: ReturnType<typeof resolveNodeStatusVisual>["icon"] }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  switch (icon) {
    case "play":
      return <Play className={cls} aria-hidden />;
    case "user":
      return <UserCheck className={cls} aria-hidden />;
    case "check":
      return <Check className={cls} aria-hidden />;
    case "x":
      return <X className={cls} aria-hidden />;
    case "ban":
      return <Ban className={cls} aria-hidden />;
    case "minus":
      return <Minus className={cls} aria-hidden />;
    case "skip":
      return <SkipForward className={cls} aria-hidden />;
    case "stale":
      return <AlertTriangle className={cls} aria-hidden />;
    case "alert":
      return <AlertTriangle className={cls} aria-hidden />;
    default:
      return <Circle className={cn(cls, "opacity-50")} aria-hidden />;
  }
}

function KindGlyph({ kind }: { kind: WorkflowNodeVisualKind }) {
  const cls = "h-3.5 w-3.5 shrink-0 text-[var(--fg-tertiary)]";
  if (kind === "human_gate") return <UserCheck className={cls} aria-hidden />;
  if (kind === "decision") return <GitBranch className={cls} aria-hidden />;
  if (kind === "system_task" || kind === "end") return <Package className={cls} aria-hidden />;
  if (kind === "start") return <Play className={cls} aria-hidden />;
  return null;
}

export function WorkflowNodeChrome({
  label,
  visualKind,
  status,
  selected = false,
  isRuntimeCurrent = false,
  primaryAgentId,
  attempt,
  subtitle,
  badge,
  title,
  className,
  children,
  showTargetHandle = true,
  showSourceHandle = true,
  sourceHandles,
  decisionLayout = false,
}: WorkflowNodeChromeProps) {
  const visual = resolveNodeStatusVisual(status);
  const aria = workflowNodeAriaLabel({
    label,
    visualKind,
    status,
    isRuntimeCurrent,
    primaryAgentId,
    attempt,
  });

  return (
    <div
      className={cn(
        "relative flex h-full w-full flex-col justify-between overflow-hidden rounded-[10px] border bg-[var(--vui-surface-panel)] px-2.5 py-2 shadow-[0_1px_2px_rgba(0,0,0,0.04)] outline-none",
        visual.borderClass,
        visual.toneClass,
        isRuntimeCurrent ? visual.ringClass : "",
        selected ? "outline outline-2 outline-offset-1 outline-[var(--accent-cool,#2563eb)]" : "",
        visualKind === "human_gate" ? "rounded-[12px]" : "",
        visualKind === "decision" ? "rounded-[14px]" : "",
        visualKind === "start" || visualKind === "end" ? "rounded-full px-3" : "",
        className,
      )}
      data-vui="workflow-task-node"
      data-visual-kind={visualKind}
      data-status={status}
      data-current={isRuntimeCurrent ? "true" : "false"}
      data-selected={selected ? "true" : "false"}
      role="button"
      tabIndex={0}
      aria-label={aria}
      title={title}
    >
      {showTargetHandle ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!h-2 !w-2 !border-0 !bg-[var(--fg-tertiary)]"
        />
      ) : null}

      <div className="flex min-w-0 items-start justify-between gap-1.5">
        <div className="flex min-w-0 items-center gap-1.5">
          <KindGlyph kind={visualKind} />
          <div className="min-w-0 truncate text-[13px] font-semibold leading-tight text-[var(--fg-primary)]">
            {label}
          </div>
        </div>
        {badge}
      </div>

      {children ?? (
        <div className="mt-1 flex min-w-0 flex-col gap-0.5">
          {subtitle ? (
            <div className="truncate text-[11px] leading-tight text-[var(--fg-secondary)]">{subtitle}</div>
          ) : null}
          <div className={cn("flex min-w-0 items-center gap-1 text-[11px] font-medium leading-tight", visual.textClass)}>
            <StatusIcon icon={visual.icon} />
            <span className="truncate">{visual.statusLabel}</span>
            {attempt && attempt > 1 ? (
              <span className="shrink-0 text-[var(--fg-tertiary)]">· #{attempt}</span>
            ) : null}
          </div>
        </div>
      )}

      {decisionLayout && sourceHandles?.length ? (
        <div className="pointer-events-none absolute inset-y-0 right-0 flex flex-col justify-evenly py-2">
          {sourceHandles.map((h) => (
            <Handle
              key={h.id}
              id={h.id}
              type="source"
              position={Position.Right}
              className="!relative !right-0 !top-0 !h-2 !w-2 !translate-y-0 !border-0 !bg-[var(--accent-cool,#2563eb)]"
              style={{ position: "relative", transform: "none", right: -4 }}
            />
          ))}
        </div>
      ) : showSourceHandle ? (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-0 !bg-[var(--fg-tertiary)]"
        />
      ) : null}
    </div>
  );
}
