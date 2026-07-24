import { vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  sessionContextMenu: "vui-routes-chatcodingroute sessionContextMenu fixed z-[80] grid w-[188px] max-w-[calc(100vw-24px)] content-start gap-1 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_86%,transparent)] p-1 text-[var(--fg-primary)] shadow-none backdrop-blur-[4px]",
  sessionContextMenuDanger:
    "vui-routes-chatcodingroute sessionContextMenuDanger min-w-0 !border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] !bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] !text-[var(--state-error)]",
  sessionContextMenuItem: `vui-routes-chatcodingroute sessionContextMenuItem min-w-0 !w-full justify-start ${vuiOpaqueRowClass} px-2 py-1.5 text-left text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:grid [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-content]]:grid-cols-[auto_minmax(0,1fr)] [&_[data-slot=vui-button-content]]:items-center [&_[data-slot=vui-button-content]]:justify-start [&_[data-slot=vui-button-icon]]:self-center [&_[data-slot=vui-button-label]]:block [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate [&_[data-slot=vui-button-label]]:text-left`,
} as const;

export default styles;
