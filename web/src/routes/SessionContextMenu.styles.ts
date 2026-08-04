const styles = {
  sessionContextMenu:
    "vui-routes-chatcodingroute sessionContextMenu z-[80] w-[188px] max-w-[calc(100vw-24px)] rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_86%,transparent)] shadow-none backdrop-blur-[4px]",
  sessionContextMenuDanger:
    "vui-routes-chatcodingroute sessionContextMenuDanger min-w-0 !border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] !bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] !text-[var(--state-error)]",
  sessionContextMenuItem:
    "vui-routes-chatcodingroute sessionContextMenuItem min-w-0 !w-full justify-start",
} as const;

export default styles;
