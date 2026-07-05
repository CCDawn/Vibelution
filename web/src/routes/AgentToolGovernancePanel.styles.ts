const styles = {
  configEditor: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--border-soft)_78%,_transparent)] [border-radius:8px] [background:color-mix(in_srgb,_var(--surface-panel)_54%,_transparent)]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  toolGovernanceList: "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  toolGovernanceItem: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [padding:8px] [border:1px_solid_color-mix(in_srgb,_var(--border-soft)_86%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--surface-panel)_50%,_transparent)] [overflow-wrap:anywhere] [&_div]:first-child:grid [&_div]:first-child:[gap:3px] [&_div]:first-child:min-w-0 [&_strong]:min-w-0 [&_span]:min-w-0 [&_small]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
  governanceActions: "inline-flex [align-items:center] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
  emptyText: "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
  editorActions: "flex [justify-content:flex-end] [gap:6px] min-w-0 [flex-wrap:wrap] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit",
} as const;

export default styles;
