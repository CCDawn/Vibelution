/**
 * Shared chrome for workflow task nodes (status icon, selection, runtime current).
 */
import type { CSSProperties, ReactNode } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  AlertTriangle,
  Ban,
  Bot,
  Check,
  Circle,
  GitBranch,
  Loader2,
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
  WorkflowPortSides,
} from "../../../product/workflow/workflowCanvasTypes";
import { resolveNodeStatusVisual } from "./workflowCanvasState";
import { workflowNodeAriaLabel } from "./workflowCanvasAccessibility";
import {
  WORKFLOW_PORT_SIDES,
  workflowSnapHandleId,
  workflowSnapSlotsForPortSide,
  type WorkflowReconnectMagnets,
} from "./workflowEdgeAnchors";

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
  portSides?: WorkflowPortSides;
  layoutMode?: "stage-columns" | "serpentine";
  /** Temporary magnets while reconnecting an existing edge on this card. */
  reconnectMagnets?: WorkflowReconnectMagnets;
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

function handleFraction(
  anchors: Record<string, number> | undefined,
  handleId: string,
  index: number,
  total: number,
): number {
  const value = anchors?.[handleId];
  return typeof value === "number" ? value : workflowHandleFallbackFraction(index, total);
}

/**
 * Places a handle at a 0–1 magnet along its side. Left/right use `top`;
 * top/bottom use `left`. React Flow still owns the edge of the card.
 */
export function workflowHandleSnapStyle(side: WorkflowPortSide, fraction: number): CSSProperties {
  const along = `${Number((fraction * 100).toFixed(4))}%`;
  return side === "WEST" || side === "EAST" ? { top: along } : { left: along };
}

export function workflowHandleFallbackFraction(index: number, total: number): number {
  if (total <= 1) return 0.5;
  return (index + 1) / (total + 1);
}

/**
 * Distributes N handles along the side when layout did not pick magnets.
 * Uses relative 1/(n+1) slots instead of a 16px cluster around center.
 */
export function workflowHandleSideOffset(index: number, total: number, side: WorkflowPortSide): CSSProperties {
  return workflowHandleSnapStyle(side, workflowHandleFallbackFraction(index, total));
}

