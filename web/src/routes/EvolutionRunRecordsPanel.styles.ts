const styles = {
  actionRow:
    "flex [flex-wrap:wrap] [gap:6px]",
  batchToggle:
    "inline-flex [align-items:center] [gap:8px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [&_input]:[width:15px] [&_input]:[height:15px]",
  bulkToolbar:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [flex-wrap:wrap]",
  bulkToolbarHint:
    "[flex-basis:100%] [margin:-2px_0_0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.45]",
  bulkToolbarText:
    "inline-flex [align-items:center] [gap:8px] [color:var(--fg-secondary)]",
  cardFooter:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [flex-wrap:wrap]",
  compactFact:
    "grid [align-content:center] [gap:3px] min-w-0 [min-height:42px] [padding:7px_8px] [border-radius:8px] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)] [&_span]:min-w-0 [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.92rem] [&_strong]:[font-weight:650] [&_strong]:[overflow-wrap:anywhere]",
  dangerDetailSection:
    "[opacity:0.86]",
  detailFactGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:10px] max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[640px]:[grid-template-columns:1fr]",
  detailHeader:
    "flex [justify-content:space-between] [gap:12px] [align-items:start]",
  detailHeaderActions:
    "inline-flex [align-items:center] [justify-content:flex-end] [gap:8px] [flex-wrap:wrap]",
  detailLead:
    "[margin:0] [font-size:1.74rem] [color:var(--fg-primary)_!important] [line-height:1]",
  detailSection:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.6] grid [border-top:1px_solid_var(--border-hairline)] [gap:6px] [padding-top:10px] [margin-top:10px]",
  detailSectionCompact:
    "[margin-top:0] [padding-top:0] [border-top:0]",
  detailSubtleId:
    "min-w-0 [overflow:hidden] [color:var(--fg-tertiary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [text-overflow:ellipsis] [white-space:nowrap]",
  detailTitle:
    "[margin:6px_0_0] [font-size:1.08rem]",
  errorText:
    "[margin:0] [line-height:1.4] [color:var(--state-error)]",
  eyebrow:
    "[margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  feedbackText:
    "[margin:0] [color:var(--fg-secondary)] [line-height:1.55] [white-space:pre-wrap]",
  inlineAction:
    "[border:1px_solid_var(--border-hairline)] [border-radius:8px] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] hover:[background:var(--surface-card-hover)] [justify-self:end] min-w-0 [max-width:100%] inline-flex [align-items:center] [justify-content:center] [gap:8px] [background:var(--surface-card-muted)] [color:var(--fg-primary)] [width:fit-content] [min-height:32px] [padding:0_10px] [font-size:var(--vui-font-xs)]",
  listRowTop:
    "flex [align-items:center] [justify-content:space-between] [gap:12px]",
  metaRow:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [&_span]:[color:var(--fg-tertiary)]",
  noticeText:
    "[color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [margin:0] [display:-webkit-box] [overflow:hidden] [line-height:1.45] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] max-[1200px]:hidden",
  paneCollapsed:
    "[padding:0] [border:0] [overflow:hidden] [visibility:hidden]",
  panelHeader:
    "flex [align-items:start] [justify-content:space-between] [gap:12px]",
  relatedList:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] max-[900px]:[grid-template-columns:1fr]",
  relatedRow:
    "grid [border-radius:8px] [background:var(--surface-card-muted)] [border:1px_solid_var(--border-hairline)] [gap:4px] [min-height:48px] [padding:9px_10px]",
  runCardButton:
    "grid w-full [gap:8px] [border:0] [padding:0] [background:transparent] [color:inherit] [text-align:left]",
  runDetailOverview:
    "grid [grid-template-columns:minmax(190px,_0.42fr)_minmax(0,_1fr)] [gap:10px] [align-items:start] [padding:10px] [border-radius:8px] [border:1px_solid_var(--border-hairline)] [background:var(--surface-card-subtle)] max-[900px]:[grid-template-columns:1fr]",
  runDetailPanel:
    "min-h-0 [padding:10px_12px] grid [align-content:start] [gap:10px] [overflow:auto]",
  runItem:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.6] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] hover:[background:var(--surface-card-hover)] grid [gap:6px] [padding:9px_10px] [background:var(--surface-card-muted)] [color:var(--fg-primary)] [text-align:left]",
  runItemActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_8%,_transparent)]",
  runListScrollable:
    "grid [gap:6px] [max-height:min(620px,_58vh)] [overflow:auto] [padding-right:4px]",
  runQueuePanel:
    "min-h-0 [padding:10px_12px] grid [align-content:start] [gap:10px] [overflow:auto]",
  runRecordCard:
    "[gap:10px]",
  runRecordIdentity:
    "grid [gap:3px] min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-family:var(--font-mono)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  runRecordTitleRow:
    "[align-items:flex-start]",
  runRuntimeNote:
    "grid [gap:4px] [padding:8px_10px] [border-radius:8px] [background:var(--surface-card-subtle)] [color:var(--fg-secondary)] [&_p]:[margin:0] [&_p]:[line-height:1.45]",
  runScoreDiagnosis:
    "grid [gap:3px] min-w-0 [padding:8px_10px] [border-radius:8px] [background:var(--surface-card-muted)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[overflow:hidden] [&_p]:[color:var(--fg-primary)] [&_p]:[-webkit-line-clamp:2] [&_p]:[-webkit-box-orient:vertical]",
  runScoreFacts:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] [margin-top:4px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] max-[640px]:[grid-template-columns:1fr]",
  runScorePanel:
    "grid [align-content:center] [gap:6px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.45]",
  runSignalGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:8px] max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[640px]:[grid-template-columns:1fr]",
  runSignalStack:
    "grid [align-content:start] [gap:8px] min-w-0",
  scoreRow:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [&_span]:[color:var(--fg-tertiary)]",
  secondaryPill:
    "inline-flex [align-items:center] [justify-content:center] [max-width:100%] [min-height:28px] [padding:0_10px] [border-radius:999px] [border:1px_solid_var(--border-soft)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis] [color:var(--fg-secondary)] [background:var(--surface-card-muted)]",
  sectionTitle:
    "[margin:3px_0_0] [line-height:1.18] [margin-top:2px] [font-size:0.98rem]",
  selectionBar:
    "flex [align-items:center] [justify-content:space-between] [gap:10px] [flex-wrap:wrap]",
  statusPill:
    "inline-flex [align-items:center] [justify-content:center] [max-width:100%] [min-height:28px] [padding:0_10px] [border-radius:999px] [border:1px_solid_var(--border-soft)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis] [color:var(--accent-warm-2)] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)]",
  structuredEmptyState:
    "grid [align-content:start] [gap:8px] [min-height:86px] [padding:10px_12px] [border-radius:8px] [border:1px_dashed_var(--border-hairline)] [background:var(--surface-card-subtle)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]",
  surface:
    "[border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--surface-panel)] [box-shadow:none]",
};

export default styles;
