const styles = {
  root:
    "flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden bg-[var(--vui-surface-canvas)] p-2",
  tabRail:
    "grid shrink-0 grid-flow-col auto-cols-[minmax(152px,1fr)] gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
  tabButton:
    "!h-auto min-h-[54px] !w-full min-w-0 !justify-start !rounded-[var(--vui-radius-md)] !border !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] !px-2 !py-1.5 !text-left hover:!border-[color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] hover:!bg-[var(--vui-surface-row)]",
  tabButtonActive:
    "!border-[color-mix(in_srgb,_var(--accent-cool)_52%,_var(--vui-border-subtle))] !bg-[color-mix(in_srgb,_var(--accent-cool)_8%,_var(--vui-surface-panel))] shadow-[0_0_0_2px_color-mix(in_srgb,_var(--accent-cool)_7%,_transparent)]",
  tabLayout:
    "grid w-full min-w-0 [grid-template-columns:28px_minmax(0,1fr)_auto] items-center gap-2",
  avatar:
    "grid size-7 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-surface-muted))] text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text-strong)]",
  tabCopy: "min-w-0",
  tabTitle: "block truncate text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  tabSubtitle: "mt-0.5 block truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  tabStatus:
    "self-start pt-0.5 text-[length:var(--vui-font-xs)] font-medium not-italic text-[var(--vui-text-muted)]",
  tabStatusActive: "text-[var(--accent-cool)]",
  sessionSurface:
    "flex min-h-[544px] flex-1 flex-col overflow-hidden rounded-[var(--vui-radius-lg)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] shadow-[0_5px_18px_color-mix(in_srgb,_var(--vui-text-strong)_4.5%,_transparent)]",
  selectedHeader:
    "flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-x-[18px] gap-y-2.5 border-b border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,_var(--vui-surface-row)_54%,_var(--vui-surface-panel))] px-[13px] py-[11px]",
  selectedIdentity: "flex min-w-0 flex-[1_1_270px] items-center gap-2.5",
  selectedAvatar:
    "grid size-8 shrink-0 place-items-center rounded-[var(--vui-radius-md)] bg-[color-mix(in_srgb,_var(--accent-cool)_16%,_var(--vui-surface-muted))] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  selectedCopy: "min-w-0",
  selectedTitleRow: "flex min-w-0 flex-wrap items-center gap-1.5",
  selectedTitle: "truncate text-[length:var(--vui-font-md)] font-semibold text-[var(--vui-text-strong)]",
  roleBadge:
    "rounded-full bg-[var(--vui-surface-muted)] px-1.5 py-0.5 text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text-muted)]",
  statusBadge:
    "rounded-full bg-[color-mix(in_srgb,_var(--accent-cool)_9%,_var(--vui-surface-muted))] px-1.5 py-0.5 text-[length:var(--vui-font-xs)] font-medium text-[var(--accent-cool)]",
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
    "flex shrink-0 items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2",
  conversationContract: "flex min-w-0 items-center gap-2",
  contractIcon:
    "grid size-6 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,_var(--accent-cool)_10%,_var(--vui-surface-muted))] text-[var(--accent-cool)]",
  contractCopy: "flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5",
  contractTitle:
    "text-[length:var(--vui-font-xs)] font-semibold text-[var(--vui-text-strong)]",
  contractMeta: "truncate text-[length:var(--vui-font-xs)] text-[var(--vui-text-muted)]",
  toolbarActions: "flex shrink-0 items-center gap-1.5",
  compactAction: "!h-7 !w-fit !min-w-0 !px-2 !text-[length:var(--vui-font-xs)]",
  sessionLink:
    "inline-flex h-7 w-fit items-center gap-1 rounded-[var(--vui-radius-sm)] border border-[var(--vui-border-subtle)] px-2 text-[length:var(--vui-font-xs)] font-medium text-[var(--vui-text)] transition hover:border-[var(--accent-cool)] hover:text-[var(--accent-cool)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-cool)]",
  body:
    "relative flex min-h-[430px] flex-1 overflow-hidden bg-[color-mix(in_srgb,_var(--vui-surface-chat)_92%,_var(--vui-surface-muted))]",
  conversation: "h-full min-h-[430px] w-full flex-1",
  loading:
    "grid h-full min-h-[430px] w-full place-items-center text-[length:var(--vui-font-sm)] text-[var(--vui-text-muted)]",
  empty:
    "m-auto flex w-[min(72%,_460px)] flex-col items-center gap-2 rounded-[var(--vui-radius-lg)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-8 py-7 text-center text-[length:var(--vui-font-sm)] leading-6 text-[var(--vui-text-muted)]",
  emptyAvatar:
    "grid size-10 place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-muted)] text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  emptyTitle: "text-[length:var(--vui-font-sm)] font-semibold text-[var(--vui-text-strong)]",
  queryNotice:
    "absolute inset-x-3 top-2 z-10 rounded-[var(--vui-radius-sm)] border border-[color-mix(in_srgb,_var(--vui-danger)_32%,_var(--vui-border-subtle))] bg-[color-mix(in_srgb,_var(--vui-danger)_7%,_var(--vui-surface-panel))] px-2 py-1 text-[length:var(--vui-font-xs)] text-[var(--vui-danger)]",
} as const;

export default styles;
