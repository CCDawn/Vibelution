const styles = {
  fieldStack:
    "fieldStack min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  iconButton:
    "iconButton inline-flex min-h-[var(--vui-control-height-sm)] min-w-0 w-fit max-w-full shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-[var(--vui-control-muted)] px-2 py-1 text-vui-xs text-vui-fg-secondary hover:bg-[var(--vui-control-hover-bg)]",
  managementHeader:
    "managementHeader flex min-w-0 flex-wrap items-center justify-between gap-2 [&_h2]:text-vui-xs [&_h2]:font-medium",
  managementPanel:
    "managementPanel grid min-h-0 min-w-0 content-start gap-3 bg-transparent py-1 text-vui-micro-13",
  panelEyebrow:
    "panelEyebrow min-w-0 text-vui-2xs font-normal leading-relaxed text-vui-fg-tertiary",
} as const;

export default styles;
