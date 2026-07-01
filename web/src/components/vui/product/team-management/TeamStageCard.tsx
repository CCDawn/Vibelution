import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

export type TeamStageTone = "active" | "done" | "failed" | "idle" | "pending";

/**
 * Faithful reproduction of the original `.sourceCollectionStageCard` design
 * (recovered from TeamsRoute.module.css @ ccf0cb5a~1). The stage state drives
 * the `--source-step-border` / `--source-step-fg` custom properties the card
 * cascades into its border + text colours.
 */
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
  "grid grid-rows-[auto_auto_auto] content-start self-start min-w-0 min-h-0 gap-1 p-1.5 rounded-[7px] border cursor-pointer overflow-hidden text-[0.66rem] font-[740] " +
  "border-[color:var(--source-step-border,var(--border-soft))] text-[color:var(--source-step-fg,var(--fg-muted))] " +
  "bg-[image:var(--vui-gradient-route-soft)] bg-[color:var(--source-workbench-card)] " +
  "transition-[border-color,box-shadow] duration-150 " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-cool)_56%,var(--source-step-border,var(--border-soft)))] hover:shadow-[var(--vui-shadow-accent)] " +
  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-accent)] focus-visible:border-[color:color-mix(in_srgb,var(--accent-cool)_56%,var(--source-step-border,var(--border-soft)))]";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_72%,var(--border-strong))] shadow-[var(--vui-shadow-inset-accent)]";

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
      <div className="flex min-w-0 items-center justify-between gap-1.5">
        <strong className="flex-none text-[0.62rem] text-[color:color-mix(in_srgb,var(--accent-cool)_74%,var(--fg-primary))]">
          {String(index + 1).padStart(2, "0")}
        </strong>
        <span
          className={`text-[0.58rem] font-[820] text-[color:var(--source-step-fg,var(--fg-muted))] ${TEXT_TRUNCATE}`}
        >
          {status}
        </span>
      </div>
      <span className="grid content-start gap-0.5 min-w-0">
        <b className={`text-[0.74rem] text-[var(--fg-primary)] ${TEXT_TRUNCATE}`}>{label}</b>
        <em className={`not-italic text-[0.6rem] font-[760] text-[var(--fg-muted)] ${TEXT_TRUNCATE}`}>
          {metric}
        </em>
        <small
          className={`text-[0.58rem] font-[820] text-[color:var(--source-step-fg,var(--fg-muted))] ${TEXT_TRUNCATE}`}
        >
          {nextLabel}
        </small>
      </span>
      {actions ? <div className="min-w-0">{actions}</div> : null}
    </article>
  );
}
