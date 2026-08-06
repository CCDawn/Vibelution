import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  fieldWide: "grid [grid-column:1_/_-1] [gap:7px] min-w-0 [&_textarea]:[width:100%] [&_textarea]:min-w-0 [&_textarea]:[border:1px_solid_var(--vui-border-subtle)] [&_textarea]:[border-radius:var(--radius-control)] [&_textarea]:[background:var(--vui-surface-row)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-xs)] [&_textarea]:[min-height:62px] [&_textarea]:[resize:vertical] [&_textarea]:[padding:7px_9px] [&_textarea]:[line-height:1.35] [&_textarea]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_textarea]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  compressionPolicyHeader: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [&_h3]:[margin:0] [&_h3]:min-w-0",
  compressionPolicyTitle: "inline-block min-w-0 [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap] [border-radius:6px] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  compressionPolicyGrid: "grid [gap:7px] min-w-0 [grid-template-columns:repeat(3,_minmax(0,_1fr))] [align-items:end] max-[860px]:[grid-template-columns:1fr]",
  compressionPolicySubgrid: `grid [gap:7px] min-w-0 [grid-template-columns:repeat(4,_minmax(0,_1fr))] [padding:7px] ${vuiOpaqueRowClass} max-[860px]:[grid-template-columns:1fr]`,
  compressionPolicyFooter: "grid [gap:7px] min-w-0 [grid-template-columns:minmax(110px,_1fr)_repeat(2,_minmax(0,_1fr))] [align-items:end] max-[860px]:[grid-template-columns:1fr]",
  configDeepLinkRow: "flex [justify-content:flex-end] [gap:6px] min-w-0 [&_[data-vui=\\\"button\\\"]]:[white-space:nowrap]",
} as const;

export default styles;
