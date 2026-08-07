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
import type {
  WorkflowNodeRunStatus,
  WorkflowNodeVisualKind,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
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
  /** ELK port sides keyed by handle id; drives Handle placement (P1-4). */
  portSides?: {
    source: Record<string, WorkflowPortSide>;
    target: Record<string, WorkflowPortSide>;
  };
};

function sideToPosition(side: WorkflowPortSide): Position {
  switch (side) {
    case "WEST":
      return Position.Left;
    case "EAST":
      return Position.Right;
    case "NORTH":
      return Position.Top;
    case "SOUTH":
      return Position.Bottom;
  }
}

function firstSideOf(map: Record<string, WorkflowPortSide> | undefined): WorkflowPortSide | null {
  if (!map) {
    return null;
  }
  const first = Object.values(map)[0];
  return first ?? null;
}

/**
 * Distributes N handles along the axis perpendicular to their side so same-side
 * handles never stack on the node midpoint (P1-4). Left/right handles spread
 * vertically; top/bottom handles spread horizontally.
 */
function sideOffset(index: number, total: number, side: WorkflowPortSide): Record<string, number> {
  if (total <= 1) {
    return {};
  }
  const t = total > 1 ? index / (total - 1) : 0.5;
  const percent = 12 + t * 76; // keep inside the node's visible band
  return side === "WEST" || side === "EAST" ? { top: percent } : { left: percent };
}

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
  portSides,
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

  const targetSide = firstSideOf(portSides?.target) ?? "WEST";
  const singleSourceSide = firstSideOf(portSides?.source) ?? "EAST";
  const sideOfSourceHandle = (id: string): WorkflowPortSide =>
    portSides?.source[id] ?? "EAST";
  const sideOfTargetHandle = (id: string): WorkflowPortSide =>
    portSides?.target[id] ?? targetSide;
  // Real ELK target ports, keyed by short name (e.g. "feedback:in"); the
  // renderer mirrors every one so multi-entry nodes keep edge endpoints
  // visually aligned with the engine (P1-4).
  const targetHandleIds = portSides?.target ? Object.keys(portSides.target) : [];

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
        targetHandleIds.length > 0 ? (
          targetHandleIds.map((id, index) => {
            const side = sideOfTargetHandle(id);
            return (
              <Handle
                key={id}
                id={id}
                type="target"
                position={sideToPosition(side)}
                style={sideOffset(index, targetHandleIds.length, side)}
                className="!h-2 !w-2 !border-0 !bg-[var(--fg-tertiary)]"
              />
            );
          })
        ) : (
          <Handle
            type="target"
            position={sideToPosition(targetSide)}
            className="!h-2 !w-2 !border-0 !bg-[var(--fg-tertiary)]"
          />
        )
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
        <>
          {(["WEST", "EAST", "NORTH", "SOUTH"] as const).map((side) => {
            const handles = sourceHandles.filter((h) => sideOfSourceHandle(h.id) === side);
            if (handles.length === 0) {
              return null;
            }
            const vertical = side === "WEST" || side === "EAST";
            return (
              <div
                key={side}
                className="pointer-events-none absolute flex justify-evenly"
                style={
                  vertical
                    ? { top: 0, bottom: 0, [side === "WEST" ? "left" : "right"]: 0, flexDirection: "column", paddingBlock: 12 }
                    : { left: 0, right: 0, [side === "NORTH" ? "top" : "bottom"]: 0, flexDirection: "row", paddingInline: 12 }
                }
              >
                {handles.map((h, index) => (
                  <Handle
                    key={h.id}
                    id={h.id}
                    type="source"
                    position={sideToPosition(side)}
                    style={sideOffset(index, handles.length, side)}
                    className="!h-2 !w-2 !border-0 !bg-[var(--accent-cool,#2563eb)]"
                  />
                ))}
              </div>
            );
          })}
        </>
      ) : decisionLayout ? null : showSourceHandle ? (
        <Handle
          type="source"
          position={sideToPosition(singleSourceSide)}
          className="!h-2 !w-2 !border-0 !bg-[var(--fg-tertiary)]"
        />
      ) : null}
    </div>
  );
}
