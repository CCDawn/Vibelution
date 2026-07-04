const styles = {
  protectedZone: "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--border-soft))] [border-radius:8px] [background:color-mix(in_srgb,_var(--accent-cool)_7%,_var(--surface-card))] [&_svg]:[color:var(--accent-cool)]",
  dangerZone: "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--state-error)_32%,_var(--border-soft))] [border-radius:8px] [background:color-mix(in_srgb,_var(--state-error)_7%,_var(--surface-card))] [&_svg]:[color:var(--state-error)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
} as const;

export default styles;
