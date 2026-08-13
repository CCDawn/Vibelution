import type { NodeProps } from "@xyflow/react";

import { cn } from "../../../lib/cn";

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
        "h-full w-full border bg-[color-mix(in_srgb,var(--vui-surface-region)_84%,transparent)]",
        spacious
          ? "rounded-[26px] shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_12px_36px_rgba(15,23,42,0.04)]"
          : "rounded-2xl",
        tone === "active"
          ? "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))]"
          : tone === "attention"
            ? "border-[color-mix(in_srgb,var(--state-warning)_32%,var(--vui-border-subtle))]"
            : tone === "done"
              ? "border-[var(--vui-border-subtle)] opacity-95"
              : "border-[var(--vui-border-subtle)]",
      )}
      data-vui="workflow-stage-region"
      data-stage-tone={tone}
      data-layout-mode={spacious ? "serpentine" : "stage-columns"}
    >
      <div className={cn("flex items-center gap-2", spacious ? "px-4 pt-4 pb-1" : "px-3.5 pt-3 pb-1")}>
        <span
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded-full border px-1.5 text-[10px] font-semibold tabular-nums",
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
          <div className="ml-auto flex items-center gap-2 text-[10px] tabular-nums text-[var(--fg-tertiary)]">
            <span>{completedCount} / {taskCount}</span>
            <span className="h-1 w-16 overflow-hidden rounded-full bg-[var(--vui-border-subtle)]">
              <span
                className="block h-full rounded-full bg-[var(--accent-cool)] transition-[width]"
                style={{ width: `${Math.min(100, (completedCount / taskCount) * 100)}%` }}
              />
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
