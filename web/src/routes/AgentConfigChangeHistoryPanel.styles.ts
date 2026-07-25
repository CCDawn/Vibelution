import { vuiFlatPanelClass, vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  historyPanel: `grid min-w-0 [align-content:start] [gap:8px] [padding:10px] ${vuiFlatPanelClass}`,
  panelHeader: "grid min-w-0 [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:8px] [&_div]:min-w-0 [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)] [&_h3]:[font-size:var(--vui-font-md)] [&_p]:m-0 [&_p]:mt-1 [&_p]:text-[var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-[1.45] max-[640px]:[grid-template-columns:1fr]",
  actions: "flex min-w-0 [flex-wrap:wrap] [gap:6px]",
  draftCard: `grid min-w-0 [gap:7px] [padding:9px] ${vuiOpaqueRowClass}`,
  draftHeader: "flex min-w-0 [flex-wrap:wrap] [align-items:center] [justify-content:space-between] [gap:6px] [&_h4]:m-0 [&_h4]:text-[var(--fg-primary)] [&_h4]:[font-size:var(--vui-font-sm)]",
  draftStatus: "[color:var(--accent-cool)] [font-size:var(--vui-font-xs)]",
  draftStale: "[color:var(--vui-status-warning-fg)]",
  draftSummary: "m-0 [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.45]",
  changedFields: "flex min-w-0 [flex-wrap:wrap] [gap:5px] [margin:0] [padding:0] [list-style:none]",
  changedField: "[padding:3px_6px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] [border-radius:var(--radius-control)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)]",
  draftActions: "flex min-w-0 [flex-wrap:wrap] [gap:6px]",
  revisionHeader: "flex min-w-0 [align-items:baseline] [justify-content:space-between] [gap:8px] [&_h4]:m-0 [&_h4]:text-[var(--fg-primary)] [&_h4]:[font-size:var(--vui-font-sm)] [&_span]:text-[var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  revisionList: "grid min-w-0 [gap:5px]",
  revisionRow: "grid min-w-0 [gap:5px] [padding:8px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)]",
  revisionMeta: "flex min-w-0 [flex-wrap:wrap] [gap-x:8px] [gap-y:3px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)]",
  emptyText: "m-0 [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)]",
} as const;

export default styles;
