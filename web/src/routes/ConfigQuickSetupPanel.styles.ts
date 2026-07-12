const panelSurface =
  "[background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px]";

const styles = {
  root: "vui-routes-configquicksetuppanel root min-w-0",
  workspace: "vui-routes-configquicksetuppanel workspace grid min-w-0 [grid-template-columns:minmax(22rem,0.9fr)_minmax(28rem,1.1fr)] gap-4",
  inputColumn: `vui-routes-configquicksetuppanel inputColumn ${panelSurface} grid min-w-0 content-start gap-4 p-4`,
  resultColumn: `vui-routes-configquicksetuppanel resultColumn ${panelSurface} grid min-h-[28rem] min-w-0 content-start gap-3 p-4`,
  field: "vui-routes-configquicksetuppanel field grid min-w-0 gap-1 text-[var(--vui-font-xs)] font-semibold text-vui-fg-secondary",
  hint: "vui-routes-configquicksetuppanel hint text-[var(--vui-font-xs)] leading-relaxed text-vui-fg-tertiary",
  advanced: "vui-routes-configquicksetuppanel advanced grid min-w-0 gap-2 rounded-md border border-vui-border-subtle bg-vui-surface-row p-2",
  advancedSummary: "vui-routes-configquicksetuppanel advancedSummary cursor-pointer text-[var(--vui-font-sm)] font-semibold text-vui-fg-secondary",
  advancedGrid: "vui-routes-configquicksetuppanel advancedGrid grid min-w-0 [grid-template-columns:repeat(2,minmax(0,1fr))] gap-2 pt-2",
  actionRow: "vui-routes-configquicksetuppanel actionRow flex min-w-0 flex-wrap items-center gap-2",
  resultHeader: "vui-routes-configquicksetuppanel resultHeader flex min-w-0 items-start justify-between gap-2",
  resultTitle: "vui-routes-configquicksetuppanel resultTitle m-0 text-[var(--vui-font-md)] font-bold text-vui-fg-primary",
  modelList: "vui-routes-configquicksetuppanel modelList grid min-w-0 gap-2",
};

export default styles;
