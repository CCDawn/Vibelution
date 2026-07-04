const styles = {
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  emptyDetail:
    "emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelEyebrow:
    "panelEyebrow min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  ragContextCard:
    "ragContextCard min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  ragContextList:
    "ragContextList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  ragContextMeta:
    "ragContextMeta min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  ragHealthStrip:
    "ragHealthStrip min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[repeat(auto-fit,minmax(108px,1fr))] gap-1.5",
  ragPolicyStrip:
    "ragPolicyStrip min-w-0 flex flex-wrap items-center gap-1.5",
  ragPreviewHeader:
    "ragPreviewHeader min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
  ragPreviewPanel:
    "ragPreviewPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
} as const;

export default styles;
