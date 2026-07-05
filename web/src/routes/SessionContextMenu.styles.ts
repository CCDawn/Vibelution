const styles = {
  sessionContextMenu:
    "vui-routes-chatcodingroute sessionContextMenu fixed z-[80] grid w-[188px] max-w-[calc(100vw-24px)] content-start gap-1 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_86%,transparent)] p-1 text-[var(--fg-primary)] shadow-none backdrop-blur-[4px]",
  sessionContextMenuDanger:
    "vui-routes-chatcodingroute sessionContextMenuDanger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  sessionContextMenuItem:
    "vui-routes-chatcodingroute sessionContextMenuItem min-w-0 !w-full justify-start rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5 text-left text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_[data-slot=vui-button-label]]:col-span-full",
} as const;

export default styles;
