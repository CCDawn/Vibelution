const styles = {
  actions:
    "min-w-0 flex shrink-0 flex-wrap items-center justify-end gap-1.5 self-center",
  alwaysButton:
    "min-h-8 border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] px-2.5 text-[var(--fg-primary)]",
  body:
    "min-w-0 grid gap-1 [font-size:var(--vui-font-sm)] leading-snug text-[var(--fg-secondary)]",
  commandPreview:
    "m-0 max-h-[4.5rem] min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-workspace)] px-2 py-1 font-mono [font-size:11px] leading-snug text-[var(--fg-primary)]",
  dialog:
    "mx-auto min-w-0 w-full max-w-[min(40rem,100%)] !grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-strong)] bg-[var(--vui-surface-panel)] px-2.5 py-2 text-[var(--fg-primary)] shadow-[var(--vui-elevation-panel)]",
  header:
    "min-w-0 flex flex-wrap items-center gap-1.5 text-[var(--fg-primary)]",
  headerTitle:
    "text-[13px] font-semibold leading-tight text-[var(--fg-primary)]",
  hotkeys:
    "m-0 [font-size:10px] font-medium tracking-wide text-[var(--fg-tertiary)]",
  grantDescription:
    "m-0 [font-size:11px] leading-snug text-[var(--fg-tertiary)]",
  icon:
    "mt-0.5 min-w-0 shrink-0 text-[var(--state-warning)]",
  lead:
    "m-0 [font-size:12px] leading-snug text-[var(--fg-secondary)]",
  noButton:
    "min-h-8 border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2.5 text-[var(--fg-secondary)]",
  overlay:
    "min-w-0 w-full",
  overlayInline:
    "min-w-0 w-full",
  dialogInline:
    "min-w-0 w-full max-w-[min(40rem,100%)] !grid grid-cols-[28px_minmax(0,1fr)] items-start gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[var(--vui-border-strong)] bg-[var(--vui-surface-panel)] px-2.5 py-2 text-[var(--fg-primary)] shadow-[var(--vui-elevation-panel)] sm:grid-cols-[28px_minmax(0,1fr)_auto]",
  scopeBadge:
    "rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-px text-[10px] font-semibold text-[var(--fg-tertiary)]",
  toolList:
    "sr-only",
  toolItem:
    "min-w-0",
  yesButton:
    "min-h-8 border-[color-mix(in_srgb,var(--state-warning)_40%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_14%,var(--vui-surface-row))] px-2.5 font-semibold text-[var(--fg-primary)]",
  visuallyHidden:
    "sr-only",
} as const;

export default styles;
