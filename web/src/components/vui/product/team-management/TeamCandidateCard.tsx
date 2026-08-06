import { type ReactNode } from "react";
import { ExternalLink } from "lucide-react";

import { VNativeButton } from "../../primitives/VNativeButton";
import { VTooltip } from "../../primitives/VTooltip";

import {
  type TeamSourceResultMetaEntry,
  type TeamSourceResultProvenance,
} from "./TeamSourceResultList";
import { TeamStatusLabel } from "./TeamStatusLabel";
import { type TeamSourceResultTone } from "./teamSourceTone";

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
 * Candidate card keeps the operational decision surface to one visual row.
 * Supporting provenance stays available through hover/focus and its own link.
 */
const CARD_BASE =
  "flex min-h-[40px] min-w-0 items-center gap-2 px-2 py-1 " +
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] " +
  "max-[820px]:flex-wrap";

const CARD_INTERACTIVE =
  "transition-[border-color,box-shadow,background] duration-150 ease-[var(--vui-ease)] " +
  "hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:shadow-[var(--vui-elevation-1)] " +
  "has-[:focus-visible]:border-[var(--border-strong)] has-[:focus-visible]:shadow-[var(--vui-elevation-1)]";

const ACTIVATION_BUTTON =
  "inline-flex w-fit min-w-0 max-w-full items-center justify-start rounded-[var(--radius-control)] bg-transparent p-0 text-left text-[var(--fg-primary)] " +
  "cursor-pointer focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)] [&>strong]:min-w-0 [&>strong]:truncate";

const CARD_SELECTED =
  "border-[color:color-mix(in_srgb,var(--fg-primary)_28%,var(--border-strong))] bg-[color:color-mix(in_srgb,var(--fg-primary)_3%,var(--vui-surface-row))]";

const ACTIONS =
  "ml-auto flex flex-wrap items-center justify-end gap-1.5 min-w-0 max-[820px]:ml-0 " +
  "[&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center " +
  "[&_[data-vui=native-button]]:gap-1 [&_[data-vui=native-button]]:min-h-[26px] [&_[data-vui=native-button]]:px-2 " +
  "[&_[data-vui=native-button]]:rounded-[7px] [&_[data-vui=native-button]]:border " +
  "[&_[data-vui=native-button]]:border-[var(--vui-border-subtle)] " +
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
    <TeamStatusLabel
      tone={tone}
      tabIndex={statusTitle ? 0 : undefined}
      role={statusTitle ? "status" : undefined}
      aria-label={statusTitle}
    >
      {statusLabel}
    </TeamStatusLabel>
  );
  const detailsTooltip = (activateTitle || summary || (meta && meta.length) || source?.title) ? (
    <span className="grid gap-1">
      {activateTitle ? <span>{activateTitle}</span> : null}
      {summary ? <span>{summary}</span> : null}
      {meta?.map((entry) => <span key={entry.key}>{entry.label}</span>)}
      {statusTitle ? <span>{statusTitle}</span> : null}
      {source?.title ? <span>{source.title}</span> : null}
      {source ? <span>{source.label}：{source.value}</span> : null}
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
  const titleControl = detailsTooltip ? (
    <VTooltip content={detailsTooltip} width="wide">
      {titleValue}
    </VTooltip>
  ) : titleValue;
  const sourceActionLabel = source
    ? typeof source.title === "string"
      ? source.title
      : typeof source.label === "string"
        ? source.label
        : "打开来源"
    : "";

  return (
    <article
      data-vui-product="team-candidate-card"
      data-tone={tone}
      className={[CARD_BASE, onActivate ? CARD_INTERACTIVE : "", selected ? CARD_SELECTED : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex min-w-0 items-center gap-1.5 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[var(--fg-primary)]">
        {titleControl}
        {statusTitle ? <VTooltip content={statusTitle}>{statusBadge}</VTooltip> : statusBadge}
      </div>
      {source ? (
        <VTooltip content={source.title ?? source.label}>
          {source.href ? (
            <a
              href={source.href}
              target="_blank"
              rel="noreferrer"
              aria-label={sourceActionLabel}
              className="inline-grid size-7 shrink-0 place-items-center rounded-[var(--radius-control)] text-[var(--fg-secondary)] transition-colors hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]"
            >
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          ) : (
            <span
              data-missing={source.missing ? "true" : undefined}
              className="inline-grid size-7 shrink-0 place-items-center rounded-[var(--radius-control)] text-[var(--fg-tertiary)] data-[missing=true]:text-[var(--state-warning)]"
              aria-label={sourceActionLabel}
            >
              <ExternalLink size={14} aria-hidden="true" />
            </span>
          )}
        </VTooltip>
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </article>
  );
}
