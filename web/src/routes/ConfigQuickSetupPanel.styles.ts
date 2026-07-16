const panelSurface =
  "[background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  root: "vui-routes-configquicksetuppanel root min-w-0",
  workspace: "vui-routes-configquicksetuppanel workspace grid w-full max-w-[88rem] min-w-0 gap-4",
  inputPanel: `vui-routes-configquicksetuppanel inputPanel ${panelSurface} grid min-w-0 gap-3 p-4`,
  inputGrid: "vui-routes-configquicksetuppanel inputGrid grid min-w-0 items-end [grid-template-columns:minmax(15rem,1fr)_minmax(18rem,1.2fr)_max-content] gap-3",
  field: "vui-routes-configquicksetuppanel field grid min-w-0 gap-1 text-[var(--vui-font-xs)] font-semibold text-vui-fg-secondary [&_[data-vui=select-trigger]]:!h-10 [&_[data-vui=select-trigger]]:!min-h-10 [&_input]:!min-h-10",
  noCredential: "vui-routes-configquicksetuppanel noCredential flex min-h-8 min-w-0 items-center gap-1.5 rounded-md border border-vui-border-subtle bg-vui-surface-row px-2 text-[var(--vui-font-sm)] font-semibold text-vui-fg-secondary",
  advanced: "vui-routes-configquicksetuppanel advanced grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-row p-2",
  advancedSummary: "vui-routes-configquicksetuppanel advancedSummary cursor-pointer text-[var(--vui-font-sm)] font-semibold text-vui-fg-secondary",
  advancedGrid: "vui-routes-configquicksetuppanel advancedGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 pt-2",
  primaryAction: "vui-routes-configquicksetuppanel primaryAction min-h-10 min-w-[9rem] justify-center px-4",
  resultRegion: `vui-routes-configquicksetuppanel resultRegion ${panelSurface} grid min-w-0 gap-3 p-4`,
  resultHeader: "vui-routes-configquicksetuppanel resultHeader flex min-w-0 items-start justify-between gap-2",
  resultTitle: "vui-routes-configquicksetuppanel resultTitle m-0 text-[var(--vui-font-md)] font-bold text-vui-fg-primary",
  reviewActions: "vui-routes-configquicksetuppanel reviewActions grid min-w-0 items-end [grid-template-columns:minmax(18rem,1fr)_max-content_max-content] gap-2",
};

export default styles;
