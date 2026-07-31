const styles = {
  actions:
    "min-w-0 flex flex-wrap items-center gap-1.5",
  allowButton:
    "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  body:
    "min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  commandPreview:
    "m-0 max-h-[7.5rem] min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] px-2 py-1.5 font-mono [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-primary)]",
  dialog:
    "min-w-0 !grid grid-cols-[34px_minmax(0,1fr)_auto] gap-2.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] p-2 text-[var(--accent-warm)] shadow-none",
  header:
    "min-w-0 flex flex-wrap items-center gap-1.5",
  icon:
    "min-w-0 shrink-0 text-[var(--accent-warm)]",
  grantDescription:
    "m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  overlay:
    "min-w-0",
  toolList:
    "min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  toolItem:
    "min-w-0 max-w-full break-words [overflow-wrap:anywhere]",
  visuallyHidden:
    "sr-only",
} as const;

export default styles;
