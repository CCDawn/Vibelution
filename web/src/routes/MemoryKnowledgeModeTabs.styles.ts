const styles = {
  knowledgeModeTabs:
    "knowledgeModeTabs min-w-0 grid grid-cols-[repeat(5,minmax(0,1fr))]",
  knowledgeModeTab:
    "knowledgeModeTab min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-w-0 min-h-[28px] px-1.5 rounded-[7px] border border-[var(--border-soft)] bg-[color:color-mix(in_srgb,var(--surface-panel)_88%,transparent)] text-[var(--fg-secondary)] text-left cursor-pointer [&_span]:min-w-0 [&_span]:truncate",
  knowledgeModeTabActive:
    "knowledgeModeTabActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-w-0 min-h-[28px] px-1.5 rounded-[7px] border border-[color:color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] bg-[color:color-mix(in_srgb,var(--accent-cool)_12%,var(--surface-panel))] text-[var(--fg-primary)] text-left cursor-pointer [&_span]:min-w-0 [&_span]:truncate",
} as const;

export default styles;
