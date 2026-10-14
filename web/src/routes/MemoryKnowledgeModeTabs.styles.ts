const styles = {
  knowledgeModeTabs:
    "knowledgeModeTabs min-w-0 max-w-full !flex !flex-nowrap items-center justify-start gap-1.5 !overflow-x-auto !overflow-y-hidden !border-0 !bg-transparent !p-0 !rounded-none",
  // Base + active via Radix data-state on VTabs trigger (tailwind-merge wins over VTabs defaults).
  knowledgeModeTab: [
    "knowledgeModeTab !shrink-0 min-w-0 max-w-full !inline-flex !w-auto items-center gap-1.5",
    "min-h-[28px] rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)]",
    "bg-[var(--vui-control-muted)] !px-1.5 text-left [font-size:var(--vui-font-xs)] font-medium",
    "text-[var(--fg-secondary)] cursor-pointer",
    "hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)]",
    "disabled:cursor-default disabled:opacity-55 max-[640px]:!min-h-11",
    "[&_span]:min-w-0 [&_span]:truncate [&_strong]:tabular-nums",
    "data-[state=active]:border-vui-border-subtle",
    "data-[state=active]:bg-vui-surface-chat",
    "data-[state=active]:text-vui-fg-primary",
    "data-[state=active]:shadow-none",
  ].join(" "),
  // Legacy token retained for style contracts that still assert the active class name exists.
  knowledgeModeTabActive:
    "knowledgeModeTabActive shrink-0 min-w-0 max-w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 min-h-[28px] rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-chat px-1.5 text-left [font-size:var(--vui-font-xs)] font-medium text-vui-fg-primary cursor-pointer max-[640px]:w-full [&_span]:min-w-0 [&_span]:truncate [&_strong]:tabular-nums",
} as const;

export default styles;
