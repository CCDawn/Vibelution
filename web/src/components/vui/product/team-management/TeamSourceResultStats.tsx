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

const GRID = "flex min-w-0 flex-wrap items-center gap-1.5";
const PILL =
  "inline-flex min-h-6 w-fit max-w-full items-center gap-1.5 rounded-[var(--radius-control)] " +
  "border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 " +
  "[font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]";
const VALUE = "flex-none text-[var(--fg-primary)]";

/**
 * Compact auto-fit stat pills for source-collection workbench headers.
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
