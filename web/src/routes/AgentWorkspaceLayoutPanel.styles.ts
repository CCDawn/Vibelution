import {
  vuiRailFillClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const panelReset =
  "[&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:shadow-none";

const styles = {
  shellHost: "relative grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)] overflow-hidden",
  hiddenHeader: "hidden",
  // Recipe owns resize (layoutId). Narrow screens use route-owned master/detail switching.
  workspace: `relative h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiWorkspaceFillClass} max-[1180px]:[&>[data-vui=split-aside]]:!absolute max-[1180px]:[&>[data-vui=split-aside]]:inset-y-0 max-[1180px]:[&>[data-vui=split-aside]]:right-0 max-[1180px]:[&>[data-vui=split-aside]]:z-40 max-[680px]:[&>[data-vui=split-aside]]:!w-full max-[680px]:[&>[data-vui=split-aside]]:!min-w-0 max-[680px]:[&>[data-vui=split-aside]]:!max-w-[360px] max-[680px]:[&>[data-vui=split-aside]]:!basis-auto`,
  workspaceNarrowDirectory:
    "max-[680px]:[&>[data-vui=split-sidebar]]:!flex max-[680px]:[&>[data-vui=split-sidebar]]:!w-full max-[680px]:[&>[data-vui=split-sidebar]]:!min-w-0 max-[680px]:[&>[data-vui=split-sidebar]]:!max-w-none max-[680px]:[&>[data-vui=split-sidebar]]:!basis-full max-[680px]:[&>[data-vui=split-main]]:!hidden max-[680px]:[&>[role=separator]]:!hidden",
  workspaceNarrowDetail:
    "max-[680px]:[&>[data-vui=split-sidebar]]:!hidden max-[680px]:[&>[data-vui=split-main]]:!flex max-[680px]:[&>[data-vui=split-main]]:!w-full max-[680px]:[&>[role=separator]]:!hidden",
  directory: `grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-r border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} max-[860px]:min-h-[320px]`,
  directoryFilter:
    "min-h-0 min-w-0 overflow-hidden border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:p-2 [&_[data-vui-product=agent-workspace-panel]]:shadow-none",
  directoryList:
    `min-h-0 min-w-0 overflow-hidden ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-2`,
  main: `grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${vuiWorkspaceFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:!bg-[var(--vui-surface-workspace)] [&_[data-vui-product=agent-workspace-panel]]:p-3 max-[1280px]:[&_[data-vui-product=agent-workspace-panel]]:p-2`,
  narrowDetailBar:
    "hidden min-w-0 items-center border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] bg-[var(--vui-surface-workspace)] px-2 py-1.5 max-[680px]:flex",
  inspector: `grid h-full min-h-0 min-w-0 overflow-hidden border-l border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-0 max-[1180px]:shadow-[-18px_0_40px_rgba(0,0,0,0.18)]`,
  inspectorBackdrop:
    "pointer-events-none absolute inset-0 z-30 hidden border-0 bg-black/20 opacity-0 max-[1180px]:block max-[1180px]:pointer-events-auto max-[1180px]:opacity-100",
  // Placement-only residual for layout gate compatibility.
  inspectorResizeHandle: "max-[1180px]:hidden",
  workspaceWithInspector:
    "flex h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)]",
} as const;

export default styles;
