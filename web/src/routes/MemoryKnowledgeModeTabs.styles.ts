const styles = {
  knowledgeModeTabs:
    "knowledgeModeTabs min-w-0 max-w-full overflow-x-hidden flex flex-wrap items-center justify-start gap-1.5 max-[640px]:grid max-[640px]:grid-cols-[repeat(auto-fit,minmax(min(100%,8.5rem),1fr))]",
  knowledgeModeTab:
    "knowledgeModeTab shrink-0 min-w-0 max-w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-h-[28px] rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 text-left text-[var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] cursor-pointer hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 max-[640px]:w-full [&_span]:min-w-0 [&_span]:truncate [&_strong]:tabular-nums",
  knowledgeModeTabActive:
    "knowledgeModeTabActive shrink-0 min-w-0 max-w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-h-[28px] rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] px-1.5 text-left text-[var(--vui-font-xs)] font-semibold text-[var(--accent-cool)] cursor-pointer max-[640px]:w-full [&_span]:min-w-0 [&_span]:truncate [&_strong]:tabular-nums",
} as const;

export default styles;
