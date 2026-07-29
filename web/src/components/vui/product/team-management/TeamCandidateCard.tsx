import { type ReactNode } from "react";

import { VNativeButton } from "../../primitives/VNativeButton";
import { VTooltip } from "../../primitives/VTooltip";

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
 * Candidate card shared by the screening / graph / ingestion candidate lists.
 * Source/provenance is kept in a bounded right rail on desktop so DOI and file
 * paths do not stretch the operational workbench.
 */
const CARD_BASE =
  "grid grid-cols-[minmax(0,1fr)_minmax(9rem,16rem)] auto-rows-min min-h-[40px] items-center gap-1.5 px-2 py-1 min-w-0 " +
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] " +
  "max-[820px]:grid-cols-[minmax(0,1fr)]";

const CARD_INTERACTIVE =
  "transition-[border-color,box-shadow,background] duration-150 ease-[var(--vui-ease)] " +
  "hover:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] hover:bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))] hover:shadow-[var(--vui-elevation-1)] " +
  "has-[:focus-visible]:border-[color:color-mix(in_srgb,var(--accent-cool)_54%,var(--border-strong))] has-[:focus-visible]:shadow-[var(--vui-elevation-1)]";

const ACTIVATION_BUTTON =
  "inline-flex w-fit min-w-0 max-w-full items-center justify-start rounded-[var(--radius-control)] bg-transparent p-0 text-left text-[var(--fg-primary)] " +
  "cursor-pointer focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)] [&>strong]:min-w-0 [&>strong]:truncate";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_11%,transparent)]";

const CHIP_BASE =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border px-2 " +
  "[font-size:var(--vui-font-xs)] font-semibold leading-none whitespace-nowrap min-w-0";

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
  "col-span-2 flex flex-wrap items-center justify-end gap-1.5 min-w-0 max-[820px]:col-span-1 max-[820px]:justify-start " +
  "[&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center " +
  "[&_[data-vui=native-button]]:gap-1 [&_[data-vui=native-button]]:min-h-[26px] [&_[data-vui=native-button]]:px-2 " +
  "[&_[data-vui=native-button]]:rounded-[7px] [&_[data-vui=native-button]]:border " +
  "[&_[data-vui=native-button]]:border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] " +
  "[&_[data-vui=native-button]]:bg-[color:color-mix(in_srgb,var(--vui-surface-row)_74%,transparent)] " +
  "[&_[data-vui=native-button]]:text-[var(--fg-primary)] [&_[data-vui=native-button]]:[font-size:var(--vui-font-xs)] " +
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
  const statusBadge = (
    <span
      className={`${CHIP_BASE} ${CHIP_TONE[tone]}`}
      tabIndex={statusTitle ? 0 : undefined}
      role={statusTitle ? "status" : undefined}
      aria-label={statusTitle}
    >
      {statusLabel}
    </span>
  );
  const sourceValue = source ? (
    source.href ? (
      <a
        href={source.href}
        target="_blank"
        rel="noreferrer"
        aria-label={source.title}
      >
        {source.value}
      </a>
    ) : (
      <code tabIndex={source.title ? 0 : undefined} aria-label={source.title}>{source.value}</code>
    )
  ) : null;
  const activationTooltip = activateTitle ? (
    <span className="grid gap-1">
      <span>{activateTitle}</span>
      {statusTitle ? <span>{statusTitle}</span> : null}
      {source?.title ? <span>{source.title}</span> : null}
    </span>
  ) : null;
  const titleValue = onActivate ? (
    <VNativeButton
      className={ACTIVATION_BUTTON}
      aria-label={activateTitle}
      aria-pressed={selected}
      onClick={onActivate}
    >
      <strong>{title}</strong>
    </VNativeButton>
  ) : (
    <strong>{title}</strong>
  );
  const titleControl = activationTooltip ? (
    <VTooltip content={activationTooltip} width="wide">
      {titleValue}
    </VTooltip>
  ) : titleValue;

  return (
    <article
      data-vui-product="team-candidate-card"
      data-tone={tone}
      className={[CARD_BASE, onActivate ? CARD_INTERACTIVE : "", selected ? CARD_SELECTED : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="col-start-1 flex flex-wrap items-center gap-1.5 min-w-0 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)]">
        {titleControl}
        {statusTitle ? <VTooltip content={statusTitle}>{statusBadge}</VTooltip> : statusBadge}
      </div>
      {summary ? (
        <p className="col-start-1 m-0 min-w-0 truncate [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]">{summary}</p>
      ) : null}
      {meta && meta.length ? (
        <div className="col-start-1 flex flex-wrap items-center gap-1.5 min-w-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)] [&_span:first-child]:text-[var(--fg-secondary)]">
          {meta.map((entry) => (
            <span key={entry.key}>{entry.label}</span>
          ))}
        </div>
      ) : null}
      {source ? (
        <div
          data-missing={source.missing ? "true" : undefined}
          className="col-start-2 row-start-1 row-span-3 grid min-w-0 max-w-full grid-cols-[max-content_minmax(0,1fr)] items-center self-center gap-1 overflow-hidden [font-size:var(--vui-font-xs)] [&_a]:truncate [&_code]:truncate [&_a]:text-[var(--accent-cool)] [&_code]:text-[var(--fg-tertiary)] max-[820px]:col-start-1 max-[820px]:row-start-auto max-[820px]:row-span-1 data-[missing=true]:text-[var(--state-warning)]"
        >
          <span className="text-[var(--fg-tertiary)]">{source.label}</span>
          {source.title ? (
            <VTooltip content={source.title} width="wide">
              {sourceValue}
            </VTooltip>
          ) : (
            sourceValue
          )}
        </div>
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </article>
  );
}
