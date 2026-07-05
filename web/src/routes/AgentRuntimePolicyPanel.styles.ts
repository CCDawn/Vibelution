const styles = {
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--border-soft)_76%,_transparent)] [border-radius:8px] [background:color-mix(in_srgb,_var(--surface-panel)_58%,_transparent)]",
  contextModeGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  dirtyPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
  editorGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] max-[860px]:[grid-template-columns:1fr]",
  errorText: "[margin:0] [font-size:var(--vui-font-xs)] [line-height:1.4] [overflow-wrap:anywhere] [color:var(--state-error)]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  pathList: "[&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] grid [align-content:start] [gap:5px] min-w-0 [&_span]:[margin:0] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  runtimePolicyGrid: "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:7px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--border-soft)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:[background:color-mix(in_srgb,_var(--surface-panel)_58%,_transparent)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] max-[860px]:[grid-template-columns:1fr]",
  successText: "[margin:0] [font-size:var(--vui-font-xs)] [line-height:1.4] [overflow-wrap:anywhere] [color:var(--state-success)]",
  toggleGrid: "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] max-[860px]:[grid-template-columns:1fr]",
} as const;

export default styles;
