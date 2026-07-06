const styles = {
  stack:
    "min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] p-2 shadow-none",
  list:
    "min-w-0 space-y-2",
  notice:
    "min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_54%,transparent)] p-2 shadow-none !grid grid-cols-[16px_minmax(0,1fr)] items-start gap-[7px]",
  body:
    "min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  label:
    "block text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  message:
    "block min-w-0 break-words text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  toneError:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  toneInfo:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  toneMuted:
    "bg-[color-mix(in_srgb,var(--vui-surface-panel)_58%,transparent)] text-[var(--fg-tertiary)]",
  toneSuccess:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  toneTool:
    "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  toneWarning:
    "border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]",
} as const;

export default styles;
