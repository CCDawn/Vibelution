import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

import { VTooltip } from "../../primitives/VTooltip";

export type TeamStageTone = "active" | "done" | "failed" | "idle" | "pending";

/** Stage state drives the border/text custom properties used by the card. */
export const TEAM_STAGE_TONE_STYLE: Record<TeamStageTone, CSSProperties> = {
  active: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--fg-primary) 34%, var(--border-strong))",
    ["--source-step-fg" as string]: "var(--fg-primary)",
  },
  done: {
    ["--source-step-border" as string]: "var(--border-soft)",
    ["--source-step-fg" as string]: "var(--fg-secondary)",
  },
  failed: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--accent-danger) 58%, var(--border-strong))",
    ["--source-step-fg" as string]:
      "color-mix(in srgb, var(--accent-danger) 78%, var(--fg-primary))",
  },
  pending: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--accent-warm) 42%, var(--border-soft))",
    ["--source-step-fg" as string]:
      "color-mix(in srgb, var(--accent-warm) 74%, var(--fg-primary))",
  },
  idle: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--fg-muted) 18%, var(--border-soft))",
    ["--source-step-fg" as string]: "var(--fg-muted)",
  },
};

const CARD_BASE =
  "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center content-center gap-3 overflow-hidden rounded-[var(--vui-radius-soft)] border p-2.5 text-left text-[0.72rem] font-[740] cursor-pointer " +
  "border-[color:var(--source-step-border,var(--border-soft))] text-[color:var(--source-step-fg,var(--fg-muted))] " +
  "bg-[color:var(--source-workbench-card)] shadow-[var(--vui-elevation-1)] " +
  "transition-[border-color,box-shadow,background-color] duration-150 ease-[var(--vui-ease)] " +
  "hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:shadow-[var(--vui-elevation-2)] " +
  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus),var(--vui-elevation-2)] focus-visible:border-[var(--border-strong)]";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--fg-primary)_34%,var(--border-strong))] bg-[color:color-mix(in_srgb,var(--fg-primary)_3%,var(--source-workbench-card))] shadow-[inset_2px_0_0_color-mix(in_srgb,var(--fg-primary)_72%,transparent),var(--vui-elevation-2)]";

const HEADER = "flex min-w-0 items-center gap-2";
const STEP_INDEX =
  "flex h-[22px] min-w-[26px] items-center justify-center rounded-[6px] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[0.62rem] font-[820] text-[var(--fg-secondary)]";
const STATUS_BADGE =
  "max-w-[58%] text-[0.64rem] font-[720] text-[color:var(--source-step-fg,var(--fg-muted))]";
const BODY = "flex min-w-0 items-center";
const ACTION_BUTTON =
  "[&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]]:min-h-[28px] [&_[data-vui=native-button]]:px-2.5 [&_[data-vui=native-button]]:text-[0.66rem] [&_[data-vui=native-button]]:font-[840] [&_[data-vui=native-button]]:whitespace-nowrap";
const ACTION_ROW =
  `flex flex-none items-center justify-end gap-1.5 ${ACTION_BUTTON}`;
const TEXT_TRUNCATE = "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";

export type TeamStageCardProps = {
  index: number;
  status: ReactNode;
  label: ReactNode;
  metric: ReactNode;
  nextLabel: ReactNode;
  tone: TeamStageTone;
  selected?: boolean;
  title?: string;
  onActivate: () => void;
  actions?: ReactNode;
};

/** Guard so clicks/keys on inner buttons or links don't trigger card activation. */
function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("button, a"));
}

export function TeamStageCard({
  index,
  status,
  label,
  metric,
  nextLabel,
  tone,
  selected = false,
  title,
  onActivate,
  actions,
}: TeamStageCardProps) {
  const handleClick = (event: ReactMouseEvent<HTMLElement>) => {
    if (isInteractiveTarget(event.target)) {
      return;
    }
    onActivate();
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (isInteractiveTarget(event.target)) {
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    onActivate();
  };

  const details = (
    <div className="grid gap-1">
      <strong>{label}</strong>
      <span>{status}</span>
      <span>{metric}</span>
      <span>{nextLabel}</span>
      {title ? <span>{title}</span> : null}
    </div>
  );
  const card = (
    <article
      data-vui-product="team-stage-card"
      data-tone={tone}
      className={[CARD_BASE, selected ? CARD_SELECTED : ""].filter(Boolean).join(" ")}
      style={TEAM_STAGE_TONE_STYLE[tone]}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <div className={BODY}>
        <div className={HEADER}>
          <strong className={STEP_INDEX}>
            {String(index + 1).padStart(2, "0")}
          </strong>
          <b className={`text-[0.86rem] text-[var(--fg-primary)] ${TEXT_TRUNCATE}`}>{label}</b>
          <span
            data-slot="stage-status"
            className={`${STATUS_BADGE} ${TEXT_TRUNCATE}`}
          >
            {status}
          </span>
        </div>
      </div>
      {actions ? <div className={ACTION_ROW}>{actions}</div> : null}
    </article>
  );

  return <VTooltip content={details} width="wide">{card}</VTooltip>;
}
