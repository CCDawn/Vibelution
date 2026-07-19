const styles = {
  copyNotice:
    "copyNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  editPreviewGrid:
    "editPreviewGrid min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  editPreviewPanel:
    "editPreviewPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  managementActions:
    "managementActions min-w-0 flex flex-wrap items-center gap-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  primaryActionButton:
    "primaryActionButton min-w-0 flex flex-wrap items-center gap-1.5 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
} as const;

export default styles;
