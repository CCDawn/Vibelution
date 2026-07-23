const styles = {
  selfModeStack:
    "grid min-h-0 h-full max-h-full grid-rows-[minmax(0,1fr)] content-stretch items-stretch gap-0 overflow-hidden pr-1 max-[900px]:h-full max-[900px]:overflow-auto",
  spinIcon:
    "animate-spin",
  structuredEmptyState:
    "grid [align-content:start] [gap:8px] [min-height:86px] [padding:10px_12px] [border-radius:8px] [border:1px_dashed_var(--vui-border-subtle)] [background:color-mix(in_srgb,_var(--vui-surface-row)_64%,_transparent)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]",
  surface:
    "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)] [box-shadow:none]",
};

export default styles;
