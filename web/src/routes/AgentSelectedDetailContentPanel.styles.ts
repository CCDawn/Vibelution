const styles = {
  // Main column only — inspector lives in workspace third column.
  selectedDetailFrame:
    "grid h-full min-h-0 w-full min-w-0 [grid-template-rows:auto_minmax(0,_1fr)] [align-content:start] [gap:12px] [overflow:hidden]",
  overviewLayout:
    "grid min-h-0 min-w-0 [align-content:start] [gap:8px] [overflow:auto] [overscroll-behavior:contain]",
  overviewMain: "grid min-w-0 [align-content:start] [gap:8px]",
  // Kept for layout-contract compatibility (inspector moved to workspace rail).
  overviewAside:
    "hidden",
  paneContent:
    "grid min-h-0 min-w-0 [align-content:start] [gap:8px] [overflow:auto] [overscroll-behavior:contain]",
  configSectionNav:
    "inline-grid w-fit max-w-full [grid-auto-flow:column] [grid-auto-columns:minmax(88px,_max-content)] [gap:3px] min-w-0 [padding:3px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] max-[860px]:grid max-[860px]:w-full max-[860px]:[grid-auto-flow:row] max-[860px]:[grid-auto-columns:auto] max-[860px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))]",
  configSectionTab:
    "inline-flex w-full [align-items:center] [justify-content:center] [gap:6px] min-w-0 [min-height:30px] [padding:4px_10px] [border:1px_solid_transparent] [border-radius:var(--radius-control)] [background:transparent] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:720] hover:[background:var(--vui-surface-row-hover)] hover:[color:var(--fg-secondary)]",
  configSectionTabActive:
    "inline-flex w-full [align-items:center] [justify-content:center] [gap:6px] min-w-0 [min-height:30px] [padding:4px_10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_30%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [color:var(--accent-cool)] [font-size:var(--vui-font-xs)] [font-weight:760]",
  configSectionBody: "grid min-w-0 [align-content:start] [gap:8px]",
  configSectionBadge:
    "inline-flex [align-items:center] [justify-content:center] [min-width:18px] [min-height:18px] [padding:0_5px] [border-radius:999px] [background:color-mix(in_srgb,_var(--accent-warm)_14%,_transparent)] [color:var(--accent-warm-2)] [font-size:var(--vui-font-xs)] [font-weight:800]",
} as const;

export default styles;
