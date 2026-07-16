const styles = {
  sidebar:
    "vui-routes-configsettingsnavigation sidebar grid h-full min-h-0 [width:clamp(15.5rem,17vw,18rem)] [grid-template-rows:auto_auto_minmax(0,1fr)] gap-4 overflow-hidden border border-vui-border-subtle bg-[color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] p-4",
  sidebarHeader: "vui-routes-configsettingsnavigation sidebarHeader grid min-w-0 gap-1",
  eyebrow:
    "vui-routes-configsettingsnavigation eyebrow m-0 text-[var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary",
  title: "vui-routes-configsettingsnavigation title m-0 text-lg font-extrabold text-vui-fg-primary",
  titleRow: "vui-routes-configsettingsnavigation titleRow flex min-w-0 items-center gap-1.5",
  status:
    "vui-routes-configsettingsnavigation status flex min-h-10 items-center justify-between gap-3 rounded-lg border border-vui-border-subtle bg-vui-surface-row px-3 text-[var(--vui-font-sm)] font-semibold text-vui-fg-secondary",
  statusValue: "vui-routes-configsettingsnavigation statusValue text-vui-fg-primary",
  groupNav: "vui-routes-configsettingsnavigation groupNav grid min-h-0 content-start gap-2 overflow-y-auto pr-1",
  groupButton:
    "vui-routes-configsettingsnavigation groupButton !grid min-h-11 !w-full !grid-cols-[minmax(0,1fr)] !justify-stretch rounded-lg px-3 text-left text-[var(--vui-font-sm)] font-bold",
  groupButtonActive:
    "vui-routes-configsettingsnavigation groupButtonActive border-[color-mix(in_srgb,var(--accent-cool)_44%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_13%,var(--vui-surface-row))] text-vui-fg-primary shadow-[inset_3px_0_0_var(--accent-warm-2)]",
  pageTabs:
    "vui-routes-configsettingsnavigation pageTabs flex min-w-0 items-center gap-2 overflow-x-auto border-b border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-toolbar)_80%,transparent)] px-4 py-2 [scrollbar-width:thin]",
  pageButton:
    "vui-routes-configsettingsnavigation pageButton min-h-10 shrink-0 px-4 text-[var(--vui-font-sm)] font-bold",
  pageButtonActive:
    "vui-routes-configsettingsnavigation pageButtonActive text-vui-fg-primary shadow-[inset_0_-2px_0_var(--accent-warm-2)]",
} as const;

export default styles;
