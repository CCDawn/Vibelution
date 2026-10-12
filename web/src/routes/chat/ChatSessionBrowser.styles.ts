const styles = {
  root:
    "chatSessionBrowser flex h-full min-h-0 min-w-0 w-full flex-col overflow-y-auto px-4 py-5 sm:px-7 sm:py-7 lg:px-10",
  header:
    "flex min-w-0 flex-wrap items-start justify-between gap-3 pb-5 sm:gap-4",
  headingCopy: "min-w-0 flex-1 basis-full sm:basis-auto",
  eyebrow:
    "mb-1.5 block text-[11px] font-medium tracking-[0.025em] text-[var(--fg-tertiary)]",
  title:
    "m-0 text-[22px] font-semibold leading-tight tracking-[-0.025em] text-[var(--fg-primary)] sm:text-[24px]",
  description:
    "mb-0 mt-1.5 max-w-[58ch] text-[length:var(--vui-font-xs)] leading-relaxed text-[var(--fg-secondary)]",
  createButton: "mt-0 shrink-0 !min-h-[44px] sm:mt-4 sm:!min-h-8",
  tools:
    "flex min-w-0 flex-col gap-2 border-y border-[var(--vui-border-subtle)] py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3",
  search:
    "flex min-w-0 flex-1 items-center gap-2 text-[var(--fg-tertiary)]",
  searchInput:
    "min-w-0 flex-1 !border-transparent !bg-transparent !shadow-none focus-visible:!border-[var(--vui-border-subtle)]",
  filters:
    "flex min-w-0 flex-wrap items-center gap-0.5 sm:shrink-0 sm:justify-end",
  filter:
    "!h-11 !min-h-11 !rounded-[var(--radius-control)] !border-transparent !bg-transparent !px-3 !text-[length:var(--vui-font-xs)] !font-normal !text-[var(--fg-secondary)] !shadow-none hover:!bg-[var(--vui-control-muted-hover)] sm:!h-7 sm:!min-h-7 sm:!px-2",
  filterActive:
    "!bg-[var(--vui-surface-inset)] !font-medium !text-[var(--fg-primary)]",
  resultCount:
    "min-h-9 pt-2 text-[length:var(--vui-font-2xs)] text-[var(--fg-tertiary)]",
  inlineState:
    "mb-2",
  state:
    "my-2",
  list: "min-w-0 pb-5",
  group: "min-w-0 [&+section]:mt-5",
  groupTitle:
    "mb-1 flex min-h-7 items-center gap-1.5 px-2 text-[length:var(--vui-font-xs)] font-medium text-[var(--fg-secondary)] [&>svg]:text-[var(--fg-tertiary)] [&>span]:ml-auto [&>span]:text-[var(--fg-tertiary)] [&>span]:font-normal",
  groupRows: "grid min-w-0 gap-0.5",
  row:
    "chatSessionBrowserRow flex !h-auto !min-h-[76px] w-full min-w-0 !items-start !justify-start !gap-3 !rounded-[9px] !border !border-transparent !bg-transparent !px-3 !py-2.5 !text-left !text-[var(--fg-primary)] !shadow-none hover:!border-[var(--vui-border-subtle)] hover:!bg-[color-mix(in_srgb,var(--vui-surface-inset)_58%,transparent)] focus-visible:!outline-2 focus-visible:!outline-offset-2 focus-visible:!outline-[color-mix(in_srgb,var(--accent-cool)_52%,transparent)]",
  rowActive:
    "!border-[color-mix(in_srgb,var(--fg-primary)_8%,transparent)] !bg-[var(--vui-selection-bg)] !shadow-[var(--vui-sheen)] hover:!bg-[var(--vui-selection-bg)]",
  avatar:
    "mt-0.5 inline-grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] text-[11px] font-medium text-[var(--fg-secondary)]",
  rowCopy: "flex min-w-0 flex-1 flex-col items-stretch gap-1 text-left",
  titleLine: "flex min-w-0 items-center gap-2 leading-snug",
  sessionTitle: "min-w-0 truncate text-[length:var(--vui-font-sm)] font-medium text-[var(--fg-primary)]",
  teamTag:
    "inline-flex min-w-0 max-w-[40%] shrink-0 items-center gap-1 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] px-1.5 py-0.5 text-[10px] leading-none text-[var(--fg-secondary)] [&>span]:truncate",
  agentLine:
    "flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[length:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:max-w-full [&>span]:truncate",
  agentName: "font-medium text-[var(--fg-secondary)]",
  summary:
    "line-clamp-2 min-w-0 whitespace-normal text-[length:var(--vui-font-2xs)] leading-relaxed text-[var(--fg-tertiary)]",
  rowFooter: "flex min-w-0 items-center justify-between gap-3 pt-0.5",
  status:
    "inline-flex min-w-0 items-center gap-1.5 text-[length:var(--vui-font-2xs)] text-[var(--fg-tertiary)] [&>span:last-child]:truncate",
  statusMark: "h-1.5 w-1.5 shrink-0 rounded-full bg-[color-mix(in_srgb,var(--fg-tertiary)_68%,transparent)]",
  status_running: "text-[var(--state-success)] [&>span:first-child]:bg-[var(--state-success)]",
  status_approval: "text-[var(--state-warning)] [&>span:first-child]:bg-[var(--state-warning)]",
  status_error: "text-[var(--state-error)] [&>span:first-child]:bg-[var(--state-error)]",
  status_completed: "text-[var(--accent-cool)] [&>span:first-child]:bg-[var(--accent-cool)]",
  status_none: "text-[var(--fg-tertiary)]",
  time: "shrink-0 text-[10px] tabular-nums text-[var(--fg-tertiary)]",
} as const;

export default styles;
