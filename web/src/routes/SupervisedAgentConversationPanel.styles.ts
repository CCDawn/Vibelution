const styles = {
  root:
    "flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden bg-vui-surface-workspace p-2",
  tabRail:
    "grid shrink-0 grid-flow-col auto-cols-[minmax(152px,1fr)] gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
  tabButton:
    "min-h-[54px] w-full min-w-0 justify-start px-2 py-1.5 text-left",
  tabLayout:
    "grid w-full min-w-0 [grid-template-columns:28px_minmax(0,1fr)_auto] items-center gap-2",
  avatar:
    "grid size-7 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-surface-muted))] text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text-strong)]",
  tabCopy: "min-w-0",
  tabTitle: "block truncate text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  tabSubtitle: "mt-0.5 block truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  tabStatus:
    "mt-0.5 min-h-5 shrink-0 self-start px-1.5",
  sessionSurface:
    "flex min-h-[544px] flex-1 flex-col overflow-hidden",
  selectedHeader:
    "flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-x-[18px] gap-y-2.5 border-b border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,_var(--vui-surface-row)_54%,_var(--vui-surface-panel))] px-[13px] py-[11px]",
  selectedIdentity: "flex min-w-0 flex-[1_1_270px] items-center gap-2.5",
  selectedAvatar:
    "grid size-8 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_16%,_var(--vui-surface-muted))] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  selectedCopy: "min-w-0",
  selectedTitleRow: "flex min-w-0 flex-wrap items-center gap-1.5",
  selectedTitle: "truncate text-[length:var(--vui-font-md)] font-semibold text-[var(--vui-text-strong)]",
  identityChip: "min-h-5 px-1.5",
  selectedDescription:
    "mt-1 max-w-[430px] truncate text-[length:var(--vui-font-xs)] leading-5 text-[var(--vui-text-muted)]",
  selectedFacts: "grid min-w-0 flex-[1_1_320px] grid-cols-4",
  factCell:
    "min-w-[70px] border-l border-[var(--vui-border-subtle)] px-2.5 first:border-l-0",
  factLabel:
    "mb-1 whitespace-nowrap text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  factValue:
    "max-w-[130px] truncate whitespace-nowrap font-mono text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text)] [&>span]:block [&>span]:truncate",
  timelineToolbar:
    "shrink-0 justify-between gap-3 border-b border-vui-border-subtle bg-vui-surface-toolbar px-3 py-2",
  conversationContract: "flex min-w-0 items-center gap-2",
  contractChip: "min-h-6 shrink-0 gap-1.5",
  contractMeta: "truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  toolbarActions: "flex shrink-0 items-center gap-1.5",
  compactAction: "h-7 w-fit min-w-0 px-2 text-[length:var(--vui-font-xs)]",
  sessionAction: "h-7 w-fit min-w-0 px-2 text-[length:var(--vui-font-xs)]",
  body:
    "relative flex min-h-[430px] flex-1 overflow-hidden bg-vui-surface-chat",
  conversation: "h-full min-h-[430px] w-full flex-1",
  loading:
    "flex h-full min-h-[430px] w-full items-center justify-center gap-2 text-[length:var(--vui-font-sm)] text-vui-fg-tertiary",
  empty:
    "m-auto w-[min(72%,_460px)] px-8 py-7 text-center",
  emptyAvatar:
    "grid size-10 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  queryNotice:
    "absolute inset-x-3 top-2 z-10",
} as const;

export default styles;
