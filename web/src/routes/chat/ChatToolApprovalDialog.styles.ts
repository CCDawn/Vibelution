const styles = {
  actions:
    "min-w-0 flex flex-wrap items-center gap-1.5",
  alwaysButton:
    "border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--fg-primary)]",
  body:
    "min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  commandPreview:
    "m-0 max-h-[7.5rem] min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] px-2 py-1.5 font-mono [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-primary)]",
  dialog:
    "min-w-0 !grid grid-cols-[34px_minmax(0,1fr)_auto] gap-2.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,var(--vui-surface-panel))] p-2 text-[var(--accent-warm)] shadow-none",
  header:
    "min-w-0 flex flex-wrap items-center gap-1.5",
  hotkeys:
    "m-0 [font-size:10px] font-semibold tracking-wide text-[var(--fg-tertiary)]",
  grantDescription:
    "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  icon:
    "min-w-0 shrink-0 text-[var(--accent-warm)]",
  lead:
    "m-0",
  noButton:
    "border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)]",
  overlay:
    "min-w-0 w-full",
  overlayInline:
    "min-w-0 w-full",
  dialogInline:
    "min-w-0 !grid grid-cols-[34px_minmax(0,1fr)] gap-2 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-warm)_32%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,var(--vui-surface-panel))] p-2 text-[var(--accent-warm)] shadow-none sm:grid-cols-[34px_minmax(0,1fr)_auto]",
  scopeBadge:
    "rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-px text-[10px] font-semibold text-[var(--fg-tertiary)]",
  toolList:
    "min-w-0 flex min-h-0 flex-wrap content-start gap-1.5 overflow-auto",
  toolItem:
    "min-w-0 max-w-full break-words [overflow-wrap:anywhere] rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_20%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] px-1.5 py-0.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-primary)]",
  yesButton:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] font-extrabold text-[var(--accent-warm)]",
  visuallyHidden:
    "sr-only",
} as const;

export default styles;
