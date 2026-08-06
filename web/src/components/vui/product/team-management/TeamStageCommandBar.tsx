import { type ReactNode } from "react";

import { VNativeButton } from "../../primitives/VNativeButton";
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
  /** Short status text only; shown in tooltip + optional tiny tag. */
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
  "grid w-full min-w-0 grid-cols-1 gap-2 px-2.5 py-2 rounded-[var(--vui-radius-soft)] border " +
  "border-[color:var(--source-step-border,color-mix(in_srgb,var(--accent-success)_24%,var(--border-soft)))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-panel)] shadow-[var(--vui-elevation-1-sheen)] " +
  "lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center lg:gap-x-3";

const TITLE_STRONG =
  "text-[0.82rem] text-[var(--fg-primary)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const TITLE_SUB =
  "text-[0.64rem] font-[720] text-[var(--fg-muted)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

/** Right column: steps row then stats row — never share one cramped horizontal line. */
const RIGHT_CLUSTER =
  "flex min-w-0 w-full flex-col items-stretch gap-1.5 lg:w-auto lg:max-w-[min(100%,42rem)] lg:items-end";

const STEPS_ROW =
  "flex min-w-0 w-full flex-nowrap items-center justify-end gap-1 overflow-x-auto overscroll-x-contain " +
  "[scrollbar-width:thin]";

const STEP_CHIP =
  "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[0.62rem] font-[720] " +
  "border-[color:color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color:var(--source-workbench-card)] " +
  "text-[var(--fg-muted)] transition-colors";

const STEP_CHIP_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] " +
  "bg-[color:color-mix(in_srgb,var(--accent-cool)_10%,var(--source-workbench-card))] text-[var(--fg-primary)]";

const STEP_CHIP_BUTTON =
  "cursor-pointer hover:border-[color:color-mix(in_srgb,var(--accent-cool)_35%,var(--border-soft))]";

const STEP_INDEX = "tabular-nums font-[820] text-[var(--fg-tertiary)]";
const STEP_TITLE = "whitespace-nowrap font-[760]";
const STEP_STATUS =
  "max-w-[4.5rem] overflow-hidden text-ellipsis whitespace-nowrap text-[0.58rem] opacity-85";

const STATS_GRID = "flex min-w-0 w-full flex-wrap items-center justify-end gap-1.5";
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

function statusTooltip(status: ReactNode): string | undefined {
  if (typeof status === "string" || typeof status === "number") {
    return String(status);
  }
  return undefined;
}

/**
 * Command bar: title left; right column stacks stage steps above summary stats
 * so chips never collide with status pills.
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
      <div className="grid min-w-0 gap-0.5">
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
              const tip = statusTooltip(step.status);
              const body = (
                <>
                  <span className={STEP_INDEX}>{step.indexLabel}</span>
                  <span className={STEP_TITLE}>{step.title}</span>
                  {tip ? (
                    <span className={STEP_STATUS} title={tip}>
                      {tip}
                    </span>
                  ) : null}
                </>
              );
              if (step.onClick) {
                return (
                  <VNativeButton
                    key={step.id}
                    type="button"
                    role="listitem"
                    className={className}
                    style={TEAM_STAGE_TONE_STYLE[step.tone]}
                    onClick={step.onClick}
                    title={tip}
                    data-stage-id={step.id}
                    data-selected={step.selected ? "true" : "false"}
                  >
                    {body}
                  </VNativeButton>
                );
              }
              return (
                <span
                  key={step.id}
                  role="listitem"
                  className={className}
                  style={TEAM_STAGE_TONE_STYLE[step.tone]}
                  title={tip}
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
                <VNativeButton
                  key={stat.key}
                  type="button"
                  className={pillClass}
                  title={stat.title}
                  onClick={stat.onClick}
                >
                  {content}
                </VNativeButton>
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
