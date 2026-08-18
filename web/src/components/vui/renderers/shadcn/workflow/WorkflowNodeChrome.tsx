/**
 * Shared chrome for workflow task nodes (status icon, selection, runtime current).
 */
import type { ReactNode } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  AlertTriangle,
  Ban,
  Bot,
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
  primaryRoleKey?: string;
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
  layoutMode?: "stage-columns" | "serpentine";
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
  const cls = "h-4 w-4 shrink-0";
  if (kind === "agent_task") return <Bot className={cls} aria-hidden />;
  if (kind === "human_gate") return <UserCheck className={cls} aria-hidden />;
  if (kind === "decision") return <GitBranch className={cls} aria-hidden />;
  if (kind === "system_task" || kind === "end") return <Package className={cls} aria-hidden />;
  if (kind === "start") return <Play className={cls} aria-hidden />;
  return null;
}

const ROLE_LABELS: Record<string, string> = {
  source_finder: "资料搜集",
  source_extractor: "证据提炼",
  source_relation_mapper: "证据关系",
  source_ingestor: "知识入库",
  research_owner: "科研负责人",
  experiment_planner: "实验规划",
  experiment_ledger: "实验台账",
  formal_runner: "受控执行",
  iteration_planner: "迭代规划",
  iteration_versioning: "版本治理",
  package_builder: "成果治理",
};

function roleLabel(roleKey: string | undefined): string {
  if (!roleKey) return "角色待确认";
  return ROLE_LABELS[roleKey] ?? roleKey.replaceAll("_", " ");
}

function actorLabel(kind: WorkflowNodeVisualKind): string {
  if (kind === "human_gate") return "人工";
  if (kind === "system_task") return "系统";
  if (kind === "decision") return "决策";
  if (kind === "start") return "起点";
  if (kind === "end") return "终点";
  return "Agent";
}

export function WorkflowNodeChrome({
  label,
  visualKind,
  status,
  selected = false,
  isRuntimeCurrent = false,
  primaryAgentId,
  primaryRoleKey,
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
  layoutMode = "stage-columns",
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
  const spacious = layoutMode === "serpentine";
  const compactMeta = attempt && attempt > 1
    ? `第 ${attempt} 次`
    : isRuntimeCurrent
      ? "当前节点"
      : primaryAgentId
        ? "Agent 已绑定"
        : visualKind === "human_gate"
          ? "人工确认"
          : visualKind === "system_task"
            ? "系统执行"
            : "待运行";

  return (
    <div
      className={cn(
        "relative flex h-full w-full flex-col justify-between overflow-hidden border outline-none transition duration-150",
        spacious
          ? "rounded-[11px] bg-[var(--vui-surface-panel)] px-3 py-2.5 shadow-[var(--vui-elevation-1)] hover:-translate-y-px hover:shadow-[var(--vui-elevation-2)]"
          : "rounded-[10px] bg-[var(--vui-surface-panel)] px-2.5 py-2 shadow-[var(--vui-elevation-1)]",
        visual.borderClass,
        spacious ? "text-[var(--fg-primary)]" : visual.toneClass,
        isRuntimeCurrent ? visual.ringClass : "",
        selected ? "outline outline-2 outline-offset-2 outline-[var(--accent-cool,#2563eb)]" : "",
        visualKind === "human_gate" || visualKind === "decision" ? "rounded-[11px]" : "",
        !spacious && (visualKind === "start" || visualKind === "end") ? "rounded-full px-3" : "",
        className,
      )}
      data-vui="workflow-task-node"
      data-visual-kind={visualKind}
      data-status={status}
      data-current={isRuntimeCurrent ? "true" : "false"}
      data-selected={selected ? "true" : "false"}
      data-layout-mode={layoutMode}
      role="button"
      tabIndex={0}
      aria-label={aria}
      title={title}
    >
      {spacious ? (
        <span
          className={cn("pointer-events-none absolute inset-x-3 top-0 h-[3px] rounded-b", visual.accentBarClass)}
          aria-hidden
        />
      ) : null}
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
                className="!h-2 !w-2 !border-[1.5px] !border-[var(--vui-border-strong)] !bg-[var(--vui-surface-panel)]"
              />
            );
          })
        ) : (
          <Handle
            type="target"
            position={sideToPosition(targetSide)}
            className="!h-2 !w-2 !border-[1.5px] !border-[var(--vui-border-strong)] !bg-[var(--vui-surface-panel)]"
          />
        )
      ) : null}

      <div className={cn("flex min-w-0 justify-between", spacious ? "items-center gap-2" : "items-start gap-1.5")}>
        <div className={cn("flex min-w-0 items-center", spacious ? "gap-2.5" : "gap-1.5")}>
          {spacious ? (
            <span className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))] text-[var(--accent-cool)]">
              <KindGlyph kind={visualKind} />
            </span>
          ) : (
            <KindGlyph kind={visualKind} />
          )}
          <div className={cn(
            "min-w-0 font-semibold text-[var(--fg-primary)]",
            spacious ? "truncate text-[13px] leading-[1.2]" : "truncate text-[13px] leading-tight",
          )}>
            {label}
          </div>
        </div>
        {spacious ? (
          <span className={cn(
            "inline-flex h-5 shrink-0 items-center rounded-md border px-1.5 text-[8px] font-semibold",
            visualKind === "human_gate"
              ? "border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_7%,transparent)] text-[var(--state-warning)]"
              : "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]",
          )}>
            {actorLabel(visualKind)}
          </span>
        ) : badge}
      </div>

      {spacious ? (
        <>
          <div className="mt-2 flex min-w-0 items-center gap-1.5 leading-none">
            <span
              className={cn(
                "inline-flex h-5 shrink-0 items-center gap-1 rounded-md border px-1.5 text-[10px] font-semibold",
                visual.badgeClass,
              )}
              data-status-badge={status}
            >
              <StatusIcon icon={visual.icon} />
              {visual.statusLabel}
            </span>
            <span className="truncate text-[9px] font-medium text-[var(--fg-tertiary)]">{compactMeta}</span>
          </div>
          <div className="mt-auto grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-2 border-t border-[var(--vui-border-subtle)] pt-1.5 text-[8.5px] leading-none text-[var(--fg-tertiary)]">
            <span className="truncate font-medium text-[var(--fg-secondary)]">{roleLabel(primaryRoleKey)}</span>
            <span className="max-w-24 truncate text-right">{primaryAgentId ? "已绑定" : actorLabel(visualKind)}</span>
          </div>
        </>
      ) : children ?? (
        <div className={cn("flex min-w-0 flex-col", spacious ? "mt-2 gap-1.5" : "mt-1 gap-0.5")}>
          {subtitle ? (
            <div className={cn("text-[11px] text-[var(--fg-secondary)]", spacious ? "line-clamp-2 leading-4" : "truncate leading-tight")}>{subtitle}</div>
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
                    className="!h-2 !w-2 !border-[1.5px] !border-[var(--accent-cool,#2563eb)] !bg-[var(--vui-surface-panel)]"
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
          className="!h-2 !w-2 !border-[1.5px] !border-[var(--vui-border-strong)] !bg-[var(--vui-surface-panel)]"
        />
      ) : null}
    </div>
  );
}
