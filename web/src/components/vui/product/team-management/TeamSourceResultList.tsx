import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

export type TeamSourceResultTone = "ready" | "warning" | "danger" | "neutral";

export type TeamSourceResultMetaEntry = {
  key: string;
  label: ReactNode;
};

export type TeamSourceResultProvenance = {
  label: ReactNode;
  value: ReactNode;
  href?: string;
  title?: string;
  missing?: boolean;
};

export type TeamSourceResultItemProps = {
  tone: TeamSourceResultTone;
  statusLabel: ReactNode;
  statusTitle?: string;
  title: ReactNode;
  titleTooltip?: string;
  meta: TeamSourceResultMetaEntry[];
  source: TeamSourceResultProvenance;
  selected?: boolean;
  /** When provided the row is keyboard/click activatable (linked candidate). */
  onActivate?: () => void;
  activateTitle?: string;
};

/**
 * Faithful reproduction of `.sourceCollectionResultItem` as verified against
 * live data: status chip | title | meta | provenance in a dense 4-column row,
 * with the accent-tinted selected/hover states from the original design.
 */
const ROW_BASE =
  "grid grid-cols-[max-content_minmax(0,1fr)_max-content_minmax(120px,220px)] min-h-[36px] items-center gap-2 px-2 py-1 min-w-0 " +
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] " +
  "max-[820px]:grid-cols-[max-content_minmax(0,1fr)]";

const ROW_INTERACTIVE =
  "cursor-pointer transition-[border-color,box-shadow,background] duration-150 ease-[var(--vui-ease)] " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] hover:bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))] hover:shadow-[var(--vui-shadow-inset-accent),var(--vui-elevation-1)] " +
  "focus-visible:outline-none focus-visible:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] focus-visible:shadow-[var(--vui-shadow-inset-accent),var(--vui-elevation-1)]";

const ROW_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_11%,var(--vui-surface-row))] shadow-[var(--vui-shadow-inset-accent)]";

const CHIP_BASE =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border px-2 " +
  "text-[var(--vui-font-xs)] font-semibold leading-none whitespace-nowrap justify-self-start min-w-0";

const CHIP_TONE: Record<TeamSourceResultTone, string> = {
  ready:
    "border-[color:color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  warning:
    "border-[color:color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  danger:
    "border-[color:color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  neutral: "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]",
};

export function TeamSourceResultItem({
  tone,
  statusLabel,
  statusTitle,
  title,
  titleTooltip,
  meta,
  source,
  selected = false,
  onActivate,
  activateTitle,
}: TeamSourceResultItemProps) {
  const handleKeyDown = onActivate
    ? (event: ReactKeyboardEvent<HTMLElement>) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        event.preventDefault();
        onActivate();
      }
    : undefined;

  return (
    <article
      data-vui-product="team-source-result-item"
      data-tone={tone}
      className={[ROW_BASE, onActivate ? ROW_INTERACTIVE : "", selected ? ROW_SELECTED : ""]
        .filter(Boolean)
        .join(" ")}
      role={onActivate ? "button" : undefined}
      tabIndex={onActivate ? 0 : -1}
      aria-pressed={onActivate ? selected : undefined}
      title={activateTitle}
      onClick={onActivate}
      onKeyDown={handleKeyDown}
    >
      <span className={`${CHIP_BASE} ${CHIP_TONE[tone]}`} title={statusTitle}>
        {statusLabel}
      </span>
      <div className="min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_strong]:block [&_strong]:truncate">
        <strong title={titleTooltip}>{title}</strong>
      </div>
      <div className="flex min-w-[76px] flex-nowrap items-center gap-1 whitespace-nowrap text-[var(--vui-font-xs)] text-[var(--fg-tertiary)] [&_span:first-child]:text-[var(--fg-secondary)] max-[820px]:hidden">
        {meta.map((entry) => (
          <span key={entry.key}>{entry.label}</span>
        ))}
      </div>
      <div
        data-missing={source.missing ? "true" : undefined}
        className="grid grid-cols-[max-content_minmax(0,1fr)] items-center gap-1 overflow-hidden text-[var(--vui-font-xs)] [&_a]:truncate [&_code]:truncate [&_a]:text-[var(--accent-cool)] [&_code]:text-[var(--fg-tertiary)] max-[820px]:col-span-2 data-[missing=true]:text-[var(--state-warning)]"
      >
        <span className="text-[var(--fg-tertiary)]">{source.label}</span>
        {source.href ? (
          <a
            href={source.href}
            target="_blank"
            rel="noreferrer"
            title={source.title}
            onClick={(event) => event.stopPropagation()}
          >
            {source.value}
          </a>
        ) : (
          <code title={source.title}>{source.value}</code>
        )}
      </div>
    </article>
  );
}

export type TeamSourceResultListProps = {
  ariaLabel?: string;
  children: ReactNode;
};

/** Faithful reproduction of `.sourceCollectionResultList`: a dense scrollable row stack. */
export function TeamSourceResultList({ ariaLabel, children }: TeamSourceResultListProps) {
  return (
    <div
      data-vui-product="team-source-result-list"
      aria-label={ariaLabel}
      className="grid min-h-0 min-w-0 content-start gap-1.5 overflow-auto"
    >
      {children}
    </div>
  );
}
