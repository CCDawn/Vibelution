import {
  vuiRailFillClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const panelReset =
  "[&_[data-vui-product=agent-workspace-panel]]:h-full [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:shadow-none";

const styles = {
  workspace: `relative flex h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiWorkspaceFillClass} max-[860px]:flex-col max-[860px]:overflow-auto`,
  directory: `grid h-full min-h-0 min-w-0 shrink-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-r border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} max-[860px]:min-h-[320px] max-[860px]:w-full! max-[860px]:max-w-none! max-[860px]:border-b max-[860px]:border-r-0`,
  directoryFilter:
    "min-h-0 min-w-0 overflow-hidden border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [&_[data-vui-product=agent-workspace-panel]]:rounded-none [&_[data-vui-product=agent-workspace-panel]]:border-0 [&_[data-vui-product=agent-workspace-panel]]:p-2 [&_[data-vui-product=agent-workspace-panel]]:shadow-none",
  directoryList:
    `min-h-0 min-w-0 overflow-hidden ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-2`,
  main: `grid h-full min-h-0 min-w-0 flex-1 overflow-hidden ${vuiWorkspaceFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:!bg-[var(--vui-surface-workspace)] [&_[data-vui-product=agent-workspace-panel]]:p-3 max-[1280px]:[&_[data-vui-product=agent-workspace-panel]]:p-2`,
  inspector: `z-40 grid h-full min-h-0 min-w-0 shrink-0 overflow-hidden border-l border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiRailFillClass} ${panelReset} [&_[data-vui-product=agent-workspace-panel]]:p-0 max-[1180px]:absolute max-[1180px]:inset-y-0 max-[1180px]:right-0 max-[1180px]:w-[min(360px,calc(100%-24px))]! max-[1180px]:max-w-[calc(100%-24px)] max-[1180px]:shadow-[-18px_0_40px_rgba(0,0,0,0.18)]`,
  inspectorBackdrop:
    "pointer-events-none absolute inset-0 z-30 hidden border-0 bg-black/20 opacity-0 max-[1180px]:block max-[1180px]:pointer-events-auto max-[1180px]:opacity-100",
  // Wave 4B: PaneResizeHandle owns the visual rule; only placement overrides stay here.
  inspectorResizeHandle: "max-[1180px]:hidden",
  workspaceWithInspector:
    "flex h-full min-h-0 w-full min-w-0 overflow-hidden border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)]",
} as const;

export default styles;
