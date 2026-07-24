import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  root: `root min-w-0 ${vuiFlatPanelClass} p-2 grid min-h-0 content-start gap-2`,
  toolbar:
    "toolbar min-w-0 grid gap-2 lg:grid-cols-[minmax(0,0.96fr)_minmax(0,1.04fr)]",
  formRow:
    "formRow min-w-0 grid gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] md:grid-cols-[minmax(0,1.15fr)_minmax(12rem,0.85fr)_auto] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  list:
    "list min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  selectedPage: `selectedPage min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiOpaqueRowClass} p-2`,
  resultList:
    "resultList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  badge:
    "badge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  error:
    "error min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-danger)_32%,transparent)] bg-[color-mix(in_srgb,var(--accent-danger)_10%,var(--vui-surface-row))] p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--accent-danger)]",
  emptyState:
    "emptyState min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  header:
    "header min-w-0 flex flex-wrap items-center justify-between gap-2",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  body:
    "body min-w-0 grid gap-2 xl:grid-cols-[minmax(17rem,0.82fr)_minmax(17rem,0.82fr)_minmax(0,1.36fr)]",
  panel: `panel min-w-0 grid min-h-[14rem] content-start gap-1.5 ${vuiOpaqueRowClass} p-2`,
  panelHeader:
    "panelHeader min-w-0 flex flex-wrap items-center justify-between gap-1.5",
  listButton:
    "listButton min-w-0 grid w-full gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-transparent p-2 text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted)]",
  listButtonActive:
    `listButtonActive ${vuiStateSelectedRowClass} text-[var(--fg-primary)]`,
  actionRow:
    "actionRow min-w-0 flex flex-wrap items-center gap-1.5",
  meta:
    "meta min-w-0 max-w-full [overflow-wrap:anywhere] break-all [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  metaWrap:
    "metaWrap min-w-0 max-w-full [overflow-wrap:anywhere] break-all [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  code:
    "code block max-h-24 overflow-auto whitespace-pre-wrap break-all rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-overlay)_88%,black)] px-2 py-1 font-mono text-[11px] leading-relaxed text-[var(--fg-primary)]",
  pre:
    "pre min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-overlay)_88%,black)] px-2 py-2 font-mono text-[11px] leading-relaxed text-[var(--fg-primary)]",
  previewList:
    "previewList min-w-0 grid max-h-28 content-start gap-1 overflow-auto [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
} as const;

export default styles;
