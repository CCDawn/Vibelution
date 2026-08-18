import type { NodeProps } from "@xyflow/react";
import { Check, CircleAlert, Loader2 } from "lucide-react";

import { cn } from "../../../lib/cn";

const STAGE_TONE_META = {
  active: {
    chip: "border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool)]",
    indexBadge:
      "border-[color-mix(in_srgb,var(--accent-cool)_52%,var(--vui-border-subtle))] bg-[var(--accent-cool)] text-[var(--vui-surface-panel)]",
    progress: "bg-[var(--accent-cool)]",
    label: "进行中",
    Icon: Loader2,
  },
  attention: {
    chip: "border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]",
    indexBadge:
      "border-[color-mix(in_srgb,var(--state-warning)_52%,var(--vui-border-subtle))] bg-[var(--state-warning)] text-[var(--vui-surface-panel)]",
    progress: "bg-[var(--state-warning)]",
    label: "需关注",
    Icon: CircleAlert,
  },
  done: {
    chip: "border-[color-mix(in_srgb,var(--state-success)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--state-success)]",
    indexBadge:
      "border-[color-mix(in_srgb,var(--state-success)_52%,var(--vui-border-subtle))] bg-[var(--state-success)] text-[var(--vui-surface-panel)]",
    progress: "bg-[var(--state-success)]",
    label: "已完成",
    Icon: Check,
  },
  idle: {
    chip: "",
    indexBadge: "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] text-[var(--fg-tertiary)]",
    progress: "bg-[var(--accent-cool)]",
    label: "",
    Icon: null,
  },
} as const;

type StageTone = keyof typeof STAGE_TONE_META;

function asStageTone(value: string): StageTone {
  return value === "active" || value === "attention" || value === "done" ? value : "idle";
}

export function WorkflowStageRegionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const index = Number(props.data.stageIndex ?? 0) + 1;
  const tone = asStageTone(String(props.data.stageTone ?? "idle"));
  const taskCount = Number(props.data.taskCount ?? 0);
  const completedCount = Number(props.data.completedCount ?? 0);
  const spacious = props.data.layoutMode === "serpentine";
  const meta = STAGE_TONE_META[tone];

  return (
    <div
      className={cn(
        "h-full w-full border bg-[color-mix(in_srgb,var(--vui-surface-region)_84%,transparent)]",
        spacious
          ? "rounded-2xl border-t-2 bg-[linear-gradient(90deg,color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-region)),color-mix(in_srgb,var(--vui-surface-region)_72%,transparent)_24%,color-mix(in_srgb,var(--vui-surface-region)_55%,transparent))] shadow-[inset_0_1px_0_rgba(255,255,255,0.72)]"
          : "rounded-2xl",
        tone === "active"
          ? "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--accent-cool)_14%,transparent)]"
          : tone === "attention"
            ? "border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))]"
            : tone === "done"
              ? "border-[color-mix(in_srgb,var(--state-success)_30%,var(--vui-border-subtle))]"
              : "border-[var(--vui-border-subtle)]",
      )}
      data-vui="workflow-stage-region"
      data-stage-tone={tone}
      data-layout-mode={spacious ? "serpentine" : "stage-columns"}
    >
      <div className={cn("flex items-center gap-2", spacious ? "px-4 pt-3 pb-1" : "px-3.5 pt-3 pb-1")}>
        <span
          className={cn(
            "inline-flex items-center justify-center border font-semibold tabular-nums",
            spacious ? "size-[30px] rounded-lg px-1.5 text-[9px] shadow-[0_2px_7px_rgba(15,23,42,0.05)]" : "h-5 min-w-5 rounded-full px-1.5 text-[10px]",
            meta.indexBadge,
          )}
        >
          {index}
        </span>
        <div className="truncate text-[12px] font-semibold tracking-wide text-[var(--fg-secondary)]">
          {label}
        </div>
        {meta.Icon ? (
          <span
            className={cn(
              "inline-flex h-5 shrink-0 items-center gap-1 rounded-md border px-1.5 text-[9px] font-semibold",
              meta.chip,
            )}
            data-stage-tone-chip={tone}
          >
            <meta.Icon
              className={cn("h-3 w-3", tone === "active" ? "animate-spin [animation-duration:2.4s]" : "")}
              aria-hidden
            />
            {meta.label}
          </span>
        ) : null}
        {spacious && taskCount > 0 ? (
          <div className="ml-auto flex items-center gap-2 text-[9px] tabular-nums text-[var(--fg-tertiary)]">
            <span className="h-1.5 w-[96px] overflow-hidden rounded-full bg-[var(--vui-border-subtle)]">
              <span
                className={cn("block h-full rounded-full transition-[width]", meta.progress)}
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
