const styles = {
  knowledgeModeTabs:
    "knowledgeModeTabs min-w-0 max-w-full overflow-x-hidden flex flex-wrap items-center justify-start gap-1.5 max-[640px]:grid max-[640px]:grid-cols-[repeat(2,minmax(0,1fr))]",
  knowledgeModeTab:
    "knowledgeModeTab shrink-0 max-w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-w-0 min-h-[28px] px-1.5 rounded-[7px] border border-[var(--border-soft)] bg-[color:color-mix(in_srgb,var(--surface-panel)_88%,transparent)] text-[var(--fg-secondary)] text-left cursor-pointer hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 [&_span]:min-w-0 [&_span]:truncate",
  knowledgeModeTabActive:
    "knowledgeModeTabActive shrink-0 max-w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-w-0 min-h-[28px] px-1.5 rounded-[7px] border border-[color:color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] bg-[color:color-mix(in_srgb,var(--accent-cool)_12%,var(--surface-panel))] text-[var(--fg-primary)] text-left cursor-pointer [&_span]:min-w-0 [&_span]:truncate",
} as const;

export default styles;
