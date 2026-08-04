import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    `countPill min-w-0 ${vuiControlPillClass}`,
  graphCanvasFallback:
    "graphCanvasFallback min-w-0 grid min-h-0 gap-2 p-2",
  graphCanvasPanel:
    "graphCanvasPanel grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto_var(--memory-graph-node-list-height,168px)] gap-0 overflow-hidden",
  graphCanvasToolbar:
    "graphCanvasToolbar min-w-0 flex flex-wrap items-center justify-between gap-1.5 px-1 py-0.5 [&>div]:min-w-0 [&_strong]:break-words",
  graphClearFocusButton:
    `graphClearFocusButton min-w-0 ${vuiControlQuietClass}`,
  graphInteractionHint:
    "graphInteractionHint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  // Wave 6B: PaneHeightResizeHandle owns row-resize visual; placement only.
  graphNodeListResizeHandle:
    "graphNodeListResizeHandle",
  graphNodeList:
    "graphNodeList min-w-0 grid h-full min-h-0 content-start gap-1.5 overflow-auto pt-1 [&_[data-vui=\"button\"]]:w-full",
  graphNodeTypeMark:
    "graphNodeTypeMark min-w-0",
  graphTypeList:
    "graphTypeList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_button]:w-full [&_[data-active=true]]:border-[var(--accent-cool)]",
  graphWorkspace:
    "graphWorkspace min-w-0 grid h-full min-h-0 gap-0 overflow-hidden",
  graphMetricToolbar:
    "graphMetricToolbar min-w-0 shrink-0 border-0 bg-transparent px-0 py-0",
  graphCanvasInner:
    "graphCanvasInner grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto_var(--memory-graph-node-list-height,168px)] gap-0 overflow-hidden",
  graphInspectorHost:
    "graphInspectorHost min-h-0 min-w-0 overflow-hidden border-0 bg-transparent shadow-none",
  graphInspectorInner:
    "graphInspectorInner grid h-full min-h-0 min-w-0 overflow-hidden",
  itemButton: `itemButton min-w-0 w-full max-w-full ${vuiOpaqueRowClass} p-2 text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5 [&_strong]:min-w-0 [&_strong]:truncate [&_small]:min-w-0 [&_small]:truncate`,
  itemButtonActive: `itemButtonActive min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateSelectedRowClass}`,
  managementPanel:
    "managementPanel gap-1.5 border-t border-[var(--vui-border-hairline)] pt-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  searchBox: `searchBox min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  sourcePanel:
    "sourcePanel min-h-0 overflow-hidden border-0 bg-transparent shadow-none",
  sourcePanelInner:
    "sourcePanelInner grid h-full min-h-0 content-start gap-1.5 overflow-auto p-1.5",
  workspace:
    `workspace min-w-0 grid h-full min-h-0 flex-1 gap-0 overflow-hidden ${vuiWorkspaceFillClass}`,
} as const;

export default styles;
