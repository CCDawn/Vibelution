const styles = {
  controlStrip:
    "grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-center gap-[7px] rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--border-soft)_62%,transparent)] bg-[color:color-mix(in_srgb,var(--surface-panel)_42%,transparent)] p-2 max-[980px]:grid-cols-[1fr]",
  managementNav:
    "!mx-0 !mt-0 min-w-0 self-start max-[980px]:w-full",
  summaryGrid:
    "grid min-w-0 grid-cols-[repeat(3,minmax(0,1fr))] gap-[5px] max-[720px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[520px]:grid-cols-[1fr]",
  summaryCard:
    "grid min-w-0 gap-[2px] rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--border-soft)_58%,transparent)] bg-[color:color-mix(in_srgb,var(--surface-panel)_38%,transparent)] px-2 py-1.5 [&>span]:truncate [&>span]:text-[var(--vui-font-xs)] [&>span]:font-semibold [&>span]:text-vui-fg-tertiary [&>strong]:truncate [&>strong]:text-[var(--vui-font-md)] [&>strong]:font-extrabold [&>strong]:leading-tight [&>strong]:text-vui-fg-primary",
  agentScopeBar:
    "grid min-w-0 grid-cols-[minmax(170px,1fr)_minmax(180px,230px)_minmax(150px,190px)_minmax(180px,auto)] items-center gap-[7px] rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--accent-cool)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,transparent)] p-2 max-[1120px]:grid-cols-[minmax(0,1fr)_minmax(180px,230px)] max-[700px]:grid-cols-[1fr]",
  scopeCopy:
    "grid min-w-0 gap-[2px] [&>strong]:truncate [&>strong]:text-[var(--vui-font-sm)] [&>strong]:font-extrabold [&>strong]:text-vui-fg-primary [&>span]:truncate [&>span]:text-[var(--vui-font-xs)] [&>span]:font-semibold [&>span]:text-vui-fg-tertiary",
  panelEyebrow:
    "m-0 truncate text-[var(--vui-font-xs)] font-bold uppercase tracking-[0.06em] text-vui-fg-tertiary",
  scopeSelect:
    "grid min-w-0 gap-[3px] text-[var(--vui-font-xs)] font-semibold text-vui-fg-tertiary [&_[data-vui=native-select]]:w-full",
  scopeStats:
    "flex min-w-0 flex-wrap items-center justify-end gap-1.5 text-[var(--vui-font-xs)] font-semibold text-vui-fg-tertiary max-[700px]:justify-start [&>span]:inline-grid [&>span]:min-h-7 [&>span]:grid-cols-[auto_auto] [&>span]:items-center [&>span]:gap-1 [&>span]:rounded-[var(--radius-control)] [&>span]:border [&>span]:border-[color:color-mix(in_srgb,var(--border-soft)_58%,transparent)] [&>span]:bg-[color:color-mix(in_srgb,var(--surface-panel)_38%,transparent)] [&>span]:px-2 [&_strong]:text-vui-fg-primary",
  deepLinkNotice:
    "col-span-full m-0 min-w-0 rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_9%,transparent)] px-2 py-1.5 text-[var(--vui-font-xs)] font-semibold leading-[var(--vui-line-readable)] text-vui-accent-cool",
} as const;

export default styles;
