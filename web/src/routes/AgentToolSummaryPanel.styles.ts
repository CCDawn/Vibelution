import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  configEditor: `grid [gap:8px] min-w-0 [padding:10px] ${vuiFlatPanelClass}`,
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  titleRow: "flex min-w-0 items-center gap-1 [&_h3]:min-w-0 [&_h3]:overflow-wrap:anywhere",
  policySummaryGrid: "flex [flex-wrap:wrap] [align-items:center] [gap:5px] min-w-0 [overflow-wrap:anywhere] [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[gap:4px] [&_span]:min-w-0 [&_span]:[max-width:100%] [&_span]:[min-height:28px] [&_span]:[padding:0_8px] [&_span]:[border:1px_solid_var(--vui-border-subtle)] [&_span]:[border-radius:var(--radius-control)] [&_span]:!bg-[var(--vui-surface-row)] [&_b]:min-w-0 [&_b]:[overflow-wrap:anywhere] [&_b]:[color:var(--fg-secondary)] [&_b]:[font-size:var(--vui-font-xs)] [&_b]:[font-weight:650] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
} as const;

export default styles;
