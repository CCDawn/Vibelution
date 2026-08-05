const styles = {
  sourceCollectionRunSwitcher:
    "sourceCollectionRunSwitcher min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[7px] border border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] bg-[color:var(--source-workbench-panel)] px-2 py-1.5 max-[980px]:grid-cols-[1fr]",
  sourceCollectionRunSwitcherMain:
    "sourceCollectionRunSwitcherMain min-w-0 grid min-w-0 grid-cols-[max-content_minmax(220px,360px)] items-center gap-2 [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-secondary)] max-[900px]:grid-cols-[1fr]",
  sourceCollectionRunSwitcherStats:
    "sourceCollectionRunSwitcherStats min-w-0 flex flex-wrap items-center justify-end gap-1.5 [font-size:var(--vui-font-xs)] [&_span]:inline-flex [&_span]:min-h-[26px] [&_span]:items-center [&_span]:gap-1.5 [&_span]:whitespace-nowrap [&_span]:rounded-[7px] [&_span]:border [&_span]:border-[color:var(--border-soft)] [&_span]:bg-[color:var(--source-workbench-card)] [&_span]:px-2 [&_span]:font-[720] [&_strong]:text-[var(--fg-primary)]",
} as const;

export default styles;
