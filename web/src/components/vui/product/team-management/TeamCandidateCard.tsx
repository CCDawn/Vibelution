import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import {
  type TeamSourceResultMetaEntry,
  type TeamSourceResultProvenance,
  type TeamSourceResultTone,
} from "./TeamSourceResultList";

export type TeamCandidateCardProps = {
  title: ReactNode;
  statusLabel: ReactNode;
  statusTitle?: string;
  tone: TeamSourceResultTone;
  summary?: ReactNode;
  meta?: TeamSourceResultMetaEntry[];
  source?: TeamSourceResultProvenance;
  /** Mutation buttons supplied by the route; the card styles them uniformly. */
  actions?: ReactNode;
  selected?: boolean;
  onActivate?: () => void;
  activateTitle?: string;
};

/**
 * Candidate card shared by the screening / graph / ingestion candidate lists —
 * classes reproduce the verified `workflowCandidateItem` baseline (dense
 * bordered row, accent selected state) with the standard chip and action-rail
 * grammar from the sibling team-management components.
 */
const CARD_BASE =
  "grid grid-cols-[minmax(0,1fr)_minmax(120px,220px)] min-h-[40px] items-center gap-2 px-2 py-1 min-w-0 " +
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] " +
  "max-[820px]:grid-cols-[minmax(0,1fr)]";

const CARD_INTERACTIVE =
  "cursor-pointer transition-[border-color,box-shadow,background] duration-150 ease-[var(--vui-ease)] " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] hover:bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))] hover:shadow-[var(--vui-elevation-1)] " +
  "focus-visible:outline-none focus-visible:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] focus-visible:shadow-[var(--vui-elevation-1)]";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_11%,transparent)]";

const CHIP_BASE =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border px-2 " +
  "text-[var(--vui-font-xs)] font-semibold leading-none whitespace-nowrap min-w-0";

const CHIP_TONE: Record<TeamSourceResultTone, string> = {
  ready:
    "border-[color:color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  warning:
    "border-[color:color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  danger:
    "border-[color:color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color:color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  neutral: "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]",
};

const ACTIONS =
  "flex flex-wrap items-center gap-1.5 min-w-0 " +
  "[&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center " +
  "[&_[data-vui=native-button]]:gap-1 [&_[data-vui=native-button]]:min-h-[26px] [&_[data-vui=native-button]]:px-2 " +
  "[&_[data-vui=native-button]]:rounded-[7px] [&_[data-vui=native-button]]:border " +
  "[&_[data-vui=native-button]]:border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] " +
  "[&_[data-vui=native-button]]:bg-[color:color-mix(in_srgb,var(--surface-card)_74%,transparent)] " +
  "[&_[data-vui=native-button]]:text-[var(--fg-primary)] [&_[data-vui=native-button]]:text-[var(--vui-font-xs)] " +
  "[&_[data-vui=native-button]:disabled]:cursor-not-allowed [&_[data-vui=native-button]:disabled]:opacity-55";

export function TeamCandidateCard({
  title,
  statusLabel,
  statusTitle,
  tone,
  summary,
  meta,
  source,
  actions,
  selected = false,
  onActivate,
  activateTitle,
}: TeamCandidateCardProps) {
  const handleKeyDown = onActivate
    ? (event: ReactKeyboardEvent<HTMLElement>) => {
        if (event.target instanceof Element && event.target.closest("button, a")) {
          return;
        }
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        event.preventDefault();
        onActivate();
      }
    : undefined;

  const handleClick = onActivate
    ? (event: React.MouseEvent<HTMLElement>) => {
        if (event.target instanceof Element && event.target.closest("button, a")) {
          return;
        }
        onActivate();
      }
    : undefined;

  return (
    <article
      data-vui-product="team-candidate-card"
      data-tone={tone}
      className={[CARD_BASE, onActivate ? CARD_INTERACTIVE : "", selected ? CARD_SELECTED : ""]
        .filter(Boolean)
        .join(" ")}
      role={onActivate ? "button" : undefined}
      tabIndex={onActivate ? 0 : undefined}
      aria-pressed={onActivate ? selected : undefined}
      title={activateTitle}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <div className="flex flex-wrap items-center gap-1.5 min-w-0 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)]">
        <strong>{title}</strong>
        <span className={`${CHIP_BASE} ${CHIP_TONE[tone]}`} title={statusTitle}>
          {statusLabel}
        </span>
      </div>
      {summary ? (
        <p className="m-0 min-w-0 truncate text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]">{summary}</p>
      ) : null}
      {meta && meta.length ? (
        <div className="flex flex-wrap items-center gap-1.5 min-w-0 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)] [&_span:first-child]:text-[var(--fg-secondary)]">
          {meta.map((entry) => (
            <span key={entry.key}>{entry.label}</span>
          ))}
        </div>
      ) : null}
      {source ? (
        <div
          data-missing={source.missing ? "true" : undefined}
          className="grid grid-cols-[max-content_minmax(0,1fr)] items-center gap-1 overflow-hidden min-w-0 text-[var(--vui-font-xs)] [&_a]:truncate [&_code]:truncate [&_a]:text-[var(--accent-cool)] [&_code]:text-[var(--fg-tertiary)] data-[missing=true]:text-[var(--state-warning)]"
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
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </article>
  );
}
