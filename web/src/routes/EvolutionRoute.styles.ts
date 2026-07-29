// Wave 8 prune: removed 107 unused keys (EvolutionRoute panel-componentization residue).
// Explicit Tailwind style map converted from the former route stylesheet by
// web/scripts/convert-css-module.mjs (2026-07-02 refined target: one styling
// system). Declarations are Tailwind arbitrary properties
// emitting byte-identical CSS; descendant .a .b rules were flattened onto the
// child key. Edit values directly.
import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)] [box-shadow:none]";
const panelSurfaceSoft =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] !bg-[var(--vui-surface-panel)]";
const rowSurface =
  `${vuiOpaqueRowClass}`;
const rowSurfaceSoft =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] !bg-[var(--vui-surface-row)]";
const actionSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-control-muted)] [color:var(--fg-primary)] [transition:border-color_140ms_ease,_background-color_140ms_ease,_color_140ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] hover:[background:var(--vui-control-muted-hover)]";
const pillSurface =
  "inline-flex [align-items:center] [justify-content:center] [max-width:100%] [min-height:28px] [padding:0_10px] [border-radius:999px] [border:1px_solid_var(--vui-border-subtle)] [background:var(--vui-control-muted)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [overflow:hidden] [text-overflow:ellipsis]";
const compactMetricSurface =
  `grid [gap:3px] min-w-0 ${rowSurfaceSoft} [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-weight:600] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [min-height:36px] [padding:5px_7px]`;

