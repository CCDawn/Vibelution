
const styles = {
  // Main column only — inspector lives in workspace third column.
  selectedDetailFrame:
    "grid h-full min-h-0 w-full min-w-0 [grid-template-rows:auto_minmax(0,_1fr)] [align-content:start] [gap:12px] [overflow:hidden]",
  detailHeaderRegion:
    "grid min-w-0 [align-content:start] [gap:8px]",
  overviewLayout:
    "grid min-h-0 min-w-0 [align-content:start] [gap:8px] [overflow:auto] [overscroll-behavior:contain]",
  overviewMain: "grid min-w-0 [align-content:start] [gap:8px]",
  // Kept for layout-contract compatibility (inspector moved to workspace rail).
  overviewAside:
    "hidden",
  paneContent:
    "grid min-h-0 min-w-0 [align-content:start] [gap:8px] [overflow:auto] [overscroll-behavior:contain]",
  configPane: "grid h-full min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden bg-vui-surface-panel",
  configSectionNav: "flex min-w-0 shrink-0 items-center gap-6 overflow-x-auto border-b border-vui-border-subtle px-10 [scrollbar-width:none] max-sm:gap-5 max-sm:px-4",
  configSectionTab: "inline-flex h-11 min-h-11 shrink-0 items-center gap-1 border-x-0 border-t-0 border-b-2 border-transparent bg-transparent p-0 text-sm font-normal text-vui-fg-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vui-accent-cool",
  configSectionTabActive: "inline-flex h-11 min-h-11 shrink-0 items-center gap-1 border-x-0 border-t-0 border-b-2 border-vui-fg-primary bg-transparent p-0 text-sm font-medium text-vui-fg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vui-accent-cool",
  configSectionBody: "h-full min-h-0 min-w-0 overflow-hidden",
  opsContent: "grid h-full min-h-0 min-w-0 content-start gap-6 overflow-auto px-10 py-7 max-sm:px-4",
  secondaryDetails: "border-t border-vui-border-subtle pt-4",
  secondarySummary: "cursor-pointer py-2 text-sm font-medium",
  secondaryBody: "grid gap-4 pt-4",
  configSectionBadge:
    "inline-flex [align-items:center] [justify-content:center] [min-width:18px] [min-height:18px] [padding:0_5px] [border-radius:999px] [background:color-mix(in_srgb,_var(--accent-warm)_14%,_transparent)] [color:var(--accent-warm-2)] [font-size:var(--vui-font-xs)] [font-weight:800]",
} as const;

export default styles;
