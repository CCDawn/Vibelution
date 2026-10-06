const border = "border-[var(--vui-border-subtle)]";
const muted = "text-[var(--fg-tertiary)]";

export default {
  page: "grid min-w-0 content-start gap-3 p-3 lg:p-4",
  heading: "flex min-w-0 items-center justify-between gap-2 [&_h1]:m-0 [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-[var(--fg-primary)]",
  grid: "grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1.7fr)_minmax(17rem,1fr)]",
  mainColumn: "grid min-w-0 content-start gap-3",
  sideColumn: "grid min-w-0 content-start gap-3",
  panel: `grid min-w-0 content-start gap-3 rounded-[var(--vui-radius-soft)] border ${border} bg-[var(--vui-surface-panel)]`,
  panelHeading: `flex min-w-0 items-center justify-between gap-2 border-b ${border} pb-2 [&_h2]:m-0 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-[var(--fg-primary)] [&_span]:text-xs ${muted}`,
  tableWrap: "min-w-0 max-w-full overflow-x-auto",
  stockButton: "!h-auto !min-h-0 !max-w-full !justify-start !px-0.5 !py-1 text-left",
  stockIdentity: "grid min-w-0 gap-0.5 [&_strong]:truncate [&_strong]:text-xs [&_strong]:font-medium [&_strong]:text-[var(--fg-primary)] [&_small]:truncate [&_small]:font-mono [&_small]:text-[var(--vui-type-caption-size)] [&_small]:text-[var(--fg-tertiary)]",
  number: "font-mono text-xs tabular-nums text-[var(--fg-primary)]",
  muted: muted,
  rise: "text-[var(--state-error)]",
  fall: "text-[var(--state-success)]",
  quoteFooter: `flex min-w-0 flex-wrap items-center justify-between gap-2 border-t ${border} pt-2 text-xs ${muted}`,
  skeleton: "grid min-w-0 gap-2",
  warning: "m-0 text-xs text-[var(--state-warning)]",
  statusRows: `grid grid-cols-1 gap-2 text-xs ${muted} sm:grid-cols-3 [&_span]:grid [&_span]:gap-1 [&_strong]:font-medium [&_strong]:text-[var(--fg-primary)]`,
  shortcuts: "grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-2",
  recentList: `grid min-w-0 divide-y ${border}`,
  recentRow: `!h-auto !min-h-0 !w-full !justify-between !gap-3 !rounded-none !px-1 !py-2 text-left [&_span]:min-w-0`,
  recentTitle: "grid min-w-0 flex-1 gap-1 [&_strong]:truncate [&_strong]:text-xs [&_strong]:font-medium [&_strong]:text-[var(--fg-primary)] [&_small]:truncate [&_small]:text-[var(--vui-type-caption-size)] [&_small]:text-[var(--fg-tertiary)]",
} as const;
