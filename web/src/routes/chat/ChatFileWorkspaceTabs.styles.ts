const styles = {
  fileTab:
    "vui-routes-chatfileworkspacetabs fileTab min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-[min(100%,18rem)] items-center justify-center gap-1.5 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  fileTabActive:
    "vui-routes-chatfileworkspacetabs fileTabActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  fileTabButton:
    "vui-routes-chatfileworkspacetabs fileTabButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 overflow-hidden truncate rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:truncate",
  fileTabClose:
    "vui-routes-chatfileworkspacetabs fileTabClose min-w-0 size-[var(--vui-control-height-xs)] shrink-0",
} as const;

export default styles;
