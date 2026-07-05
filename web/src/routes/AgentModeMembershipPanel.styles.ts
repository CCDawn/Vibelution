const styles = {
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--border-soft)_76%,_transparent)] [border-radius:8px] [background:color-mix(in_srgb,_var(--surface-panel)_58%,_transparent)]",
  dirtyPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
  editorGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] max-[860px]:[grid-template-columns:1fr]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  toggleGrid: "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] max-[860px]:[grid-template-columns:1fr]",
} as const;

export default styles;
