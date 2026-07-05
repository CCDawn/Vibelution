const styles = {
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--border-soft)_78%,_transparent)] [border-radius:8px] [background:color-mix(in_srgb,_var(--surface-panel)_54%,_transparent)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  policySummaryGrid: "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] min-w-0 [overflow-wrap:anywhere] [&_span]:min-w-0 [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--border-soft)_86%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:color-mix(in_srgb,_var(--surface-panel)_50%,_transparent)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] max-[860px]:[grid-template-columns:1fr]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
} as const;

export default styles;
