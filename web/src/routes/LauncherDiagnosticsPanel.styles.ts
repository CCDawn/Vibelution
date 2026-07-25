import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurface = `${vuiOpaqueRowClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";
const mutedControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-2 [font-size:var(--vui-font-xs)] leading-none text-vui-fg-secondary no-underline hover:border-vui-border-soft hover:bg-vui-control-muted-hover hover:text-vui-fg-primary disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";

const styles = {
  commandLine: `mt-2 grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-x-2 gap-y-[5px] ${rowSurface} px-[9px] py-[7px] max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_small]:col-start-2 [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[620px]:[&_small]:col-start-1`,
  compactItem: "grid min-w-0 grid-cols-[minmax(150px,0.74fr)_minmax(0,1fr)] gap-2 border-b border-[color-mix(in_srgb,var(--border-soft)_68%,transparent)] py-[5px] data-[tone=success]:[&_strong]:text-[var(--state-success)] data-[tone=error]:[&_strong]:text-[var(--state-error)] max-[620px]:grid-cols-[minmax(0,1fr)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]",
  compactList: "mt-2 grid min-w-0 gap-[5px] [&>small]:text-[var(--fg-secondary)]",
  diagnosticSection: `min-h-0 min-w-0 overflow-hidden ${rowSurface} p-2`,
  diagnosticsBody: "grid min-h-0 min-w-0 grid-cols-2 gap-2 overflow-auto px-2.5 pb-2.5 pr-1 [scrollbar-gutter:stable] max-[620px]:grid-cols-[minmax(0,1fr)]",
  // Wave 6C: PaneHeightResizeHandle owns row-resize visual; placement only.
  diagnosticsBodyResizeHandle:
    "diagnosticsBodyResizeHandle",
  diagnosticsGrid: "grid min-w-0 grid-cols-[minmax(72px,max-content)_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 px-2.5 pb-2.5 [&_dt]:m-0 [&_dt]:min-w-0 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:uppercase [&_dt]:tracking-[0.06em] [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:truncate [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:leading-tight [&_dd]:text-[var(--fg-primary)]",
  diagnosticsPanel: "col-auto block min-h-0 overflow-hidden p-0 [&_summary]:flex [&_summary]:min-w-0 [&_summary]:cursor-pointer [&_summary]:items-baseline [&_summary]:justify-between [&_summary]:gap-2.5 [&_summary]:px-2.5 [&_summary]:py-2 [&_summary]:text-[var(--fg-secondary)] [&_summary_span]:[font-size:var(--vui-font-xs)] [&_summary_span]:uppercase [&_summary_span]:tracking-[0.08em] [&_summary_span]:text-[var(--fg-tertiary)] [&_summary_strong]:text-[var(--fg-primary)]",
  guardianHead: `grid min-w-0 grid-cols-[minmax(178px,1fr)_minmax(120px,0.7fr)_minmax(84px,0.52fr)_minmax(0,1.7fr)] items-center gap-[7px] border-b border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)] max-[860px]:grid-cols-[minmax(140px,1fr)_minmax(96px,0.65fr)_minmax(82px,0.5fr)_minmax(0,1.4fr)] max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden`,
  guardianRow: "grid min-w-0 grid-cols-[minmax(178px,1fr)_minmax(120px,0.7fr)_minmax(84px,0.52fr)_minmax(0,1.7fr)] items-center gap-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_74%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] first:border-t-0 data-[tone=success]:border-l-2 data-[tone=success]:border-l-[var(--state-success)] data-[tone=warning]:border-l-2 data-[tone=warning]:border-l-[var(--state-warning)] data-[tone=error]:border-l-2 data-[tone=error]:border-l-[var(--state-error)] max-[860px]:grid-cols-[minmax(140px,1fr)_minmax(96px,0.65fr)_minmax(82px,0.5fr)_minmax(0,1.4fr)] max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--fg-primary)]",
  guardianSummary: "mt-2 grid min-w-0 grid-cols-[minmax(0,1fr)_repeat(3,max-content)_auto] items-center gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] max-[860px]:grid-cols-2 max-[860px]:[&_span]:col-span-full max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:min-w-0 [&_span]:truncate [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)]",
  // Wave 6F: height from PersistedHeightListShell, not fixed max-h.
  guardianTable: `mt-1.5 grid min-h-0 min-w-0 overflow-auto ${rowSurfaceMuted} [scrollbar-gutter:stable]`,
  guardianTableResizeHandle:
    "guardianTableResizeHandle",
  iconButton: mutedControl,
  panel: `block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  panelHeader: "flex min-w-0 items-baseline justify-between gap-2.5 border-b border-[var(--border-soft)] pb-1.5 [&>*]:min-w-0 [&_strong]:flex-auto [&_strong]:truncate [&_strong]:text-right [&_strong]:text-[var(--fg-primary)]",
  recoveryLine: `mt-2 grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-x-2 gap-y-[5px] ${rowSurface} px-[9px] py-[7px] data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_36%,transparent)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_small]:col-start-2 [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[620px]:[&_small]:col-start-1`,
  specGrid: "mt-2 grid min-w-0 grid-cols-[minmax(72px,max-content)_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 [&_dt]:m-0 [&_dt]:min-w-0 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:uppercase [&_dt]:tracking-[0.06em] [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:truncate [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:leading-tight [&_dd]:text-[var(--fg-primary)]",
  spin: "animate-spin",
} as const;

export default styles;
