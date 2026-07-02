import { type ReactNode } from "react";

import { TEAM_STAGE_TONE_STYLE, type TeamStageTone } from "./TeamStageCard";

export type TeamStageStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

export type TeamStageCommandBarProps = {
  ariaLabel?: string;
  tone: TeamStageTone;
  title: ReactNode;
  subtitle: ReactNode;
  stats: TeamStageStat[];
};

const BAR_BASE =
  "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-2.5 py-2 rounded-[var(--vui-radius-soft)] border " +
  "border-[color:var(--source-step-border,color-mix(in_srgb,var(--accent-success)_24%,var(--border-soft)))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-panel)] shadow-[var(--vui-elevation-1-sheen)]";

const TITLE_STRONG =
  "text-[0.82rem] text-[var(--fg-primary)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const TITLE_SUB =
  "text-[0.64rem] font-[720] text-[var(--fg-muted)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

// Compact right-packed stat chips (label + value close together) instead of a
// stretched auto-fit grid that spread the pills across the whole bar.
const STATS_GRID = "flex flex-wrap items-center justify-end gap-1.5 min-w-0";
const STAT_PILL =
  "inline-flex min-h-[26px] items-center gap-1.5 px-2 rounded-[7px] whitespace-nowrap " +
  "border border-[color:color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color:var(--source-workbench-card)] " +
  "text-[0.64rem] font-[720] text-[var(--fg-muted)]";
const STAT_VALUE = "flex-none text-[0.78rem] font-[820] text-[var(--fg-primary)]";

/**
 * Faithful reproduction of `.sourceCollectionCommandBar` + `.sourceCollectionCommandStats`:
 * a two-column command bar (title block + auto-fit stat pills) whose border is
 * driven by the current console stage tone.
 */
export function TeamStageCommandBar({
  ariaLabel,
  tone,
  title,
  subtitle,
  stats,
}: TeamStageCommandBarProps) {
  return (
    <section
      data-vui-product="team-stage-command-bar"
      data-tone={tone}
      aria-label={ariaLabel}
      className={BAR_BASE}
      style={TEAM_STAGE_TONE_STYLE[tone]}
    >
      <div className="grid gap-0.5 min-w-0 flex-1 basis-[240px]">
        <strong className={TITLE_STRONG}>{title}</strong>
        <span className={TITLE_SUB}>{subtitle}</span>
      </div>
      <div className={STATS_GRID}>
        {stats.map((stat) => (
          <span key={stat.key} className={STAT_PILL}>
            {stat.label} <strong className={STAT_VALUE}>{stat.value}</strong>
          </span>
        ))}
      </div>
    </section>
  );
}
