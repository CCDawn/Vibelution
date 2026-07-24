import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailActionButton:
    `detailActionButton min-w-0 ${vuiControlQuietClass}`,
  emptyState:
    "emptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reviewQueueActions:
    "reviewQueueActions min-w-0 flex flex-wrap items-center gap-1.5",
  reviewQueueBody:
    "reviewQueueBody min-w-0 grid min-w-0 content-start gap-1 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  // Single card, single column — solid background so nothing paints through from the next section.
  reviewQueueItem: `reviewQueueItem relative z-0 min-w-0 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-1.5 ${vuiOpaqueRowClass} p-2.5 shadow-none`,
  reviewQueueList:
    "reviewQueueList min-w-0 grid content-start gap-2",
  // Plain body text; do not re-introduce nested bordered cards.
  reviewQueueSummary:
    "reviewQueueSummary m-0 min-w-0 max-w-full [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere] [word-break:break-word]",
  reviewQueueTime:
    "reviewQueueTime min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  // Title + origin on one row: title takes remaining width, origin is content-sized chip (no 0.38fr dead column).
  reviewQueueTitleLine:
    "reviewQueueTitleLine min-w-0 max-w-full !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 [font-size:var(--vui-font-sm)] font-semibold leading-snug text-[var(--fg-primary)] [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_strong]:[word-break:break-word] [&_span]:min-w-0 [&_span]:max-w-[12rem] [&_span]:truncate [&_span]:rounded-full [&_span]:border [&_span]:border-[var(--vui-border-subtle)] [&_span]:bg-[var(--vui-control-muted)] [&_span]:px-2 [&_span]:py-0.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:font-semibold [&_span]:text-[var(--fg-secondary)]",
  reviewRank:
    "reviewRank mt-0.5 inline-flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 [font-size:var(--vui-font-xs)] font-bold text-[var(--fg-tertiary)]",
  reviewReasonList:
    "reviewReasonList min-w-0 flex flex-wrap gap-1.5",
  reviewReasonPill:
    `reviewReasonPill min-w-0 ${vuiControlPillClass}`,
} as const;

export default styles;
