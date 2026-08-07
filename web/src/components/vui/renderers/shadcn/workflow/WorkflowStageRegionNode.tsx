import type { NodeProps } from "@xyflow/react";

import { cn } from "../../../lib/cn";

export function WorkflowStageRegionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const index = Number(props.data.stageIndex ?? 0) + 1;
  const tone = String(props.data.stageTone ?? "idle");

  return (
    <div
      className={cn(
        "h-full w-full rounded-2xl border bg-[color-mix(in_srgb,var(--vui-surface-region)_88%,transparent)]",
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
    >
      <div className="flex items-center gap-2 px-3.5 pt-3 pb-1">
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
      </div>
    </div>
  );
}
