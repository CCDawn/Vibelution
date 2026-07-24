import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  activeChannelPill:
    `activeChannelPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] ${vuiStateSelectedRowClass}`,
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  matrixCard: `matrixCard min-w-0 max-w-full ${vuiOpaqueRowClass} p-2 !grid grid-cols-[minmax(0,1fr)_auto] gap-2.5 text-left [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&_span]:line-clamp-2 [&_span]:min-w-0 [&_dl]:grid [&_dl]:grid-cols-2 [&_dl]:gap-1.5`,
  matrixCardActive:
    `matrixCardActive min-w-0 ${vuiStateSelectedRowClass}`,
  matrixCardButton:
    "matrixCardButton min-w-0 w-full max-w-full !grid min-h-[70px] items-center text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:contents",
  matrixGrid:
    "matrixGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(100%,10rem),1fr))]",
  matrixHeader: "matrixHeader min-w-0 flex flex-wrap items-center gap-1.5",
  matrixHeaderMeta:
    "matrixHeaderMeta min-w-0 flex flex-wrap items-center gap-1.5",
  matrixPanel: `matrixPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
