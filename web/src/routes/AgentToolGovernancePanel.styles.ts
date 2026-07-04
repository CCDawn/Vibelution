const styles = {
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_var(--border-soft)] [border-radius:8px] [background:var(--surface-card)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  toolGovernanceList: "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  toolGovernanceItem: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [padding:8px] [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-control)] [background:var(--surface-panel)] [&_div]:first-child:grid [&_div]:first-child:[gap:3px] [&_div]:first-child:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  governanceActions: "inline-flex [align-items:center] [gap:6px] min-w-0",
  emptyText: "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0",
} as const;

export default styles;
