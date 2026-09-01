/**
 * Challenge-cup hypothesis leaderboard (read-only inspector panel).
 * Lives inside the research process inspector column (300–520px), so grids
 * respond to the container, never the viewport. Composes existing VUI atoms.
 */
export default {
  root: "flex min-h-0 w-full flex-col gap-3 p-1 [font-size:var(--vui-font-xs)]",
  header: "flex flex-wrap items-center justify-between gap-2",
  eyebrow: "text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]",
  topline: "flex flex-wrap items-center gap-2",
  switcher: "min-w-40 max-w-full flex-1",
  metaRow: "flex flex-wrap items-center gap-x-3 gap-y-1 text-[var(--fg-tertiary)] [font-size:var(--vui-font-2xs)]",
  roundCard:
    "grid gap-2.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_p]:m-0",
  sectionTitle: "text-[11px] font-semibold text-[var(--fg-primary)]",
  badgeRow: "flex flex-wrap items-center gap-1.5",
  summaryCard:
    "grid gap-1.5 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] p-2.5 [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:leading-[1.5] [&_span]:[font-size:var(--vui-font-2xs)] [&_span]:font-[650] [&_span]:tracking-[0.02em] [&_span]:text-[var(--fg-secondary)]",
  candidateList: "grid gap-1.5",
  candidateCard:
    "grid gap-1.5 rounded-[var(--vui-radius-control)] bg-[var(--vui-surface-inset)] p-2.5 data-[recommended=true]:border data-[recommended=true]:border-[var(--vui-border-subtle)] data-[recommended=true]:bg-[var(--vui-surface-card)]",
  candidateHead: "flex flex-wrap items-center gap-1.5",
  rank: "[font-size:var(--vui-font-2xs)] font-[650] text-[var(--fg-tertiary)]",
  candidateId: "wrap-anywhere font-medium text-[var(--fg-primary)] [font-size:var(--vui-font-2xs)]",
  claimText: "wrap-anywhere text-[var(--fg-primary)] [font-size:var(--vui-font-2xs)]",
  mutedText: "wrap-anywhere text-[var(--fg-secondary)] [font-size:var(--vui-font-2xs)]",
  scoreGrid:
    "grid grid-cols-2 gap-1 @min-[400px]:grid-cols-5 [&>div]:grid [&>div]:gap-[2px] [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-card)] [&>div]:p-1.5 [&_span]:text-[10px] [&_span]:text-[var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-2xs)]",
  recordRow: "flex flex-wrap items-center gap-2 text-[var(--fg-secondary)] [font-size:var(--vui-font-2xs)]",
  detailList: "m-0 grid list-none gap-1 p-0",
  detailItem:
    "grid gap-0.5 rounded border border-[var(--vui-border-subtle)] px-2 py-1.5 text-[var(--fg-secondary)] [font-size:var(--vui-font-2xs)]",
  detailTopline: "flex flex-wrap items-center gap-1.5",
  detailText: "wrap-anywhere",
  reviewRow:
    "grid gap-0.5 rounded border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] px-2 py-1.5 [font-size:var(--vui-font-2xs)]",
  reviewList: "grid gap-1",
  reviewHead: "flex flex-wrap items-center gap-1.5",
  reviewMeta: "wrap-anywhere text-[var(--fg-tertiary)]",
  reviewText: "wrap-anywhere text-[var(--fg-secondary)]",
  empty: "h-auto w-full border-0 bg-transparent",
  fill: "min-h-24",
} as const;
