import { type ReactNode } from "react";

import { VNativeButton } from "../../primitives/VNativeButton";
import { VTooltip } from "../../primitives/VTooltip";
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
  "flex w-full min-w-0 flex-wrap items-center gap-2.5 rounded-[var(--vui-radius-soft)] border px-3 py-2.5 text-left " +
  "border-[color:var(--source-step-border,var(--border-soft))] bg-[color:var(--source-workbench-panel)] shadow-[var(--vui-elevation-1)]";

const TITLE_STRONG =
  "text-[0.82rem] text-[var(--fg-primary)] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

const RIGHT_CLUSTER =
  "flex min-w-0 flex-1 flex-wrap items-center gap-2";

const STEPS_ROW =
  "flex min-w-0 w-fit flex-nowrap items-center gap-0.5 overflow-x-auto overscroll-x-contain rounded-[8px] " +
  "border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0.5 [scrollbar-width:thin]";

const STEP_CHIP =
  "inline-flex shrink-0 items-center gap-1 rounded-[6px] border border-transparent px-1.5 py-1 text-[0.62rem] font-[720] " +
  "bg-transparent text-[var(--fg-tertiary)] transition-[background-color,color,box-shadow] duration-150";

const STEP_CHIP_SELECTED =
  "bg-[var(--source-workbench-card)] text-[var(--fg-primary)] shadow-[var(--vui-elevation-1)]";

const STEP_CHIP_BUTTON =
  "cursor-pointer hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]";

const STEP_INDEX = "tabular-nums font-[820] text-[var(--fg-tertiary)]";
const STEP_TITLE = "whitespace-nowrap font-[760]";

const STATS_GRID = "flex min-w-0 flex-wrap items-center gap-2";
const STAT_PILL =
  "inline-flex min-h-[24px] items-center gap-1 whitespace-nowrap text-[0.64rem] font-[680] text-[var(--fg-tertiary)]";
const STAT_PILL_ACCENT =
  "text-[var(--fg-secondary)]";
const STAT_PILL_DANGER =
  "text-[var(--state-danger)]";
const STAT_PILL_BUTTON =
  "cursor-pointer rounded-[6px] px-1.5 hover:bg-[var(--vui-control-muted-hover)] focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]";
const STAT_VALUE = "flex-none text-[0.78rem] font-[820] text-[var(--fg-primary)]";

function statusTooltip(status: ReactNode): string | undefined {
  if (typeof status === "string" || typeof status === "number") {
    return String(status);
  }
  return undefined;
}

/**
 * Command bar keeps the active stage, progress, and summary in one local group.
 * Only actionable entries receive control chrome.
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
      <VTooltip content={subtitle} width="wide">
        <strong className={TITLE_STRONG}>{title}</strong>
      </VTooltip>
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
