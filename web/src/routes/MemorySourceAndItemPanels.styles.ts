import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  filterButton:
    "filterButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  filterButtonActive:
    `filterButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  filterGroup:
    "filterGroup min-w-0",
  itemPanel: `itemPanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center gap-1.5 px-1 py-0.5",
  panelNotice: `panelNotice min-w-0 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5 ${vuiOpaqueRowClass} p-2 [font-size:var(--vui-font-xs)] [&_span]:min-w-0 [&_span]:break-words`,
  searchBox: `searchBox min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  sourceButton: `sourceButton min-w-0 w-full max-w-full ${vuiOpaqueRowClass} text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 !grid grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-2 min-h-10 px-[7px] py-[5px] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents`,
  sourceButtonActive:
    `sourceButtonActive min-w-0 ${vuiStateSelectedRowClass}`,
  sourceCopy:
    "sourceCopy min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_strong]:block [&_strong]:min-w-0 [&_strong]:truncate [&_span]:block [&_span]:min-w-0 [&_span]:truncate",
  sourceIcon:
    "sourceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  sourceList:
    "sourceList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  sourcePanel: `sourcePanel min-w-0 min-h-0 overflow-auto ${vuiFlatPanelClass} p-2`,
  sourceStats:
    "sourceStats min-w-0 text-right tabular-nums",
} as const;

export default styles;