const styles = {
  sourceInventorySection:
    "grid [gap:6px]",
  actionRow:
    "flex [flex-wrap:wrap] [gap:6px]",
  batchToggle:
    "inline-flex [align-items:center] [gap:8px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [&_input]:[width:15px] [&_input]:[height:15px]",
  bulkToolbar:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [flex-wrap:wrap]",
  bulkToolbarText:
    "inline-flex [align-items:center] [gap:8px] [color:var(--fg-secondary)]",
  cardFooter:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [flex-wrap:wrap]",
  cardHeadline:
    "[color:var(--fg-primary)_!important] [font-weight:600]",
  caseConversationFallback:
    "grid [min-height:180px] [place-items:center] [color:var(--fg-secondary)]",
  caseConversationShell:
    "flex [flex:1_1_0] min-h-0 [height:100%] bg-[var(--vui-surface-base)] [background-image:linear-gradient(to_right,color-mix(in_srgb,var(--vui-border-subtle)_24%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--vui-border-subtle)_18%,transparent)_1px,transparent_1px)] [background-size:40px_40px]",
  caseConversationTranscript:
    "[flex:1_1_0] [height:100%] min-h-0 [padding:0_!important] [border:0_!important] [background:transparent_!important] [box-shadow:none_!important]",
  caseOverviewEvidence:
    `grid [grid-template-rows:auto_minmax(120px,_1fr)_auto] [align-content:stretch] [gap:10px] min-w-0 min-h-0 [padding:10px] ${panelSurfaceSoft} [overflow:auto]`,
  caseOverviewEvidenceGrid:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:8px] min-w-0 max-[640px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))]",
  caseOverviewEvidenceItem:
    "grid [gap:3px] min-w-0 [padding-bottom:8px] [border-bottom:1px_solid_var(--border-hairline)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:650] [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[line-height:1.3] [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap]",
  caseOverviewEmptyState: `grid min-w-0 min-h-[120px] [place-items:center] [align-self:stretch] [padding:14px] [border:1px_dashed_var(--vui-border-subtle)] [border-radius:8px] ${vuiOpaqueRowClass} [text-align:center] [&_strong]:min-w-0 [&_strong]:[max-width:100%] [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_span]:[max-width:min(560px,_100%)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.45] [&_span]:[overflow-wrap:anywhere]`,
  caseOverviewGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] min-w-0 max-[640px]:[grid-template-columns:1fr]",
  caseOverviewItem:
    `grid [gap:4px] min-w-0 [padding:8px_10px] ${rowSurfaceSoft} [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:650] [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[line-height:1.35] [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis]`,
  caseOverviewWorkspace:
    "grid [grid-template-rows:auto_minmax(120px,_1fr)] [align-content:stretch] [gap:10px] [flex:1_1_0] min-w-0 min-h-0 [height:100%] [padding:10px] [overflow:auto] bg-[var(--vui-surface-base)] [background-image:linear-gradient(to_right,color-mix(in_srgb,var(--vui-border-subtle)_24%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--vui-border-subtle)_18%,transparent)_1px,transparent_1px)] [background-size:40px_40px]",
  casePreflightIssue:
    "grid [gap:5px] [padding:10px_11px] [border:1px_solid_color-mix(in_srgb,_var(--state-warning)_36%,_var(--border-hairline))] [border-radius:8px] [background:color-mix(in_srgb,_var(--state-warning)_9%,_var(--vui-surface-row))] [color:var(--fg-secondary)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4] [&_span]:[overflow-wrap:anywhere] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.4] [&_small]:[overflow-wrap:anywhere] [&_small]:[color:var(--fg-tertiary)]",
  caseRawEvidence: `[flex:0_0_auto] [overflow:auto] ${vuiOpaqueRowClass} [max-height:none]`,
  caseTraceBody:
    `grid [gap:8px] min-w-0 [margin:0_0_4px_33px] [padding:10px_11px] ${rowSurface}`,
  caseTraceChevron:
    "grid [place-items:center] [min-height:24px] [color:var(--fg-tertiary)]",
  caseTraceIcon:
    "[position:relative] [z-index:1] grid [place-items:center] [width:26px] [height:26px] [margin-top:2px] [border:1px_solid_color-mix(in_srgb,_var(--fg-tertiary)_16%,_transparent)] [border-radius:50%] [background:var(--vui-surface-panel)] [color:var(--state-error)]",
  caseTraceMessage:
    "grid [gap:3px] min-w-0",
  caseTraceMeta:
    "flex [flex-direction:column] [align-items:flex-end] [gap:3px] [padding-top:1px]",
  caseTracePreview:
    "[display:-webkit-box] min-w-0 [overflow:hidden] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.35] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
  caseTraceSection:
    "grid [gap:5px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_span]:[letter-spacing:0.04em] [&_span]:[text-transform:uppercase] [&_pre]:[margin:0] [&_pre]:[white-space:pre-wrap] [&_pre]:[overflow-wrap:anywhere] [&_pre]:[max-height:360px] [&_pre]:[overflow:auto] [&_pre]:[color:var(--fg-secondary)] [&_pre]:[font-size:var(--vui-font-xs)] [&_pre]:[line-height:1.55]",
  caseTraceSectionJson: `[&_pre]:[padding:8px_9px] [&_pre]:[border-radius:6px] [&_pre]:${vuiFlatPanelClass} [&_pre]:[font-family:var(--font-mono)] [&_pre]:[font-size:var(--vui-font-xs)]`,
  caseTraceStack:
    "[position:relative] [z-index:1] flex [flex:1_1_auto] [flex-direction:column] [justify-content:flex-end] [gap:8px] min-w-0 [min-height:min-content]",
  caseTraceStateGrid:
    "grid [gap:7px] min-w-0",
  caseTraceStateRow:
    "[&_dd]:[margin:0] [&_dd]:[white-space:pre-wrap] [&_dd]:[overflow-wrap:anywhere] grid [gap:3px] min-w-0 [margin:0] [&_dt]:[color:var(--fg-tertiary)] [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:[font-weight:700] [&_dt]:[letter-spacing:0.04em] [&_dt]:[text-transform:uppercase] [&_dd]:[color:var(--fg-secondary)] [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:[line-height:1.55]",
  caseTraceStatus: `[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [white-space:nowrap] [padding:1px_5px] [border:1px_solid_color-mix(in_srgb,_var(--fg-tertiary)_14%,_transparent)] [border-radius:999px] ${vuiFlatPanelClass}`,
  caseTraceSummary: `grid w-full [grid-template-columns:26px_minmax(0,_1fr)_auto_18px] [gap:10px] [align-items:start] min-w-0 [min-height:48px] [padding:9px_8px_9px_0] [border:1px_solid_transparent] [border-radius:9px] [color:var(--fg-secondary)] [cursor:pointer] [font:inherit] [text-align:left] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_26%,_transparent)] hover:${vuiOpaqueRowClass} hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_26%,_transparent)] focus-visible:!bg-[var(--vui-surface-row)] focus-visible:[outline:none] [border-left-color:color-mix(in_srgb,_var(--state-error)_58%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_8%,_var(--vui-surface-row))]`,
  caseTraceTime:
    "[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [white-space:nowrap]",
  caseTraceTimeline:
    "[max-height:min(260px,_30vh)] [padding-top:8px] [padding-bottom:8px] flex [align-items:stretch] [flex:1_1_0] min-h-0 [overflow:auto] [padding:8px_6px_12px_30px] [content:\"\"] [position:absolute] [top:10px] [bottom:10px] [left:10px] [width:1px] [background:color-mix(in_srgb,_var(--fg-tertiary)_18%,_transparent)]",
  caseTraceTitle:
    "[color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:650] [white-space:nowrap]",
  caseTraceTurn:
    "grid [gap:4px] min-w-0",
  caseTraceTurn_assistant:
    "[&_.caseTraceIcon]:[color:color-mix(in_srgb,_var(--accent-warm)_80%,_var(--fg-secondary))] [&_.caseTraceSummary]:[border-left-color:color-mix(in_srgb,_var(--accent-warm)_48%,_transparent)]",
  caseTraceTurn_error:
    "[&_.caseTraceIcon]:[color:var(--state-error)] [&_.caseTraceSummary]:[border-left-color:color-mix(in_srgb,_var(--state-error)_58%,_transparent)] [&_.caseTraceSummary]:[background:color-mix(in_srgb,_var(--state-error)_8%,_var(--vui-surface-row))]",
  caseTraceTurn_input: `[&_.caseTraceSummary]:${vuiFlatPanelClass}`,
  caseTraceTurn_thought:
    "[&_.caseTraceIcon]:[color:color-mix(in_srgb,_var(--accent-warm)_80%,_var(--fg-secondary))] [&_.caseTraceSummary]:[border-left-color:color-mix(in_srgb,_var(--accent-warm)_48%,_transparent)]",
  caseTraceTurn_tool:
    "[&_.caseTraceIcon]:[color:color-mix(in_srgb,_var(--accent-cool)_78%,_var(--fg-secondary))] [&_.caseTraceSummary]:[border-left-color:color-mix(in_srgb,_var(--accent-cool)_42%,_transparent)]",
  checkboxLabel:
    "[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)]",
  checkboxRow:
    "inline-flex [align-items:center] [gap:8px] [min-height:26px] [&_input]:[width:16px] [&_input]:[height:16px]",
  closedLoopLaunchBlock:
    "grid [grid-template-columns:minmax(0,_1fr)_minmax(92px,_auto)] [align-items:center] [gap:8px] min-w-0 [padding:7px_9px] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_var(--border-hairline))] [border-radius:7px] [background:color-mix(in_srgb,_var(--accent-warm)_8%,_var(--vui-surface-row))] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_span]:min-w-0 [&_span]:[overflow-wrap:anywhere] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.3] max-[1200px]:[padding:6px_8px]",
  closedLoopModeBadge:
    "[flex:0_0_auto] [padding:2px_6px] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_36%,_var(--border-hairline))] [border-radius:999px] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)] [color:var(--accent-warm-2)] [font-size:var(--vui-font-xs)] [font-weight:740] [line-height:1] [white-space:nowrap]",
  closedLoopTitleRow:
    "inline-flex [align-items:center] [gap:6px] min-w-0",
  collapsibleEvidence:
    "grid [gap:10px] [&_summary]:[outline:0] [background:var(--vui-surface-row)]",
  compactFact:
    `${compactMetricSurface} [align-content:center] [min-height:42px] [padding:7px_8px] [&_span]:[color:var(--fg-secondary)] [&_strong]:[font-size:0.92rem] [&_strong]:[font-weight:650] [&_strong]:[overflow-wrap:anywhere]`,
  compactFieldGrid:
    "grid [grid-template-columns:minmax(0,_1.52fr)_minmax(108px,_0.68fr)] [align-items:start] [gap:8px] min-w-0 max-[1200px]:[grid-template-columns:1fr] max-[1200px]:[gap:6px]",
  compactIconAction:
    `${actionSurface} inline-flex w-9 [align-items:center] [justify-content:center] [gap:7px] [min-height:34px] [width:36px] [padding:0] disabled:[cursor:not-allowed] disabled:[color:var(--fg-tertiary)] disabled:[opacity:0.52]`,
  controlActions:
    "flex [flex-wrap:wrap] [gap:6px] min-w-0",
  controlFooter:
    "grid [gap:6px] min-w-0 max-[1200px]:[gap:6px]",
  dashboardIo:
    "min-w-0 [max-width:100%] [grid-column:3] [grid-row:1] grid [grid-template-rows:auto_minmax(0,_1fr)] [overflow:hidden_!important] max-[1200px]:[grid-column:1_/_-1] max-[1200px]:[grid-row:1] max-[900px]:[grid-column:1] max-[900px]:[grid-row:1]",
  dashboardLaunch:
    "min-w-0 [max-width:100%] [grid-column:1] [grid-row:1] max-[1200px]:[grid-column:1] max-[1200px]:[grid-row:2] max-[900px]:[grid-column:1] max-[900px]:[grid-row:2]",
  dashboardRun:
    "min-w-0 [max-width:100%] [grid-column:5] [grid-row:1] max-[1200px]:[grid-column:2] max-[1200px]:[grid-row:2] max-[900px]:[grid-column:1] max-[900px]:[grid-row:3]",
  datasetCatalogEmpty:
    "[grid-column:1_/_-1] [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.35] [overflow-wrap:anywhere]",
  datasetCatalogFilterButton:
    "[min-height:25px] [padding:0_7px] [border:1px_solid_var(--border-soft)] [border-radius:999px] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [white-space:nowrap]",
  datasetCatalogFilterButtonActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_35%,_var(--border-soft))] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_var(--vui-surface-row))] [color:var(--accent-warm-2)]",
  datasetCatalogFilterRow:
    "flex [flex-wrap:wrap] [gap:4px] min-w-0",
  datasetCatalogBody:
    "grid [gap:7px] min-h-0 [padding:0_8px_8px]",
  datasetCatalogItem:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:4px_8px] min-w-0 [padding:7px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [&_p]:[grid-column:1_/_-1] [&_p]:[margin:0] [&_p]:[color:var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[overflow-wrap:anywhere] [&_span]:[margin-right:6px] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-weight:700]",
  datasetCatalogItemMain:
    "grid [gap:1px] min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  datasetCatalogList:
    "grid [gap:6px] min-h-0 [max-height:min(158px,_20vh)] [overflow:auto] [padding-right:2px]",
  datasetCatalogPanel:
    "min-w-0 [max-height:min(238px,_34vh)] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [overflow:hidden] open:[overflow:auto]",
  datasetCatalogSummary:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [padding:8px] [cursor:pointer] [list-style:none] [&::-webkit-details-marker]:hidden [&>span:first-child]:grid [&>span:first-child]:[gap:2px] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] hover:[background:var(--vui-surface-row-hover)] focus-visible:[outline:1px_solid_color-mix(in_srgb,_var(--accent-cool)_42%,_transparent)]",
  datasetCatalogStatus:
    "[align-self:start] [max-width:116px] [padding:3px_7px] [border:1px_solid_var(--border-soft)] [border-radius:999px] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.2] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  detailHeader:
    "flex [justify-content:space-between] [gap:12px] [align-items:start]",
  detailList:
    "[margin:0] [padding-left:18px] [color:var(--fg-secondary)] grid [gap:8px]",
  detailPanel:
    "min-h-0 [overflow:auto] [padding:12px]",
  detailSection:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.6] grid [border-top:1px_solid_var(--border-hairline)] [gap:6px] [padding-top:10px] [margin-top:10px]",
  detailTitle:
    "[margin:6px_0_0] [font-size:1.08rem]",
  emptyState:
    "grid [place-items:center] [min-height:180px] [color:var(--fg-secondary)] [text-align:center]",
  errorText:
    "[margin:0] [line-height:1.4] [color:var(--state-error)]",
  errorTextCompact:
    "[margin:0] [padding:9px_10px] [border-radius:8px] [line-height:1.45] [overflow-wrap:anywhere] [color:var(--state-error)] [background:color-mix(in_srgb,_var(--state-error)_11%,_transparent)]",
  eyebrow:
    "[margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  feedbackText:
    "[margin:0] [color:var(--fg-secondary)] [line-height:1.55] [white-space:pre-wrap]",
  filterButton:
    "[min-height:26px] [padding:0_8px] [border:0] [border-radius:var(--radius-control)] [background:transparent] [color:var(--fg-secondary)] [transition:background-color_140ms_ease,_color_140ms_ease]",
  filterButtonActive:
    "[background:color-mix(in_srgb,_var(--accent-warm)_16%,_transparent)] [color:var(--accent-warm-2)]",
  filterField:
    "grid [gap:6px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  filterMeta:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [flex-wrap:wrap]",
  filterRow:
    "grid [grid-template-columns:minmax(0,_1.7fr)_repeat(2,_minmax(150px,_1fr))] [gap:10px] max-[1200px]:[grid-template-columns:1fr]",
  filterSegmented:
    "inline-flex [align-items:center] [gap:6px] [padding:3px] [border-radius:var(--radius-panel)] [border:1px_solid_var(--border-soft)] [background:var(--vui-surface-panel)]",
  formField:
    "grid [gap:3px] min-w-0 [&_label]:[color:var(--fg-tertiary)] [&_label]:[font-size:var(--vui-font-xs)]",
  formLabelWithHint:
    "inline-flex [align-items:center] [gap:6px]",
  formGrid:
    "grid [gap:7px]",
  formHint:
    "[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] max-[1200px]:hidden",
  inlineAction:
    `${actionSurface} [justify-self:end] min-w-0 [max-width:100%] inline-flex [align-items:center] [justify-content:center] [gap:8px] [width:fit-content] [min-height:32px] [padding:0_10px] [font-size:var(--vui-font-xs)]`,
  ioContent:
    "[margin:0] [overflow:auto] [white-space:pre-wrap] [overflow-wrap:anywhere] [font-family:Consolas,_\"SFMono-Regular\",_monospace] [font-size:var(--vui-font-xs)] [line-height:1.6] [color:var(--fg-secondary)] [max-height:360px]",
  ioStack:
    "flex [flex-direction:column] [gap:10px] [height:100%] min-h-0",
  ioSurface:
    "[position:relative] [overflow:hidden] grid [grid-template-rows:auto_minmax(0,_1fr)] [align-content:stretch] [gap:8px] [height:100%] min-h-0 [padding:10px_12px_12px] max-[900px]:[height:auto] max-[900px]:min-h-0 max-[900px]:[overflow:visible]",
  launchSurface:
    "[max-height:none] [overflow:auto] grid [align-content:start] [gap:8px] [height:100%] min-h-0 [padding:10px_12px_12px] [font-size:0.9rem] max-[1200px]:[max-height:none] max-[1200px]:[gap:6px] max-[1200px]:[padding:9px_10px] max-[900px]:[height:max-content] max-[900px]:[min-height:max-content] max-[900px]:[overflow:visible]",
  libraryFilters:
    "grid [gap:10px]",
  librarySummaryBar:
    "grid [grid-template-columns:minmax(0,_1.1fr)_minmax(0,_0.9fr)_minmax(0,_1fr)] [gap:8px] [align-items:stretch] min-h-0 max-[1360px]:[grid-template-columns:minmax(0,_1fr)_minmax(0,_0.85fr)_minmax(0,_0.95fr)] max-[1100px]:[grid-template-columns:1fr]",
  libraryViewStack:
    "[grid-template-rows:auto_minmax(0,_1fr)] [height:100%] [overflow:hidden] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] max-[1200px]:[height:auto] max-[1200px]:[overflow:auto]",
  listPanel:
    "min-h-0 [overflow:auto] [padding:12px] grid [align-content:start] [gap:10px]",
  listRowTop:
    "flex [align-items:center] [justify-content:space-between] [gap:12px]",
  liveIoPane:
    "[height:100%] min-h-0 [overflow:auto] [padding-right:4px]",
  // Wave 6A: PaneHeightResizeHandle owns row-resize visual; no route chrome.
  liveIoResizeHandle: "",
  liveLaunchStack:
    "grid [grid-template-rows:minmax(0,_1fr)] [gap:8px] [height:100%] min-h-0 [overflow:hidden] max-[1200px]:[grid-template-rows:minmax(0,_1fr)] max-[900px]:[height:auto] max-[900px]:[overflow:visible] max-[900px]:[grid-template-rows:auto] max-[900px]:[grid-auto-rows:max-content] max-[900px]:[align-content:start] max-[900px]:min-h-0",
  liveResizeHandle:
    "max-[1200px]:hidden",
  liveResizeHandleLaunch:
    "[grid-column:2] [grid-row:1]",
  liveResizeHandleRun:
    "[grid-column:4] [grid-row:1]",
  liveStatusRow:
    "flex [align-items:center] [justify-content:flex-end] [gap:8px] min-w-0 [max-width:min(100%,_320px)] [flex-wrap:wrap]",
  liveSurface:
    "[overflow:auto] grid [align-content:start] [gap:8px] [height:100%] min-h-0 [padding:10px_12px_12px] [font-size:0.9rem] max-[900px]:[height:auto] max-[900px]:min-h-0 max-[900px]:[overflow:visible]",
  masterDetail:
    "grid [grid-template-columns:var(--evolution-library-list-width,_360px)_12px_minmax(0,_1fr)] min-h-0 [height:100%] [overflow:hidden] max-[1200px]:[grid-template-columns:1fr] max-[1200px]:[height:auto] max-[1200px]:[overflow:visible]",
  metaRow:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] [&_span]:[color:var(--fg-tertiary)]",
  metricTile:
    compactMetricSurface,
  noticeText:
    "[color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [margin:0] [display:-webkit-box] [overflow:hidden] [line-height:1.45] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] max-[1200px]:hidden",
  noticeTextCompact:
    `[margin:0] [padding:9px_10px] [line-height:1.45] [overflow-wrap:anywhere] [color:var(--fg-secondary)] ${rowSurfaceSoft}`,
  overviewGrid:
    "grid [grid-template-columns:minmax(300px,_var(--evolution-live-launch-width,_348px))_12px_minmax(360px,_1fr)_12px_minmax(300px,_var(--evolution-live-run-width,_360px))] [grid-template-rows:minmax(0,_1fr)] [grid-auto-rows:minmax(0,_1fr)] [align-items:stretch] [align-content:stretch] min-h-0 [height:100%] [overflow:hidden] [padding-right:4px] max-[1360px]:[grid-template-columns:minmax(292px,_0.92fr)_12px_minmax(360px,_1.32fr)_12px_minmax(292px,_0.9fr)] max-[1360px]:[grid-template-rows:minmax(0,_1fr)] max-[1360px]:[gap:0] max-[1360px]:[overflow:hidden] max-[1200px]:[grid-template-columns:minmax(0,_1fr)_minmax(292px,_0.82fr)] max-[1200px]:[grid-template-rows:minmax(180px,_0.58fr)_minmax(300px,_1fr)] max-[1200px]:[overflow:auto] max-[1200px]:[gap:10px] max-[900px]:[grid-template-columns:1fr] max-[900px]:[grid-template-rows:max-content_max-content_max-content] max-[900px]:[align-content:start] max-[900px]:[height:auto] max-[900px]:[min-height:100%] max-[900px]:[overflow:auto]",
  page:
    "grid [grid-template-rows:auto_minmax(0,_1fr)] [gap:6px] [height:calc(100dvh_-_var(--shell-topbar-height))] [max-height:calc(100dvh_-_var(--shell-topbar-height))] min-h-0 [padding:6px_10px_10px] [overflow:hidden] max-[900px]:[gap:6px] max-[640px]:[padding-inline:10px]",
  paneCollapsed:
    "[padding:0] [border:0] [overflow:hidden] [visibility:hidden]",
  pathText:
    "[overflow-wrap:anywhere] [font-family:Consolas,_\"SFMono-Regular\",_monospace] [font-size:var(--vui-font-xs)]",
  proposalCard:
    "grid [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [gap:8px] [padding:10px_12px]",
  proposalCardButton:
    "grid w-full [gap:8px] [border:0] [padding:0] [text-align:left] [background:transparent] [color:inherit]",
  proposalEditGrid:
    "grid [gap:12px]",
  rawBlock:
    "[border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [padding:10px_12px] min-w-0 [overflow:hidden] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--fg-primary)] [&_summary]:[font-weight:600]",
  rawBlockStack:
    "grid [gap:8px] [width:100%]",
  rawJson:
    "[margin:12px_0_0] [padding:12px] [border-radius:8px] [overflow:auto] [background:var(--vui-surface-workspace)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.55]",
  relatedList:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] max-[900px]:[grid-template-columns:1fr]",
  relatedRow:
    `grid ${rowSurface} [gap:4px] [min-height:48px] [padding:9px_10px]`,
  // Wave 4B: visual rule from PaneCollapseHandle; keep breakpoint hide local.
  resizeHandle:
    "max-[1200px]:hidden",
  reviewLead:
    "[margin:0] [color:var(--fg-primary)_!important] [font-size:1.04rem] [line-height:1.55]",
  runItemActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_8%,_transparent)]",
  runsCommandMetrics:
    "grid [grid-template-columns:repeat(6,_minmax(0,_1fr))] [gap:6px] max-[900px]:[grid-template-columns:repeat(3,_minmax(0,_1fr))] max-[640px]:[grid-template-columns:1fr]",
  runsCommandStrip:
    "grid [grid-template-columns:minmax(220px,_0.42fr)_minmax(0,_1fr)] [gap:10px] [align-items:end] [padding:8px_10px] max-[1200px]:[grid-template-columns:1fr]",
  runsWorkspace:
    "grid [grid-template-columns:var(--evolution-runs-queue-width,_380px)_12px_minmax(0,_1fr)] [align-items:stretch] min-h-0 max-[1200px]:[grid-template-columns:1fr]",
  secondaryPill:
    `${pillSurface} [color:var(--fg-secondary)]`,
  sectionHeadingRow:
    "flex [align-items:center] [justify-content:space-between] [gap:12px] min-w-0",
  sectionTitle:
    "[margin:3px_0_0] [line-height:1.18] [margin-top:2px] [font-size:0.98rem]",
  segmentButton:
    "[min-height:26px] [padding:0_8px] [border:0] [border-radius:var(--radius-control)] [background:transparent] [color:var(--fg-secondary)] [transition:background-color_140ms_ease,_color_140ms_ease]",
  segmentButtonActive:
    "[background:color-mix(in_srgb,_var(--accent-warm)_16%,_transparent)] [color:var(--accent-warm-2)]",
  segmented:
    "inline-flex [align-items:center] [gap:6px] [padding:3px] [border-radius:var(--radius-panel)] [border:1px_solid_var(--border-soft)] [background:var(--vui-surface-panel)]",
  selectInput:
    "[width:100%] min-w-0 [min-height:31px] [padding:0_9px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-workspace)] [color:var(--fg-primary)] focus:[outline:1px_solid_color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] focus:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)]",
  selectionBar:
    "flex [align-items:center] [justify-content:space-between] [gap:10px] [flex-wrap:wrap]",
  selectionSummary:
    "inline-flex [align-items:center] [gap:8px] [color:var(--fg-secondary)]",
  // Self track is the only page child (no route toolbar). One 1fr row fills the
  // viewport; inner trackShell must keep its own auto | 1fr so the status bar
  // stays content-height instead of stretching.
  selfPage:
    "[grid-template-rows:minmax(0,1fr)] [gap:0] [padding:8px_12px_12px] [background:color-mix(in_srgb,_var(--vui-surface-panel)_78%,_var(--vui-surface-workspace))] [min-h-0] [align-content:stretch] max-[900px]:[grid-template-rows:minmax(0,1fr)] max-[900px]:[gap:0]",
  sourceInventoryBar:
    `${rowSurfaceSoft} flex [flex-wrap:wrap] [gap:6px_10px] [padding:4px_8px] min-w-0 [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[gap:6px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)]`,
  sourceMetaCompact:
    `${rowSurfaceSoft} [&_strong]:[color:var(--fg-primary)] grid [grid-template-columns:minmax(0,_1fr)_minmax(96px,_auto)] [align-items:center] [gap:8px] min-w-0 [padding:7px_10px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap]`,
  sourceMetaMain:
    "min-w-0 grid [gap:2px] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  sourceMetaSide:
    "[justify-self:end] [padding:5px_9px] [border:1px_solid_var(--border-soft)] [border-radius:999px] [background:var(--vui-surface-row)] [white-space:nowrap]",
  sourceWarningStrip:
    "[margin:0] [padding:7px_9px] [border:1px_solid_color-mix(in_srgb,_var(--state-warning)_40%,_var(--border-hairline))] [border-radius:7px] [background:color-mix(in_srgb,_var(--state-warning)_10%,_var(--vui-surface-row))] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.36] [overflow-wrap:anywhere]",
  statusLead:
    "[color:var(--fg-primary)] [font-size:0.96rem] [margin:0] [display:-webkit-box] [overflow:hidden] [line-height:1.45] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
  statusMetricGrid:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] max-[900px]:[grid-template-columns:1fr] max-[640px]:[grid-template-columns:1fr]",
  statusPill:
    `${pillSurface} [border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_var(--vui-border-subtle))] [color:var(--accent-warm-2)] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)]`,
  stripItem:
    compactMetricSurface,
  structuredEmptyState: `grid [align-content:start] [gap:8px] [min-height:86px] [padding:10px_12px] [border-radius:8px] [border:1px_dashed_var(--vui-border-subtle)] ${vuiOpaqueRowClass} [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]`,
  summaryMetricStrip:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] max-[900px]:[grid-template-columns:1fr] max-[640px]:[grid-template-columns:1fr]",
  summarySurface:
    "grid [align-content:start] [height:100%] min-h-0 [gap:6px] [padding:8px_10px] max-[1200px]:[grid-template-columns:1fr]",
  supervisedConversationEvidence:
    "grid [gap:8px] [width:100%] min-w-0",
  supervisedConversationTrace:
    `min-w-0 min-h-0 [max-height:min(260px,_30vh)] [overflow:hidden] ${rowSurface}`,
  supervisedMemberIdentity:
    "grid [gap:2px] min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-family:var(--font-mono)] [&_span]:[font-size:var(--vui-font-xs)]",
  supervisedMemberRow:
    "grid [grid-template-columns:minmax(78px,_0.42fr)_minmax(0,_1fr)] [gap:6px] [align-items:center] min-w-0 [min-height:34px] [padding:5px_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:7px] [background:var(--vui-surface-row)]",
  supervisedMembersHeader:
    "flex [align-items:flex-start] [justify-content:space-between] [gap:10px] min-w-0",
  supervisedMembersHeaderActions:
    "inline-flex [align-items:center] [justify-content:flex-end] [gap:6px] min-w-0",
  supervisedMembersList:
    "grid [gap:4px] min-h-0 [max-height:min(118px,_22vh)] [overflow:auto] [@container(min-width:560px)]:[max-height:min(238px,_34vh)] max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))] max-[900px]:[overflow:visible]",
  supervisedMembersPanel:
    "grid [gap:6px] [align-self:start] min-h-0 [padding:8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [overflow:hidden] max-[900px]:[max-height:none]",
  supervisedRunConsole:
    "[container-type:inline-size] [grid-auto-rows:max-content]",
  supervisedRunConsoleGrid:
    "grid [grid-template-columns:minmax(0,_1fr)] [grid-auto-rows:max-content] [align-content:start] [gap:7px] min-h-0 [@container(min-width:560px)]:[grid-template-columns:minmax(0,_1.08fr)_minmax(214px,_0.72fr)] [@container(min-width:560px)]:[align-items:start]",
  supervisedRunConsoleHeader:
    "[align-items:flex-start]",
  supervisedRunConsoleStatus:
    "inline-flex [flex-wrap:wrap] [justify-content:flex-end] [gap:5px] min-w-0",
  supervisedRunOptions:
    "grid [grid-template-columns:minmax(0,_0.95fr)_minmax(126px,_1.05fr)] [gap:6px] [align-items:end] min-w-0 [@container(min-width:560px)]:[grid-template-columns:max-content_minmax(140px,_1fr)] [@container(max-width:430px)]:[grid-template-columns:1fr]",
  supervisedRunPlan:
    "grid [align-content:center] [gap:14px] [min-height:100%] [padding:18px] [background:var(--vui-surface-base)] [background-image:linear-gradient(to_right,color-mix(in_srgb,var(--vui-border-subtle)_22%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--vui-border-subtle)_16%,transparent)_1px,transparent_1px)] [background-size:40px_40px]",
  supervisedRunPlanGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] min-w-0 max-[640px]:[grid-template-columns:1fr] [&_article]:grid [&_article]:[gap:4px] [&_article]:min-w-0 [&_article]:[padding:10px_11px] [&_article]:[border:1px_solid_var(--vui-border-subtle)] [&_article]:[border-radius:8px] [&_article]:[background:var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)]",
  supervisedRunPlanHint:
    "[margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.45] [text-align:center]",
  supervisedRunPlanLead:
    "grid [justify-items:center] [gap:7px] [text-align:center] [&_h3]:[margin:0] [&_h3]:[color:var(--fg-primary)] [&_h3]:[font-size:1rem] [&_p]:[margin:0] [&_p]:[max-width:620px] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.55]",
  supervisedRunSetup:
    "grid [align-content:start] [gap:7px] min-w-0 min-h-0",
  supervisedWorkflowFollowButton:
    "[min-height:24px] [padding:0_8px] [border:1px_solid_var(--border-hairline)] [border-radius:999px] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font:inherit] [font-size:var(--vui-font-xs)] [line-height:1] [white-space:nowrap] [cursor:pointer] [transition:border-color_120ms_ease,_background_120ms_ease,_color_120ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_42%,_var(--border-soft))] hover:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_var(--vui-surface-row))] hover:[color:var(--accent-cool-2)] hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_42%,_var(--border-soft))] focus-visible:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_var(--vui-surface-row))] focus-visible:[color:var(--accent-cool-2)] focus-visible:[outline:none]",
  supervisedWorkflowPanel:
    `grid [gap:8px] [align-self:start] min-h-0 [padding:8px] ${rowSurfaceSoft} [overflow:hidden] max-[900px]:[max-height:none]`,
  supervisedWorkflowSessionLink:
    "inline-flex [align-items:center] [gap:3px] min-w-0 [color:var(--accent-cool-2)] [text-decoration:none] [white-space:nowrap] hover:[color:var(--accent-cool)] hover:[text-decoration:underline] hover:[outline:none] focus-visible:[color:var(--accent-cool)] focus-visible:[text-decoration:underline] focus-visible:[outline:none]",
  surface:
    panelSurface,
  surfaceHeaderCompact:
    "flex [justify-content:space-between] [gap:10px] min-w-0 [&_div]:min-w-0 [align-items:center]",
  textArea:
    "[width:100%] min-w-0 [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-workspace)] [color:var(--fg-primary)] focus:[outline:1px_solid_color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] focus:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] [min-height:86px] [padding:10px_12px] [resize:vertical] [line-height:1.5]",
  textInput:
    "[width:100%] min-w-0 [min-height:31px] [padding:0_9px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-workspace)] [color:var(--fg-primary)] focus:[outline:1px_solid_color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)] focus:[border-color:color-mix(in_srgb,_var(--accent-warm)_26%,_transparent)]",
  toolbar:
    "flex [align-items:center] [justify-content:space-between] [gap:8px_12px] [flex-wrap:wrap] min-w-0 max-[1200px]:[align-items:flex-start] max-[900px]:grid max-[900px]:[grid-template-columns:1fr] max-[900px]:[gap:6px]",
  toolbarControls:
    "flex [align-items:center] [justify-content:flex-end] [gap:6px] [flex-wrap:nowrap] min-w-0 max-w-full max-[1200px]:[min-width:min(500px,_100%)] max-[900px]:[justify-content:stretch] max-[900px]:min-w-0 max-[900px]:[width:100%] max-[900px]:[overflow-x:auto] max-[900px]:[scrollbar-width:thin] max-[640px]:[justify-content:flex-start]",
  // Content-sized row for supervised focus toolbar — never grow into a tall empty shell.
  toolbarControlsSupervisedFocus:
    "flex flex-nowrap items-center justify-end gap-2 w-fit max-w-full min-w-0 shrink-0 overflow-x-auto [scrollbar-width:thin]",
  // Standalone supervised focus chrome: do NOT also apply `toolbar` (flex-wrap + full row)
  // on top of VRouteHeader hideIntro — that reintroduced full-width empty bands.
  toolbarSupervisedFocus:
    "!flex w-fit max-w-full min-w-0 flex-nowrap items-center justify-end gap-2 justify-self-end self-start",
  truncateText:
    "min-w-0 [max-width:100%] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  viewStack:
    "grid [gap:16px] [align-content:start] min-h-0 [overflow:auto] [padding-right:4px]",
  workflowStepButton:
    "grid w-full [gap:3px] min-w-0 [padding:7px_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:7px] [background:var(--vui-surface-row)] [color:inherit] [font:inherit] [text-align:left] [cursor:pointer] [transition:border-color_120ms_ease,_background_120ms_ease] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_42%,_var(--vui-border-subtle))] hover:[background:var(--vui-surface-row-hover)] hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_42%,_var(--vui-border-subtle))] focus-visible:[background:var(--vui-surface-row-hover)] focus-visible:[outline:none] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:750] [&_strong]:[white-space:nowrap]",
  workflowStepButtonActive:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_54%,_var(--border-soft))] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_var(--vui-surface-panel))]",
  workflowStepItem:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:stretch] [gap:5px] min-w-0 max-[640px]:[grid-template-columns:1fr]",
  workflowStepItemCurrent:
    "[color:var(--accent-warm-2)]",
  workflowStepMeta:
    "min-w-0 [overflow:hidden] [text-overflow:ellipsis] flex [align-items:center] [justify-content:space-between] [gap:6px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:650] [line-height:1.2] [white-space:nowrap]",
  workflowStepPreview:
    "min-w-0 [overflow:hidden] [text-overflow:ellipsis] [display:-webkit-box] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.35] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
  workflowStepRail:
    "grid [gap:5px] min-w-0 [max-height:min(196px,_30vh)] [overflow:auto] max-[900px]:[max-height:none] max-[900px]:[overflow:visible]",
} as const;

export default styles;
