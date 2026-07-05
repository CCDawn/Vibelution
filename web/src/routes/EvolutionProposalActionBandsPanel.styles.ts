const rowSurface = "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] [background:var(--vui-surface-row)]";
const actionSurface = "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-control-muted)] [color:var(--fg-primary)] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] hover:[background:var(--vui-control-muted-hover)]";

const styles = {
  actionRow:
    "flex [flex-wrap:wrap] [gap:6px]",
  detailList:
    "[margin:0] [padding-left:18px] [color:var(--fg-secondary)] grid [gap:8px]",
  detailSection:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.6] grid [border-top:1px_solid_var(--border-hairline)] [gap:6px] [padding-top:10px] [margin-top:10px]",
  errorText:
    "[margin:0] [line-height:1.4] [color:var(--state-error)]",
  feedbackText:
    "[margin:0] [color:var(--fg-secondary)] [line-height:1.55] [white-space:pre-wrap]",
  inlineAction:
    `${actionSurface} [justify-self:end] min-w-0 [max-width:100%] inline-flex [align-items:center] [justify-content:center] [gap:8px] [width:fit-content] [min-height:32px] [padding:0_10px] [font-size:var(--vui-font-xs)]`,
  relatedList:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] max-[900px]:[grid-template-columns:1fr]",
  relatedRow:
    `grid ${rowSurface} [gap:4px] [min-height:48px] [padding:9px_10px]`,
};

export default styles;
