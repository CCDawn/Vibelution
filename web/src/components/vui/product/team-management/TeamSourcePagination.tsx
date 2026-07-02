import { type MouseEvent as ReactMouseEvent, type ReactNode } from "react";

import { VButton } from "../../index";

export type TeamSourcePaginationProps = {
  ariaLabel: string;
  rangeLabel: ReactNode;
  page: number;
  pageCount: number;
  previousLabel: ReactNode;
  nextLabel: ReactNode;
  onPrevious: () => void;
  onNext: () => void;
  /** Swallows clicks so pagination inside clickable panels doesn't toggle them. */
  onContain?: (event: ReactMouseEvent<HTMLDivElement>) => void;
};

const BAR =
  "flex min-w-0 items-center justify-between gap-2 px-2 py-1.5 rounded-lg select-none whitespace-nowrap " +
  "border border-[color:color-mix(in_srgb,var(--accent-cool)_18%,var(--border-soft))] " +
  "bg-[color:var(--source-workbench-card)] text-[0.64rem] font-[800] text-[var(--fg-muted)]";

const BUTTON =
  "min-h-[24px] items-center justify-center rounded-[7px] border px-2 " +
  "border-[color:color-mix(in_srgb,var(--accent-cool)_26%,var(--border-soft))] " +
  "bg-[color:var(--source-workbench-card)] text-[0.62rem] font-[820] text-[var(--fg-primary)] " +
  "cursor-pointer data-[disabled=true]:cursor-not-allowed data-[disabled=true]:opacity-55";

/**
 * Faithful reproduction of `.sourceCollectionPagination`: a bordered pager bar
 * with the range label left and compact previous/next controls right.
 */
export function TeamSourcePagination({
  ariaLabel,
  rangeLabel,
  page,
  pageCount,
  previousLabel,
  nextLabel,
  onPrevious,
  onNext,
  onContain,
}: TeamSourcePaginationProps) {
  return (
    <div
      data-vui-product="team-source-pagination"
      className={BAR}
      aria-label={ariaLabel}
      onClick={onContain}
      onMouseDown={onContain}
    >
      <span className="min-w-0 truncate">{rangeLabel}</span>
      <div className="inline-flex items-center gap-1.5">
        <VButton density="compact" type="button" className={BUTTON} isDisabled={page <= 1} onClick={onPrevious}>
          {previousLabel}
        </VButton>
        <strong className="text-[var(--fg-primary)]">
          {page}/{pageCount}
        </strong>
        <VButton density="compact" type="button" className={BUTTON} isDisabled={page >= pageCount} onClick={onNext}>
          {nextLabel}
        </VButton>
      </div>
    </div>
  );
}
