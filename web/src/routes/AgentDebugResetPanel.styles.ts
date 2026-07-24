import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  contextualHintRow: "inline-flex [align-items:center] [gap:6px]",
  resetZone: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--state-warning)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--state-warning)_7%,_transparent)] [&_svg]:[color:var(--state-warning)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  resetOptionGrid: "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  resetOptionField: `grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:start] [gap:8px] min-w-0 [min-height:58px] [padding:7px_8px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [&_input]:[margin-top:3px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_small]:min-w-0 [&_small]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32]`,
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
} as const;

export default styles;
