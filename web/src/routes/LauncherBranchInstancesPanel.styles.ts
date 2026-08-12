import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";

const styles = {
  panel: `mx-2 mt-1.5 block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  panelHeader:
    "flex min-h-0 min-w-0 items-baseline justify-between gap-2.5 border-b border-[var(--border-soft)] pb-1.5 [&>*]:min-w-0 [&_strong]:flex-auto [&_strong]:truncate [&_strong]:text-right [&_strong]:text-[var(--fg-primary)]",
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  statusTable: `mt-1.5 grid min-w-0 overflow-hidden ${rowSurfaceMuted}`,
  statusHead:
    `grid min-w-0 grid-cols-[minmax(140px,1fr)_minmax(88px,0.6fr)_minmax(88px,0.6fr)_minmax(72px,0.45fr)_minmax(64px,0.4fr)_minmax(0,1.4fr)] items-center gap-[7px] border-b border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)] max-[860px]:grid-cols-[minmax(120px,1fr)_minmax(72px,0.55fr)_minmax(0,1.2fr)] max-[860px]:[&>span:nth-child(4)]:hidden max-[860px]:[&>span:nth-child(5)]:hidden max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden`,
  statusRow:
    "grid min-w-0 cursor-pointer grid-cols-[minmax(140px,1fr)_minmax(88px,0.6fr)_minmax(88px,0.6fr)_minmax(72px,0.45fr)_minmax(64px,0.4fr)_minmax(0,1.4fr)] items-center gap-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_74%,var(--vui-surface-row))] px-2 py-1.5 text-left [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] first:border-t-0 data-[tone=success]:border-l-2 data-[tone=success]:border-l-[var(--state-success)] data-[tone=warning]:border-l-2 data-[tone=warning]:border-l-[var(--state-warning)] data-[selected=true]:bg-[color-mix(in_srgb,var(--vui-accent)_14%,var(--vui-surface-row))] max-[860px]:grid-cols-[minmax(120px,1fr)_minmax(72px,0.55fr)_minmax(0,1.2fr)] max-[860px]:[&>span:nth-child(4)]:hidden max-[860px]:[&>span:nth-child(5)]:hidden max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--fg-primary)]",
} as const;

export default styles;
