const styles = {
  actions:
    "min-w-0 flex shrink-0 flex-nowrap items-center justify-end gap-1 self-center",
  alwaysButton:
    "!h-7 !min-h-7 border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] !px-2 !text-[11px] text-[var(--fg-primary)]",
  body:
    "min-w-0 grid gap-0.5 [font-size:var(--vui-font-sm)] leading-snug text-[var(--fg-secondary)]",
  commandPreview:
    "m-0 max-h-[2.6rem] min-w-0 overflow-hidden text-ellipsis whitespace-pre-wrap break-words rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-workspace)] px-2 py-1 font-mono [font-size:11px] leading-snug text-[var(--fg-primary)] [display:-webkit-box] [-webkit-line-clamp:2] [-webkit-box-orient:vertical]",
  dialog:
    "mx-auto min-w-0 w-full max-w-[min(44rem,100%)] !grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5 rounded-[var(--radius-control)] border border-[var(--vui-border-strong)] bg-[var(--vui-surface-panel)] px-2 py-1.5 text-[var(--fg-primary)] shadow-[var(--vui-shadow-hairline)]",
  header:
    "min-w-0 flex flex-wrap items-center gap-1 text-[var(--fg-primary)]",
  headerTitle:
    "text-[12px] font-semibold leading-none text-[var(--fg-primary)]",
  hotkeys:
    "m-0 [font-size:10px] font-medium leading-none tracking-wide text-[var(--fg-tertiary)]",
  grantDescription:
    "m-0 line-clamp-2 [font-size:10px] leading-snug text-[var(--fg-tertiary)]",
  icon:
    "min-w-0 shrink-0 self-center text-[var(--state-warning)]",
  lead:
    "m-0 [font-size:11px] leading-snug text-[var(--fg-tertiary)]",
  noButton:
    "!h-7 !min-h-7 border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] !px-2 !text-[11px] text-[var(--fg-secondary)]",
  overlay:
    "min-w-0 w-full",
  overlayInline:
    "min-w-0 w-full",
  dialogInline:
    "min-w-0 w-full max-w-[min(44rem,100%)] !grid grid-cols-[22px_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 rounded-[var(--radius-control)] border border-[var(--vui-border-strong)] bg-[var(--vui-surface-panel)] px-2 py-1.5 text-[var(--fg-primary)] shadow-[var(--vui-shadow-hairline)] sm:grid-cols-[22px_minmax(0,1fr)_auto]",
  scopeBadge:
    "rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-px text-[10px] font-semibold leading-none text-[var(--fg-tertiary)]",
  toolList:
    "sr-only",
  toolItem:
    "min-w-0",
  yesButton:
    "!h-7 !min-h-7 border-[color-mix(in_srgb,var(--state-warning)_40%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_14%,var(--vui-surface-row))] !px-2 !text-[11px] font-semibold text-[var(--fg-primary)]",
  visuallyHidden:
    "sr-only",
} as const;

export default styles;
