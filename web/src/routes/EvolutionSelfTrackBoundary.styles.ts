const styles = {
  selfModeStack:
    "grid [grid-template-rows:minmax(0,_1fr)] [gap:8px] min-h-0 [height:100%] [overflow:hidden] [padding-right:4px] max-[900px]:[grid-template-rows:minmax(0,_1fr)] max-[900px]:[height:100%] max-[900px]:[overflow:auto]",
  spinIcon:
    "animate-spin",
  structuredEmptyState:
    "grid [align-content:start] [gap:8px] [min-height:86px] [padding:10px_12px] [border-radius:8px] [border:1px_dashed_var(--vui-border-subtle)] [background:color-mix(in_srgb,_var(--vui-surface-row)_64%,_transparent)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]",
  surface:
    "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)] [box-shadow:none]",
};

export default styles;
