import { type ReactNode } from "react";

import { TEAM_STAGE_TONE_STYLE, type TeamStageTone } from "./TeamStageCard";

export type TeamStageStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
  /** Optional click target (e.g. jump to next stage). */
  onClick?: () => void;
  title?: string;
  emphasis?: "default" | "accent" | "danger";
};

/** Compact 01–04 step chips owned by the command bar (single progress surface). */
export type TeamStageCommandStep = {
  id: string;
  indexLabel: ReactNode;
  title: ReactNode;
  tone: TeamStageTone;
  selected?: boolean;
  status?: ReactNode;
  onClick?: () => void;
};

export type TeamStageCommandBarProps = {
  ariaLabel?: string;
  tone: TeamStageTone;
  title: ReactNode;
  subtitle: ReactNode;
  stats: TeamStageStat[];
  /** When set, renders unified stage progress on the right (replaces left-rail pipeline). */
  steps?: TeamStageCommandStep[];
};

const BAR_BASE =
  "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-2.5 py-2 rounded-[var(--vui-radius-soft)] border " +
  "border-[color:var(--source-step-border,color-mix(in_srgb,var(--accent-success)_24%,var(--border-soft)))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-panel)] shadow-[var(--vui-elevation-1-sheen)]";

const TITLE_STRONG =
  "text-[0.82rem] text-[var(--fg-primary)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const TITLE_SUB =
  "text-[0.64rem] font-[720] text-[var(--fg-muted)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const RIGHT_CLUSTER = "flex min-w-0 flex-wrap items-center justify-end gap-2";
const STEPS_ROW = "flex min-w-0 flex-wrap items-center justify-end gap-1";
const STEP_CHIP =
  "inline-flex max-w-[9.5rem] min-h-[26px] items-center gap-1 rounded-[7px] border px-1.5 text-[0.62rem] font-[720] " +
  "border-[color:color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color:var(--source-workbench-card)] " +
  "text-[var(--fg-muted)] transition-colors";
const STEP_CHIP_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] " +
  "bg-[color:color-mix(in_srgb,var(--accent-cool)_10%,var(--source-workbench-card))] text-[var(--fg-primary)]";
const STEP_CHIP_BUTTON = "cursor-pointer hover:border-[color:color-mix(in_srgb,var(--accent-cool)_35%,var(--border-soft))]";
const STEP_INDEX = "tabular-nums font-[820] text-[var(--fg-tertiary)]";
const STEP_TITLE = "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const STATS_GRID = "flex flex-wrap items-center justify-end gap-1.5 min-w-0";
const STAT_PILL =
  "inline-flex min-h-[26px] items-center gap-1.5 px-2 rounded-[7px] whitespace-nowrap " +
  "border border-[color:color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color:var(--source-workbench-card)] " +
  "text-[0.64rem] font-[720] text-[var(--fg-muted)]";
const STAT_PILL_ACCENT =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_40%,var(--border-soft))] " +
  "bg-[color:color-mix(in_srgb,var(--accent-cool)_9%,var(--source-workbench-card))]";
const STAT_PILL_DANGER =
  "border-[color:color-mix(in_srgb,var(--state-danger)_35%,var(--border-soft))] " +
  "bg-[color:color-mix(in_srgb,var(--state-danger)_8%,var(--source-workbench-card))]";
const STAT_PILL_BUTTON = "cursor-pointer hover:brightness-[0.98]";
const STAT_VALUE = "flex-none text-[0.78rem] font-[820] text-[var(--fg-primary)]";

/**
 * Command bar: title left, unified progress (steps + stats) packed to the right.
 */
export function TeamStageCommandBar({
  ariaLabel,
  tone,
  title,
  subtitle,
  stats,
  steps,
}: TeamStageCommandBarProps) {
  return (
    <section
      data-vui-product="team-stage-command-bar"
      data-tone={tone}
      data-progress-placement="command-bar"
      aria-label={ariaLabel}
      className={BAR_BASE}
      style={TEAM_STAGE_TONE_STYLE[tone]}
    >
      <div className="grid min-w-0 flex-1 basis-[200px] gap-0.5">
        <strong className={TITLE_STRONG}>{title}</strong>
        <span className={TITLE_SUB}>{subtitle}</span>
      </div>
      <div className={RIGHT_CLUSTER}>
        {steps && steps.length > 0 ? (
          <div className={STEPS_ROW} role="list" aria-label="stage-progress">
            {steps.map((step) => {
              const className = [
                STEP_CHIP,
                step.selected ? STEP_CHIP_SELECTED : "",
                step.onClick ? STEP_CHIP_BUTTON : "",
              ]
                .filter(Boolean)
                .join(" ");
              const body = (
                <>
                  <span className={STEP_INDEX} style={TEAM_STAGE_TONE_STYLE[step.tone]}>
                    {step.indexLabel}
                  </span>
                  <span className={STEP_TITLE}>{step.title}</span>
                  {step.status ? <span className="shrink-0 opacity-80">{step.status}</span> : null}
                </>
              );
              if (step.onClick) {
                return (
                  <button
                    key={step.id}
                    type="button"
                    role="listitem"
                    className={className}
                    onClick={step.onClick}
                    data-stage-id={step.id}
                    data-selected={step.selected ? "true" : "false"}
                  >
                    {body}
                  </button>
                );
              }
              return (
                <span
                  key={step.id}
                  role="listitem"
                  className={className}
                  data-stage-id={step.id}
                  data-selected={step.selected ? "true" : "false"}
                >
                  {body}
                </span>
              );
            })}
          </div>
        ) : null}
        <div className={STATS_GRID}>
          {stats.map((stat) => {
            const pillClass = [
              STAT_PILL,
              stat.emphasis === "accent" ? STAT_PILL_ACCENT : "",
              stat.emphasis === "danger" ? STAT_PILL_DANGER : "",
              stat.onClick ? STAT_PILL_BUTTON : "",
            ]
              .filter(Boolean)
              .join(" ");
            const content = (
              <>
                {stat.label} <strong className={STAT_VALUE}>{stat.value}</strong>
              </>
            );
            if (stat.onClick) {
              return (
                <button
                  key={stat.key}
                  type="button"
                  className={pillClass}
                  title={stat.title}
                  onClick={stat.onClick}
                >
                  {content}
                </button>
              );
            }
            return (
              <span key={stat.key} className={pillClass} title={stat.title}>
                {content}
              </span>
            );
          })}
        </div>
      </div>
    </section>
  );
}
