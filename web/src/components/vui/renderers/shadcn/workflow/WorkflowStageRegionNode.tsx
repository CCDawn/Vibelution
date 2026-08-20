import type { NodeProps } from "@xyflow/react";
import { Check, CircleAlert, Loader2 } from "lucide-react";

import { cn } from "../../../lib/cn";

/** Header status indicators aggregate member-node run state (small chips, not band identity). */
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

const STAGE_BORDER_IDLE = "border-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-border-subtle))]";

export function WorkflowStageRegionNode(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const index = Number(props.data.stageIndex ?? 0) + 1;
  const tone = asStageTone(String(props.data.stageTone ?? "idle"));
  const spacious = props.data.layoutMode === "serpentine";
  const meta = STAGE_TONE_META[tone];

  if (spacious) {
    return (
      <div
        aria-hidden="true"
        className="h-full w-full"
        data-layout-mode="serpentine"
        data-stage-tone={tone}
        data-vui="workflow-stage-region"
      />
    );
  }

  return (
    <div
      className={cn(
        "h-full w-full select-none rounded-2xl border",
        (tone === "idle" || tone === "done") ? "border-dashed" : "",
        STAGE_FILL[tone] ?? STAGE_FILL_IDLE,
        STAGE_BORDER[tone] ?? STAGE_BORDER_IDLE,
      )}
      data-vui="workflow-stage-region"
      data-stage-tone={tone}
      data-layout-mode="stage-columns"
    >
      <div className="flex items-center gap-2 px-3.5 pt-3 pb-1">
        <span
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded-full border px-1.5 text-[10px] font-semibold tabular-nums",
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
      </div>
    </div>
  );
}
