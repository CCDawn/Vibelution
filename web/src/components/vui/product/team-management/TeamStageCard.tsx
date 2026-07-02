import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

export type TeamStageTone = "active" | "done" | "failed" | "idle" | "pending";

/** Stage state drives the border/text custom properties used by the card. */
export const TEAM_STAGE_TONE_STYLE: Record<TeamStageTone, CSSProperties> = {
  active: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--accent-cool) 58%, var(--border-strong))",
    ["--source-step-fg" as string]:
      "color-mix(in srgb, var(--accent-cool) 78%, var(--fg-primary))",
    boxShadow: "var(--vui-shadow-inset-accent)",
  },
  done: {
    ["--source-step-border" as string]:
      "color-mix(in srgb, var(--accent-success) 50%, var(--border-soft))",
    ["--source-step-fg" as string]:
      "color-mix(in srgb, var(--accent-success) 76%, var(--fg-primary))",
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
  "grid grid-cols-[minmax(0,1fr)_auto] items-center content-center min-w-0 gap-3 p-2.5 rounded-[var(--vui-radius-soft)] border cursor-pointer overflow-hidden text-[0.72rem] font-[740] " +
  "border-[color:var(--source-step-border,var(--border-soft))] text-[color:var(--source-step-fg,var(--fg-muted))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-card)] shadow-[var(--vui-elevation-1-sheen)] " +
  "transition-[transform,border-color,box-shadow] duration-150 ease-[var(--vui-ease)] will-change-transform " +
  "hover:-translate-y-px hover:border-[color:color-mix(in_srgb,var(--accent-cool)_56%,var(--source-step-border,var(--border-soft)))] hover:shadow-[var(--vui-elevation-2-sheen)] " +
  "focus-visible:outline-none focus-visible:-translate-y-px focus-visible:shadow-[var(--vui-elevation-2-sheen)] focus-visible:border-[color:color-mix(in_srgb,var(--accent-cool)_56%,var(--source-step-border,var(--border-soft)))]";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_72%,var(--border-strong))] shadow-[var(--vui-shadow-inset-accent),var(--vui-elevation-2)]";

const HEADER = "flex min-w-0 items-center gap-2";
const STEP_INDEX =
  "flex h-[22px] min-w-[26px] items-center justify-center rounded-[6px] border border-[color:color-mix(in_srgb,var(--accent-cool)_26%,var(--border-soft))] bg-[color:color-mix(in_srgb,var(--accent-cool)_7%,var(--surface-card))] text-[0.62rem] font-[860] text-[color:color-mix(in_srgb,var(--accent-cool)_78%,var(--fg-primary))]";
const STATUS_BADGE =
  "max-w-[58%] rounded-full border border-[color:color-mix(in_srgb,var(--source-step-fg,var(--fg-muted))_28%,var(--border-soft))] bg-[color:color-mix(in_srgb,var(--source-step-fg,var(--fg-muted))_8%,transparent)] px-2 py-[2px] text-[0.58rem] font-[840] text-[color:var(--source-step-fg,var(--fg-muted))]";
const BODY = "grid min-w-0 content-start gap-1";
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

  return (
    <article
      data-vui-product="team-stage-card"
      data-tone={tone}
      className={[CARD_BASE, selected ? CARD_SELECTED : ""].filter(Boolean).join(" ")}
      style={TEAM_STAGE_TONE_STYLE[tone]}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      title={title}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <div className={BODY}>
        <div className={HEADER}>
          <strong className={STEP_INDEX}>
            {String(index + 1).padStart(2, "0")}
          </strong>
          <b className={`text-[0.86rem] text-[var(--fg-primary)] ${TEXT_TRUNCATE}`}>{label}</b>
          <span className={`${STATUS_BADGE} ${TEXT_TRUNCATE} ml-auto`}>
            {status}
          </span>
        </div>
        <em className={`not-italic text-[0.66rem] font-[760] text-[var(--fg-muted)] ${TEXT_TRUNCATE}`}>
          {metric}
        </em>
        <small
          className={`text-[0.64rem] font-[820] text-[color:var(--source-step-fg,var(--fg-muted))] ${TEXT_TRUNCATE}`}
        >
          {nextLabel}
        </small>
      </div>
      {actions ? <div className={ACTION_ROW}>{actions}</div> : null}
    </article>
  );
}
