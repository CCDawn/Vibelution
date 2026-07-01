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
  "grid grid-cols-[minmax(260px,0.55fr)_minmax(0,1.45fr)] items-center gap-2 px-2.5 py-2 rounded-lg border " +
  "border-[color:var(--source-step-border,color-mix(in_srgb,var(--accent-success)_24%,var(--border-soft)))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-panel)] " +
  "max-[760px]:grid-cols-[1fr]";

const TITLE_STRONG =
  "text-[0.82rem] text-[var(--fg-primary)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const TITLE_SUB =
  "text-[0.64rem] font-[720] text-[var(--fg-muted)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const STATS_GRID = "grid grid-cols-[repeat(auto-fit,minmax(96px,1fr))] gap-[5px] min-w-0";
const STAT_PILL =
  "flex min-w-0 min-h-[26px] items-center justify-between gap-1.5 px-[7px] rounded-[7px] " +
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
      <div className="grid gap-0.5 min-w-0">
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
