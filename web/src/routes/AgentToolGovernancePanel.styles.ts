import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  configEditor: `grid [gap:8px] min-w-0 [padding:10px] ${vuiFlatPanelClass}`,
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  titleRow: "flex min-w-0 items-center gap-1 [&_h3]:min-w-0 [&_h3]:overflow-wrap:anywhere",
  toolGovernanceList: "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  toolGovernanceItem: `grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [padding:8px] ${vuiOpaqueRowClass} [overflow-wrap:anywhere] [&_div]:first-child:min-w-0 [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]`,
  governanceMetaTrigger: "block min-w-0 [overflow-wrap:anywhere] [border-radius:6px] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  governanceActions: "inline-flex [align-items:center] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
  emptyText: "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
} as const;

export default styles;
