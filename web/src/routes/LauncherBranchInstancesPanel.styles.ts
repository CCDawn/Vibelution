import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";
const tableGrid =
  "grid-cols-[28px_minmax(110px,1fr)_minmax(72px,0.55fr)_minmax(110px,0.8fr)_minmax(56px,0.4fr)_minmax(0,1.2fr)_auto]";
const tableGrid860 =
  "max-[860px]:grid-cols-[28px_minmax(110px,1fr)_minmax(72px,0.5fr)_minmax(110px,0.8fr)_minmax(0,1fr)_auto] max-[860px]:[&>span:nth-child(5)]:hidden";
const tableGrid620 =
  "max-[620px]:grid-cols-[28px_minmax(0,1fr)_auto] max-[620px]:[&>span:nth-child(n+3):nth-child(-n+6)]:hidden";

const styles = {
  panel: `mx-2 mt-1.5 block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  panelHeader:
    "flex min-h-0 min-w-0 items-baseline justify-between gap-2.5 border-b border-[var(--border-soft)] pb-1.5 [&>*]:min-w-0 [&_strong]:flex-auto [&_strong]:truncate [&_strong]:text-right [&_strong]:text-[var(--fg-primary)]",
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  toolbar:
    "mt-1.5 flex min-w-0 flex-wrap items-center justify-between gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  toolbarActions: "flex min-w-0 flex-wrap items-center gap-1.5",
  pager: "inline-flex min-w-0 items-center gap-1.5",
  rangeLabel: "min-w-0 truncate text-[var(--fg-muted)]",
  notice: "min-w-0 flex-auto truncate text-[var(--fg-secondary)]",
  noticeError: "min-w-0 flex-auto truncate text-[var(--state-error)]",
  statusTable: `mt-1.5 grid min-w-0 overflow-hidden ${rowSurfaceMuted}`,
  statusHead:
    `grid min-w-0 ${tableGrid} items-center gap-[7px] border-b border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)] ${tableGrid860} ${tableGrid620}`,
  statusRow:
    `grid min-w-0 cursor-pointer ${tableGrid} items-center gap-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_74%,var(--vui-surface-row))] px-2 py-1.5 text-left [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] first:border-t-0 data-[tone=success]:border-l-2 data-[tone=success]:border-l-[var(--state-success)] data-[tone=warning]:border-l-2 data-[tone=warning]:border-l-[var(--state-warning)] data-[selected=true]:bg-[color-mix(in_srgb,var(--vui-accent)_14%,var(--vui-surface-row))] ${tableGrid860} ${tableGrid620} [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--fg-primary)] [&>span:first-child]:overflow-visible [&>span:last-child]:overflow-visible`,
  selectCell: "flex items-center justify-center",
  actionCell: "flex min-w-0 flex-wrap items-center justify-end gap-1",
  confirmList: "m-0 flex list-none flex-col gap-2 p-0 text-left",
  confirmItem: "min-w-0 rounded-md border border-[var(--border-soft)] bg-[var(--vui-surface-row)] px-2 py-1.5",
  confirmName: "m-0 text-[var(--fg-primary)]",
  confirmPath: "m-0 truncate text-[var(--fg-tertiary)]",
  confirmRisks: "m-0 mt-1 list-disc pl-4 text-[var(--state-warning)]",
} as const;

export default styles;
