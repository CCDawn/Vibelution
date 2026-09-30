import { vuiControlQuietClass } from "../design/vuiChromeRecipes";

const styles = {
  railTitle: "mt-2 text-base font-medium",
  typeCount: "text-xs text-[var(--fg-tertiary)]",
  searchResults: "grid gap-1",
  searchResult: "justify-start text-left",
  accessNote: "mt-auto pt-6 text-xs leading-relaxed text-[var(--fg-tertiary)]",
  canvasTitle: "mt-2 text-xl font-medium",
  canvasHint: "mt-2 text-xs text-[var(--fg-secondary)]",
  viewModes: "flex items-center gap-1",
  selectedTitle: "max-w-48 truncate",
  refreshError: "px-6 text-xs text-[var(--fg-secondary)]",

  atlasRail: "!border-r !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-rail)]",
  atlasRailInner: "flex h-full min-h-0 flex-col gap-6 overflow-auto px-4 py-6",
  atlasEyebrow: "text-xs tracking-wide text-[var(--fg-tertiary)]",
  atlasSearch: "flex min-w-0 items-center gap-2 rounded-md border border-[var(--vui-border-subtle)] px-2 py-1 text-[var(--fg-secondary)] [&_input]:min-w-0 [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:text-sm",
  atlasFilters: "mt-3 grid gap-1 [&_button]:w-full [&_button]:justify-between [&_button]:gap-3 [&_button]:!border-transparent [&_[data-active=true]]:bg-[var(--vui-control-hover-bg)]",
  atlasCanvas: "!bg-[var(--vui-surface-workspace)]",
  atlasMain: "flex h-full min-h-0 min-w-0 flex-col",
  atlasHeading: "flex shrink-0 flex-wrap items-center justify-between gap-4 px-6 pb-4 pt-6",
  atlasStage: "relative min-h-48 min-w-0 flex-1 overflow-hidden",
  atlasContext: "pointer-events-none absolute inset-x-4 top-3 z-20 flex flex-wrap items-start justify-between gap-2",
  atlasActionRow: "pointer-events-auto flex max-w-full flex-wrap items-center gap-2 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1.5 text-xs text-[var(--fg-secondary)] shadow-sm",
  atlasTools: "absolute bottom-3 left-5 z-20 flex items-center gap-1 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1",
  atlasFooter: "flex shrink-0 flex-wrap justify-between gap-2 px-6 py-3 text-xs text-[var(--fg-tertiary)]",
  atlasEmpty: "grid h-full min-h-48 place-content-center justify-items-center gap-3 px-6 text-center text-sm text-[var(--fg-secondary)]",
  atlasNodeList: "grid h-[var(--pane-h-graph-node-list,168px)] shrink-0 grid-cols-1 gap-1 overflow-auto border-t border-[var(--vui-border-subtle)] px-4 py-2 sm:grid-cols-2 [&_button]:justify-start",
  // Wave 6B: PaneHeightResizeHandle owns row-resize visual; placement only.
  graphNodeListResizeHandle: "graphNodeListResizeHandle",
  atlasInspectorHost: "!border-l !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)]",
  atlasInspector: "flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
  atlasDetailHeader: "flex shrink-0 items-center justify-between border-b border-[var(--vui-border-subtle)] px-5 py-3 text-xs text-[var(--fg-secondary)]",
  graphWorkspace: "min-w-0 h-full min-h-0 overflow-hidden",
  graphClearFocusButton: vuiControlQuietClass,
} as const;

export default styles;
