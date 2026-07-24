import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  configEditor: `grid [gap:8px] min-w-0 [padding:10px] ${vuiFlatPanelClass}`,
  dirtyPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
  inlineAdd: "grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:6px] min-w-0 [&_input]:min-w-0 [&_input]:[min-height:32px] [&_input]:[border-radius:var(--radius-control)] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:[width:100%] [&_input]:[padding:0_8px] [&_input]:[border:1px_solid_var(--vui-border-subtle)] [&_input]:!bg-[var(--vui-surface-workspace)] [&_input]:[color:var(--fg-primary)] [&_[data-vui=\\\"button\\\"]]:[white-space:nowrap]",
  memoryPolicyGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:6px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:!bg-[var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  pathList: "[&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] grid [align-content:start] [gap:5px] min-w-0 [&_span]:[margin:0] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  tagList: "flex [flex-wrap:wrap] [gap:5px] min-w-0 [min-height:28px] [&_button]:inline-flex [&_button]:[align-items:center] [&_button]:[min-height:24px] [&_button]:[max-width:100%] [&_button]:[padding:0_7px] [&_button]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_button]:[border-radius:999px] [&_button]:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [&_button]:[color:var(--accent-cool)] [&_button]:[font-size:var(--vui-font-xs)] [&_button]:[overflow:hidden] [&_button]:[text-overflow:ellipsis] [&_button]:[white-space:nowrap] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
} as const;

export default styles;
