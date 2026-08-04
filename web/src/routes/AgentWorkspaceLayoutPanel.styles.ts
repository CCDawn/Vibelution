import {
  vuiRailFillClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const panelReset =
  "[&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:shadow-none";

const styles = {
  shellHost: "relative grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)] overflow-hidden",
  hiddenHeader: "hidden",
  // Recipe owns resize (layoutId); keep fill/overflow + mobile stack only.
  workspace: `relative h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiWorkspaceFillClass} max-[860px]:overflow-auto`,
  directory: `grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-r border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} max-[860px]:min-h-[320px]`,
  directoryFilter:
    "min-h-0 min-w-0 overflow-hidden border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:p-2 [&_[data-vui-product=agent-workspace-panel]]:shadow-none",
  directoryList:
    `min-h-0 min-w-0 overflow-hidden ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-2`,
  main: `grid h-full min-h-0 min-w-0 overflow-hidden ${vuiWorkspaceFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:!bg-[var(--vui-surface-workspace)] [&_[data-vui-product=agent-workspace-panel]]:p-3 max-[1280px]:[&_[data-vui-product=agent-workspace-panel]]:p-2`,
  inspector: `grid h-full min-h-0 min-w-0 overflow-hidden border-l border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-0 max-[1180px]:shadow-[-18px_0_40px_rgba(0,0,0,0.18)]`,
  inspectorBackdrop:
    "pointer-events-none absolute inset-0 z-30 hidden border-0 bg-black/20 opacity-0 max-[1180px]:block max-[1180px]:pointer-events-auto max-[1180px]:opacity-100",
  // Placement-only residual for layout gate compatibility.
  inspectorResizeHandle: "max-[1180px]:hidden",
  workspaceWithInspector:
    "flex h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)]",
} as const;

export default styles;
