import type { NodeProps } from "@xyflow/react";

import { cn } from "../../../lib/cn";

/** Mix into workspace, not region/rail: light rail === panel white, and dark row sits above panel. */
const STAGE_FILL: Record<string, string> = {
  active: "bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-workspace))]",
  attention: "bg-[color-mix(in_srgb,var(--state-warning)_10%,var(--vui-surface-workspace))]",
  done: "bg-[color-mix(in_srgb,var(--accent-cool)_4%,var(--vui-surface-workspace))]",
};

const STAGE_FILL_IDLE = "bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-workspace))]";

const STAGE_BORDER: Record<string, string> = {
  active: "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))]",
  attention: "border-[color-mix(in_srgb,var(--state-warning)_32%,var(--vui-border-subtle))]",
  done: "border-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-border-subtle))] opacity-95",
};

const STAGE_BORDER_IDLE = "border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))]";

export function WorkflowStageRegionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const index = Number(props.data.stageIndex ?? 0) + 1;
  const tone = String(props.data.stageTone ?? "idle");
  const taskCount = Number(props.data.taskCount ?? 0);
  const completedCount = Number(props.data.completedCount ?? 0);
  const spacious = props.data.layoutMode === "serpentine";

  return (
    <div
      className={cn(
        "h-full w-full border",
        spacious ? "rounded-2xl border-t-2" : "rounded-2xl",
        STAGE_FILL[tone] ?? STAGE_FILL_IDLE,
        STAGE_BORDER[tone] ?? STAGE_BORDER_IDLE,
      )}
      data-vui="workflow-stage-region"
      data-stage-tone={tone}
      data-layout-mode={spacious ? "serpentine" : "stage-columns"}
    >
      <div className={cn("flex items-center gap-2", spacious ? "px-4 pt-3 pb-1" : "px-3.5 pt-3 pb-1")}>
        <span
          className={cn(
            "inline-flex items-center justify-center border font-semibold tabular-nums",
            spacious ? "size-[30px] rounded-lg bg-[var(--vui-surface-panel)] px-1.5 text-[9px] shadow-[0_2px_7px_rgba(15,23,42,0.05)]" : "h-5 min-w-5 rounded-full px-1.5 text-[10px]",
            tone === "active"
              ? "border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--vui-border-subtle))] text-[var(--accent-cool)]"
              : "border-[var(--vui-border-subtle)] text-[var(--fg-tertiary)]",
          )}
        >
          {index}
        </span>
        <div className="truncate text-[12px] font-semibold tracking-wide text-[var(--fg-secondary)]">
          {label}
        </div>
        {spacious && taskCount > 0 ? (
          <div className="ml-auto flex items-center gap-2 text-[9px] tabular-nums text-[var(--fg-tertiary)]">
            <span className="h-1 w-[76px] overflow-hidden rounded-full bg-[var(--vui-border-subtle)]">
              <span
                className="block h-full rounded-full bg-[var(--accent-cool)] transition-[width]"
                style={{ width: `${Math.min(100, (completedCount / taskCount) * 100)}%` }}
              />
            </span>
            <span><strong className="font-semibold text-[var(--fg-secondary)]">{completedCount} / {taskCount}</strong></span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
