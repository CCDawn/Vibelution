const styles = {
  actionRow:
    "flex [flex-wrap:wrap] [gap:6px]",
  closedLoopLedger:
    "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_30%,_var(--border-hairline))] [border-radius:7px] [background:color-mix(in_srgb,_var(--surface-card-subtle)_88%,_var(--accent-cool))] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.45] [&_p]:[overflow-wrap:anywhere]",
  closedLoopLedgerEvidenceGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] [&_article]:grid [&_article]:[gap:3px] [&_article]:min-w-0 [&_article]:[padding:7px_8px] [&_article]:[border:1px_solid_var(--border-hairline)] [&_article]:[border-radius:6px] [&_article]:[background:var(--surface-card-muted)] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)]",
  closedLoopLedgerHeader:
    "flex [align-items:flex-start] [justify-content:space-between] [gap:10px] min-w-0 [&_div]:grid [&_div]:[gap:3px] [&_div]:min-w-0",
  compactActionGroup:
    "inline-flex [align-items:center] [gap:6px] min-w-0",
  compactIconAction:
    "inline-flex w-9 [align-items:center] [justify-content:center] [gap:7px] [min-height:34px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--surface-card-muted)] [color:var(--fg-primary)] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] [width:36px] [padding:0] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] hover:[background:var(--surface-card-hover)] disabled:[cursor:not-allowed] disabled:[color:var(--fg-tertiary)] disabled:[opacity:0.52]",
  compactTextAction:
    "inline-flex [align-items:center] [justify-content:center] [gap:7px] [min-height:34px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--surface-card-muted)] [color:var(--fg-primary)] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] [max-width:190px] [padding:0_10px] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] hover:[background:var(--surface-card-hover)] disabled:[cursor:not-allowed] disabled:[color:var(--fg-tertiary)] disabled:[opacity:0.52]",
  detailSection:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.6] grid [border-top:1px_solid_var(--border-hairline)] [gap:6px] [padding-top:10px] [margin-top:10px]",
  detailSectionCompact:
    "[margin-top:0] [padding-top:0] [border-top:0]",
  errorTextCompact:
    "[margin:0] [padding:9px_10px] [border-radius:8px] [line-height:1.45] [overflow-wrap:anywhere] [color:var(--state-error)] [background:color-mix(in_srgb,_var(--state-error)_11%,_transparent)]",
  eventHeader:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap]",
  eventList:
    "grid [gap:8px]",
  eventListScrollable:
    "[max-height:220px] [overflow:auto] [padding-right:4px]",
  eventRow:
    "grid [gap:5px] min-w-0 [padding:9px_10px] [border-radius:8px] [background:var(--surface-card-muted)] [border:1px_solid_var(--border-hairline)]",
  eventSummary:
    "[margin:0] [color:var(--fg-secondary)] [line-height:1.5] [display:-webkit-box] [overflow:hidden] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
  eyebrow:
    "[margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  feedbackTextCompact:
    "[margin:0] [padding:9px_10px] [border-radius:8px] [line-height:1.45] [overflow-wrap:anywhere] [color:var(--fg-secondary)] [white-space:pre-wrap] [background:color-mix(in_srgb,_var(--state-success)_9%,_transparent)]",
  formHint:
    "[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] max-[1200px]:hidden",
  heroSummary:
    "[margin:0] [color:var(--fg-secondary)] [line-height:1.6] [display:-webkit-box] [overflow:hidden] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]",
  idleMonitor:
    "grid [align-content:start] [gap:8px] [height:100%] min-h-0 [padding:10px_12px_12px]",
  inlineAction:
    "[border:1px_solid_var(--border-hairline)] [border-radius:8px] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] hover:[background:var(--surface-card-hover)] [justify-self:end] min-w-0 [max-width:100%] inline-flex [align-items:center] [justify-content:center] [gap:8px] [background:var(--surface-card-muted)] [color:var(--fg-primary)] [width:fit-content] [min-height:32px] [padding:0_10px] [font-size:var(--vui-font-xs)]",
  liveRunToolbar:
    "flex [align-items:center] [justify-content:space-between] [gap:10px] min-w-0 [padding:8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--surface-card-subtle)]",
  liveStatusRow:
    "flex [align-items:center] [justify-content:flex-end] [gap:8px] min-w-0 [max-width:min(100%,_320px)] [flex-wrap:wrap]",
  liveSummaryRow:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [gap:10px] [align-items:start] min-w-0 [padding:10px_12px] [border-radius:8px] [background:var(--surface-card-subtle)] [border:1px_solid_var(--border-hairline)]",
  metricStrip:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:10px] max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[640px]:[grid-template-columns:1fr]",
  metricTile:
    "grid [gap:3px] min-w-0 [border-radius:var(--radius-card)] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-weight:600] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [min-height:36px] [padding:5px_7px]",
  monitorMetricsDense:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[640px]:[grid-template-columns:1fr]",
  monitorSummary:
    "grid [gap:10px]",
  noticeText:
    "[color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [margin:0] [display:-webkit-box] [overflow:hidden] [line-height:1.45] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] max-[1200px]:hidden",
  noticeTextCompact:
    "[margin:0] [padding:9px_10px] [border-radius:8px] [line-height:1.45] [overflow-wrap:anywhere] [color:var(--fg-secondary)] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)]",
  relatedList:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] max-[900px]:[grid-template-columns:1fr]",
  relatedRow:
    "grid [border-radius:8px] [background:var(--surface-card-muted)] [border:1px_solid_var(--border-hairline)] [gap:4px] [min-height:48px] [padding:9px_10px]",
  runControlReason:
    "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.45] [overflow-wrap:anywhere]",
  runControlSummaryBody:
    "grid [gap:4px] min-w-0",
  runMonitorDense:
    "grid [align-content:start] [gap:8px] [height:100%] min-h-0 [padding:10px_12px_12px]",
  runNextActionStrip:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [gap:8px] [align-items:start] min-w-0 [padding:8px_10px] [border-radius:7px] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.45] [&_strong]:[color:var(--fg-primary)] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow-wrap:anywhere]",
  runSummaryTone_danger:
    "[border-color:color-mix(in_srgb,_var(--state-error)_38%,_var(--border-hairline))] [background:color-mix(in_srgb,_var(--state-error)_9%,_var(--surface-card-subtle))]",
  runSummaryTone_idle:
    "[border-color:var(--border-hairline)] [background:var(--surface-card-subtle)]",
  runSummaryTone_running:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_34%,_var(--border-hairline))] [background:color-mix(in_srgb,_var(--accent-cool)_8%,_var(--surface-card-subtle))]",
  runSummaryTone_success:
    "[border-color:color-mix(in_srgb,_var(--state-success)_34%,_var(--border-hairline))] [background:color-mix(in_srgb,_var(--state-success)_8%,_var(--surface-card-subtle))]",
  runSummaryTone_warning:
    "[border-color:color-mix(in_srgb,_var(--state-warning)_38%,_var(--border-hairline))] [background:color-mix(in_srgb,_var(--state-warning)_9%,_var(--surface-card-subtle))]",
  secondaryPill:
    "inline-flex [align-items:center] [justify-content:center] [max-width:100%] [min-height:28px] [padding:0_10px] [border-radius:999px] [border:1px_solid_var(--border-soft)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis] [color:var(--fg-secondary)] [background:var(--surface-card-muted)]",
  sectionTitle:
    "[margin:3px_0_0] [line-height:1.18] [margin-top:2px] [font-size:0.98rem]",
  statusIcon:
    "inline-flex [align-items:center] [justify-content:center] [border-radius:999px] [color:var(--accent-warm-2)] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)] [width:30px] [height:30px]",
  statusPill:
    "inline-flex [align-items:center] [justify-content:center] [max-width:100%] [min-height:28px] [padding:0_10px] [border-radius:999px] [border:1px_solid_var(--border-soft)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis] [color:var(--accent-warm-2)] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)]",
  stripItem:
    "grid [gap:3px] min-w-0 [border-radius:var(--radius-card)] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-weight:600] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [min-height:36px] [padding:5px_7px]",
  surfaceHeaderCompact:
    "flex [justify-content:space-between] [gap:10px] min-w-0 [&_div]:min-w-0 [align-items:center]",
  truncateText:
    "min-w-0 [max-width:100%] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
} as const;

export default styles;
