const styles = {
  root: "flex min-h-0 flex-1 flex-col overflow-hidden",
  tabRail:
    "grid shrink-0 auto-cols-[minmax(148px,_1fr)] grid-flow-col gap-1.5 overflow-x-auto border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 [scrollbar-width:thin]",
  tabButton:
    "!h-auto min-h-[52px] min-w-[148px] !justify-start !rounded-[var(--vui-radius-md)] !border !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row)] !px-2 !py-1.5 !text-left",
  tabButtonActive:
    "!border-[color-mix(in_srgb,_var(--accent-cool)_52%,_var(--vui-border-subtle))] !bg-[color-mix(in_srgb,_var(--accent-cool)_9%,_var(--vui-surface-row))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)]",
  tabLayout: "grid w-full min-w-0 grid-cols-[28px_minmax(0,_1fr)_auto] items-center gap-2",
  avatar:
    "grid size-7 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-surface-muted))] text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text-strong)]",
  tabCopy: "min-w-0",
  tabTitle: "block truncate text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  tabSubtitle: "mt-0.5 block truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  tabStatus: "text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text-muted)]",
  tabStatusActive: "text-[var(--accent-cool)]",
  selectedHeader:
    "flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2",
  selectedIdentity: "flex min-w-0 items-center gap-2",
  selectedCopy: "min-w-0",
  selectedTitle: "truncate text-[length:var(--vui-font-md)] font-semibold text-[var(--vui-text-strong)]",
  selectedMeta: "mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  selectedMetaValue: "max-w-[260px] truncate",
  selectedActions: "flex shrink-0 items-center gap-1.5",
  compactAction: "!h-7 !w-fit !min-w-0 !px-2 !text-[length:var(--vui-font-xs)]",
  sessionLink:
    "inline-flex h-7 w-fit items-center gap-1 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] px-2 text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text)] transition hover:border-[var(--accent-cool)] hover:text-[var(--accent-cool)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-cool)]",
  body: "relative flex min-h-[320px] flex-1 overflow-hidden bg-[var(--vui-surface-chat)]",
  conversation: "h-full min-h-0 w-full flex-1",
  loading: "grid h-full min-h-[320px] w-full place-items-center text-[length:var(--vui-font-sm)] text-[var(--vui-text-muted)]",
  empty:
    "m-auto flex max-w-[460px] flex-col items-center gap-2 px-6 py-10 text-center text-[length:var(--vui-font-sm)] text-[var(--vui-text-muted)]",
  emptyAvatar:
    "grid size-10 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  emptyTitle: "text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  queryNotice:
    "absolute inset-x-3 top-2 z-10 rounded-[var(--vui-radius-sm)] border border-[color-mix(in_srgb,_var(--vui-danger)_32%,_var(--vui-border-subtle))] bg-[color-mix(in_srgb,_var(--vui-danger)_7%,_var(--vui-surface-panel))] px-2 py-1 text-[length:var(--vui-font-xs)] text-[var(--vui-danger)]",
} as const;

export default styles;
