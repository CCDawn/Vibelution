const styles = {
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_var(--border-soft)] [border-radius:8px] [background:var(--surface-card)]",
  dirtyPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
  editorGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] max-[860px]:[grid-template-columns:1fr]",
  fieldWide: "grid [grid-column:1_/_-1] [gap:4px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32] [&_textarea]:[width:100%] [&_textarea]:min-w-0 [&_textarea]:[border:1px_solid_var(--border-soft)] [&_textarea]:[border-radius:var(--radius-control)] [&_textarea]:[background:var(--surface-panel)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-xs)] [&_textarea]:[min-height:62px] [&_textarea]:[resize:vertical] [&_textarea]:[padding:7px_9px] [&_textarea]:[line-height:1.35] [&_textarea]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_textarea]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
} as const;

export default styles;
