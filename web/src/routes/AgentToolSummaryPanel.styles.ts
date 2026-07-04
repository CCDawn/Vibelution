const styles = {
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_var(--border-soft)] [border-radius:8px] [background:var(--surface-card)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  policySummaryGrid: "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] min-w-0 [&_span]:min-w-0 [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_var(--border-soft)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:var(--surface-panel)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
} as const;

export default styles;