function StatusIcon({
  icon,
  className = "h-3.5 w-3.5 shrink-0",
}: {
  icon: ReturnType<typeof resolveNodeStatusVisual>["icon"];
  className?: string;
}) {
  const cls = className;
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

function KindGlyph({
  kind,
  className = "h-4 w-4 shrink-0",
}: {
  kind: WorkflowNodeVisualKind;
  className?: string;
}) {
  const cls = className;
  if (kind === "agent_task") return <Bot className={cls} aria-hidden />;
  if (kind === "human_gate") return <UserCheck className={cls} aria-hidden />;
  if (kind === "decision") return <GitBranch className={cls} aria-hidden />;
  if (kind === "system_task" || kind === "end") return <Package className={cls} aria-hidden />;
  if (kind === "start") return <Play className={cls} aria-hidden />;
  return null;
}

const ROLE_LABELS: Record<string, string> = {
  challenge_cup_coordinator: "科研协调",
  challenge_cup_search: "搜索",
  challenge_cup_extractor: "提炼",
  challenge_cup_knowledge_manager: "知识管理",
  challenge_cup_execution_steward: "执行",
  challenge_cup_experiment_revision: "实验修订",
  challenge_cup_evaluator: "评估",
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

function kindFillClass(kind: WorkflowNodeVisualKind): string {
  if (kind === "human_gate") return "bg-[var(--state-warning)]";
  if (kind === "decision") return "bg-[var(--accent-warm)]";
  if (kind === "system_task" || kind === "end") return "bg-[var(--fg-primary)]";
  if (kind === "start") return "bg-[var(--fg-secondary)]";
  return "bg-[var(--accent-cool)]";
}

function humanGateFallbackSubtitle(role: string, status: WorkflowNodeRunStatus | undefined): string {
  if (status === "waiting_human") return `${role} · 等待确认`;
  if (status === "succeeded") return `${role} · 已确认`;
  if (status === "failed") return `${role} · 未通过`;
  if (status === "blocked") return `${role} · 受阻`;
  if (status === "running") return `${role} · 审查中`;
  return `${role} · 人工审查`;
}

function moduleSubtitle(
  kind: WorkflowNodeVisualKind,
  roleKey: string | undefined,
  agentId: string | undefined,
  status?: WorkflowNodeRunStatus,
): string {
  if (kind === "decision") return "晋升 / 回滚 / 停止";
  if (kind === "system_task") return "受控执行";
  const role = roleLabel(roleKey);
  if (kind === "human_gate") return humanGateFallbackSubtitle(role, status);
  if (kind === "start") return `${role} · 流程入口`;
  if (kind === "end") return `${role} · 流程出口`;
  if (agentId) return `${role} · Agent 已绑定`;
  return `${role} · 未绑定`;
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
  reconnectMagnets,
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
  const sourceHandleIds = portSides?.source
    ? Object.keys(portSides.source)
    : (sourceHandles?.map((handle) => handle.id) ?? []);
  const spacious = layoutMode === "serpentine";
  const handleClass = spacious
    ? "!h-2.5 !w-2.5 !border-2 !border-[var(--vui-border-strong)] !bg-[var(--vui-surface-panel)]"
    : "!h-2 !w-2 !border-[1.5px] !border-[var(--vui-border-strong)] !bg-[var(--vui-surface-panel)]";

  return (
    <div
      className={cn(
        "relative h-full w-full border outline-none transition duration-150",
        spacious
          ? "flex items-center overflow-visible rounded-2xl bg-[var(--vui-surface-panel)] py-0 pr-4 pl-3 shadow-[var(--vui-elevation-2)] hover:-translate-y-px"
          : "flex flex-col justify-between overflow-hidden rounded-[10px] bg-[var(--vui-surface-panel)] px-2.5 py-2 shadow-[var(--vui-elevation-1)]",
        visual.borderClass,
        spacious ? "text-[var(--fg-primary)]" : visual.toneClass,
        isRuntimeCurrent ? visual.ringClass : "",
        selected ? "outline outline-2 outline-offset-2 outline-[var(--accent-cool,#2563eb)]" : "",
        !spacious && (visualKind === "human_gate" || visualKind === "decision") ? "rounded-[11px]" : "",
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
      aria-current={isRuntimeCurrent ? "step" : undefined}
      title={title}
    >
      {showTargetHandle ? (
        targetHandleIds.length > 0 ? (
          targetHandleIds.map((id) => {
            const side = sideOfTargetHandle(id);
            const sameSideHandles = targetHandleIds.filter((handleId) => sideOfTargetHandle(handleId) === side);
            const fraction = handleFraction(
              portSides?.targetAnchor,
              id,
              sameSideHandles.indexOf(id),
              sameSideHandles.length,
            );
            return (
              <Handle
                key={id}
                id={id}
                type="target"
                position={sideToPosition(side)}
                isConnectable={false}
                style={workflowHandleSnapStyle(side, fraction)}
                className={handleClass}
              />
            );
          })
        ) : (
          <Handle
            type="target"
            position={sideToPosition(targetSide)}
            isConnectable={false}
            className={handleClass}
          />
        )
      ) : null}

      {spacious ? (
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span
            className={cn(
              "relative grid size-11 shrink-0 place-items-center rounded-xl text-[var(--accent-cool-contrast)] shadow-[inset_0_-1px_0_color-mix(in_srgb,var(--fg-primary)_12%,transparent)]",
              kindFillClass(visualKind),
            )}
          >
            <KindGlyph kind={visualKind} className="h-[22px] w-[22px] shrink-0" />
          </span>
          <span className="grid min-w-0 flex-1 gap-0.5 text-left">
            <span className="truncate text-[15px] font-bold leading-[1.2] tracking-[-0.02em] text-[var(--fg-primary)]">
              {label}
            </span>
            <span className="truncate text-[12px] leading-[1.35] text-[var(--fg-secondary)]">
              {visualKind === "human_gate" || (visualKind === "agent_task" && !primaryRoleKey)
                ? (subtitle?.trim() || moduleSubtitle(visualKind, primaryRoleKey, primaryAgentId, status))
                : moduleSubtitle(visualKind, primaryRoleKey, primaryAgentId, status)}
            </span>
          </span>
          <span
            className={cn(
              "inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-[11px] font-semibold leading-none",
              visual.badgeClass,
            )}
            data-status-badge={status}
          >
            {status === "running" ? (
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <StatusIcon icon={visual.icon} className="h-3 w-3 shrink-0" />
            )}
            <span>{visual.statusLabel}</span>
          </span>
        </div>
      ) : (
        <>
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
        </>
      )}

      {sourceHandleIds.length > 0 ? (
        <>
          {(["WEST", "EAST", "NORTH", "SOUTH"] as const).map((side) => {
            const handles = sourceHandleIds.filter((id) => sideOfSourceHandle(id) === side);
            if (handles.length === 0) {
              return null;
            }
            return (
              <div key={side}>
                {handles.map((handleId, index) => (
                  <Handle
                    key={handleId}
                    id={handleId}
                    type="source"
                    position={sideToPosition(side)}
                    isConnectable={false}
                    style={workflowHandleSnapStyle(
                      side,
                      handleFraction(portSides?.sourceAnchor, handleId, index, handles.length),
                    )}
                    className={cn(handleClass, "!border-[var(--accent-cool,#2563eb)]")}
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
          isConnectable={false}
          className={handleClass}
        />
      ) : null}
      {reconnectMagnets ? (
        <>
          {WORKFLOW_PORT_SIDES.flatMap((side) =>
            workflowSnapSlotsForPortSide(side).map((fraction) => (
              <Handle
                key={workflowSnapHandleId(side, fraction)}
                id={workflowSnapHandleId(side, fraction)}
                type={reconnectMagnets.type}
                position={sideToPosition(side)}
                isConnectable
                style={{ ...workflowHandleSnapStyle(side, fraction), zIndex: 5 }}
                className="!h-2.5 !w-2.5 !border-2 !border-[var(--accent-cool)] !bg-[var(--vui-surface-panel)]"
                data-workflow-snap="true"
              />
            )),
          )}
        </>
      ) : null}
    </div>
  );
}
