import { type ReactNode } from "react";

export type TeamSourceResultStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

export type TeamSourceResultStatsProps = {
  ariaLabel?: string;
  stats: TeamSourceResultStat[];
};

const GRID = "grid grid-cols-[repeat(auto-fit,minmax(92px,1fr))] gap-[5px] min-w-0";
const PILL =
  "flex min-w-0 min-h-[24px] items-center justify-between gap-1.5 px-[7px] rounded-[7px] " +
  "border border-[color:color-mix(in_srgb,var(--accent-success)_22%,var(--border-soft))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-card)] " +
  "text-[0.62rem] font-[760] text-[var(--fg-muted)]";
const VALUE = "flex-none text-[0.74rem] text-[var(--fg-primary)]";

/**
 * Faithful reproduction of `.sourceCollectionResultStats`: an auto-fit row of
 * compact stat pills (min 92px) with a subtle success-tinted border.
 */
export function TeamSourceResultStats({ ariaLabel, stats }: TeamSourceResultStatsProps) {
  return (
    <div data-vui-product="team-source-result-stats" className={GRID} aria-label={ariaLabel}>
      {stats.map((stat) => (
        <span key={stat.key} className={PILL}>
          {stat.label} <strong className={VALUE}>{stat.value}</strong>
        </span>
      ))}
    </div>
  );
}
