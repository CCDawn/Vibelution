const styles = {
  root:
    "flex min-h-0 flex-1 flex-col gap-2 overflow-hidden bg-[var(--vui-surface-canvas)] p-2",
  tabRail:
    "flex shrink-0 items-center gap-1.5 overflow-x-auto rounded-[var(--vui-radius-lg)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1.5 [scrollbar-width:thin]",
  tabButton:
    "!h-auto [min-height:46px] [min-width:132px] [max-width:240px] [flex:1_1_132px] !justify-start !rounded-[var(--vui-radius-md)] !border !border-transparent !bg-transparent !px-2 !py-1.5 !text-left hover:!border-[var(--vui-border-subtle)] hover:!bg-[var(--vui-surface-row)]",
  tabButtonActive:
    "!border-[color-mix(in_srgb,_var(--accent-cool)_52%,_var(--vui-border-subtle))] !bg-[color-mix(in_srgb,_var(--accent-cool)_9%,_var(--vui-surface-row))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)]",
  tabLayout: "grid w-full min-w-0 [grid-template-columns:24px_minmax(0,_1fr)] items-center gap-2",
  avatar:
    "grid size-6 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-surface-muted))] text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text-strong)]",
  tabCopy: "min-w-0",
  tabTitle: "block truncate text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  tabSubtitle:
    "mt-0.5 flex min-w-0 items-center gap-1.5 truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  tabStatus: "text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text-muted)]",
  tabStatusActive: "text-[var(--accent-cool)]",
  sessionSurface:
    "flex min-h-0 flex-1 flex-col overflow-hidden rounded-[var(--vui-radius-lg)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] shadow-[0_4px_16px_color-mix(in_srgb,_var(--vui-text-strong)_5%,_transparent)]",
  selectedHeader:
    "flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2",
  selectedIdentity: "flex min-w-0 items-center gap-2",
  selectedCopy: "min-w-0",
  selectedTitle: "truncate text-[length:var(--vui-font-md)] font-semibold text-[var(--vui-text-strong)]",
  selectedMeta: "mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  selectedDescription: "max-w-[260px] truncate",
  selectedMetaValue: "max-w-[260px] truncate",
  selectedActions: "flex shrink-0 items-center gap-1.5",
  compactAction: "!h-7 !w-fit !min-w-0 !px-2 !text-[length:var(--vui-font-xs)]",
  sessionLink:
    "inline-flex h-7 w-fit items-center gap-1 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] px-2 text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text)] transition hover:border-[var(--accent-cool)] hover:text-[var(--accent-cool)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-cool)]",
  body:
    "relative flex min-h-[320px] flex-1 overflow-hidden bg-[color-mix(in_srgb,_var(--vui-surface-chat)_92%,_var(--vui-surface-muted))]",
  conversation: "h-full min-h-0 w-full flex-1",
  loading: "grid h-full min-h-[320px] w-full place-items-center text-[length:var(--vui-font-sm)] text-[var(--vui-text-muted)]",
  empty:
    "m-auto flex w-[min(72%,_460px)] flex-col items-center gap-2 rounded-[var(--vui-radius-lg)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-8 py-7 text-center text-[length:var(--vui-font-sm)] leading-6 text-[var(--vui-text-muted)]",
  emptyAvatar:
    "grid size-10 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  emptyTitle: "text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  queryNotice:
    "absolute inset-x-3 top-2 z-10 rounded-[var(--vui-radius-sm)] border border-[color-mix(in_srgb,_var(--vui-danger)_32%,_var(--vui-border-subtle))] bg-[color-mix(in_srgb,_var(--vui-danger)_7%,_var(--vui-surface-panel))] px-2 py-1 text-[length:var(--vui-font-xs)] text-[var(--vui-danger)]",
} as const;

export default styles;
