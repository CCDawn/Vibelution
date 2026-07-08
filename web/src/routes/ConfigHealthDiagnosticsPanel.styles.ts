const panelSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--surface-panel)_96%,var(--surface-page))] [box-shadow:var(--vui-shadow-hairline)]";
const rowSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] [background:color-mix(in_srgb,var(--surface-card)_94%,var(--surface-page))]";
const mutedControl =
  "[display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_var(--vui-border-soft)] [background:var(--vui-control-muted)] [color:var(--vui-fg-primary)] hover:[cursor:pointer] hover:[border-color:var(--vui-border-soft)] hover:[background:var(--vui-control-muted-hover)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]";
const sectionHeaderSurface =
  "[border-bottom:1px_solid_var(--vui-border-subtle)] [background:color-mix(in_srgb,var(--vui-surface-toolbar)_72%,transparent)]";

const styles = {
  actionButton: `vui-routes-configroute actionButton ${mutedControl}`,
  actionsRow: "vui-routes-configroute actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  cardBadges: "vui-routes-configroute cardBadges [display:flex] [align-items:center] [gap:8px] [flex-wrap:wrap]",
  cardSubtle: "vui-routes-configroute cardSubtle [margin:0] [color:var(--fg-secondary)] [line-height:1.38] [min-width:0] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  cardTitle: "vui-routes-configroute cardTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.96rem] [font-weight:600] [min-width:0] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  eyebrow: "vui-routes-configroute eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  findingCard: `vui-routes-configroute findingCard ${rowSurface} [display:grid] [gap:10px] [padding:12px]`,
  findingEvidence: "vui-routes-configroute findingEvidence [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:8px] [&_span]:[min-width:0] [&_span]:[padding:9px] [&_span]:[border:1px_solid_var(--vui-border-subtle)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[display:grid] [&_span]:[gap:4px] [&_span]:[color:var(--vui-fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow-wrap:anywhere] [&_strong]:[color:var(--vui-fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600] [&_strong]:[text-transform:uppercase] [&_strong]:[letter-spacing:0.06em] max-[720px]:[grid-template-columns:1fr]",
  findingHeader: "vui-routes-configroute findingHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] [&_h4]:[margin:0] [&_h4]:[color:var(--fg-primary)] [&_h4]:[margin-top:4px] [&_h4]:[font-size:0.94rem]",
  findingList: "vui-routes-configroute findingList [display:grid] [gap:10px]",
  findingRecommendation: `vui-routes-configroute findingRecommendation [min-width:0] [padding:9px] ${rowSurface} [&_strong]:[color:var(--vui-fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600] [&_strong]:[text-transform:uppercase] [&_strong]:[letter-spacing:0.06em] [display:grid] [gap:5px] [margin:0] [color:var(--vui-fg-secondary)] [font-size:var(--vui-font-xs)]`,
  healthBadgeBlocked: "vui-routes-configroute healthBadgeBlocked [color:var(--state-error)] [background:color-mix(in_srgb,var(--state-error)_14%,transparent)] [border-color:color-mix(in_srgb,var(--state-error)_26%,transparent)]",
  healthMetric: "vui-routes-configroute healthMetric [color:var(--fg-primary)] [font-family:var(--font-display)] [font-size:1.8rem] [line-height:1]",
  healthPanel: "vui-routes-configroute healthPanel [display:grid] [align-content:start] [gap:10px] [min-width:0]",
  healthPanelHeader: "vui-routes-configroute healthPanelHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] [&_h3]:[margin:0] [&_h3]:[color:var(--fg-primary)] [&_h3]:[font-size:0.96rem]",
  healthSummaryGrid: "vui-routes-configroute healthSummaryGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  healthWorkbenchGrid: "vui-routes-configroute healthWorkbenchGrid [display:grid] [grid-template-columns:minmax(0,1.35fr)_minmax(280px,0.65fr)] [gap:12px] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  helperText: "vui-routes-configroute helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  inlineBadge: "vui-routes-configroute inlineBadge [display:inline-flex] [align-items:center] [justify-content:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [border:1px_solid_transparent] [font-size:var(--vui-font-xs)] [white-space:nowrap] [color:var(--fg-secondary)] [background:var(--vui-surface-row)]",
  inlineBadgeWarning: "vui-routes-configroute inlineBadgeWarning [color:var(--accent-warm-2)] [background:color-mix(in_srgb,var(--accent-warm)_12%,transparent)] [border-color:color-mix(in_srgb,var(--accent-warm)_22%,transparent)]",
  logHelperCard: `vui-routes-configroute logHelperCard [display:grid] [gap:6px] [padding:8px] [align-content:start] ${rowSurface}`,
  logHelperGrid: "vui-routes-configroute logHelperGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  logHelperHeader: "vui-routes-configroute logHelperHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] max-[1120px]:[align-items:stretch] max-[1120px]:[flex-direction:column]",
  logHelperMetaGrid: "vui-routes-configroute logHelperMetaGrid [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] [gap:8px] [&_span]:[min-width:0] [&_span]:[padding:10px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[display:grid] [&_span]:[gap:4px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem] [&_strong]:[overflow-wrap:anywhere] max-[720px]:[grid-template-columns:1fr]",
  logHelperSignal: `vui-routes-configroute logHelperSignal [min-width:0] [padding:10px] ${rowSurface} [display:grid] [gap:6px] [&_span]:[color:var(--vui-fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--vui-fg-primary)] [&_strong]:[overflow-wrap:anywhere]`,
  matrixCard: `vui-routes-configroute matrixCard ${panelSurface} [display:grid] [gap:6px] [padding:8px]`,
  matrixTitle: "vui-routes-configroute matrixTitle [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.06em]",
  quickActionItem: `vui-routes-configroute quickActionItem ${rowSurface} [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:center] [gap:10px] [padding:11px] [color:inherit] [text-decoration:none] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_32%,transparent)] hover:[background:var(--vui-surface-row-hover)] [&_div]:[display:grid] [&_div]:[gap:6px] [&_div]:[min-width:0] [&_strong]:[overflow-wrap:anywhere] [&_small]:[overflow-wrap:anywhere] [&_strong]:[color:var(--vui-fg-primary)] [&_strong]:[font-size:0.9rem] [&_small]:[color:var(--vui-fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.45]`,
  quickActionList: "vui-routes-configroute quickActionList [display:grid] [gap:10px]",
  sectionHeader: `vui-routes-configroute sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionHeaderActions: "vui-routes-configroute sectionHeaderActions [display:flex] [align-items:center] [justify-content:end] [gap:6px] [flex-wrap:wrap]",
  sectionHeaderMain: "vui-routes-configroute sectionHeaderMain [display:grid] [gap:3px] [min-width:0]",
  sectionSurface: `vui-routes-configroute sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.diagnosticsGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap,.agentRunPanel_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.diagnosticsGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap_)]:[margin-top:6px]`,
  sectionText: "vui-routes-configroute sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle: "vui-routes-configroute sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.92rem] [line-height:1.15]",
  statusBadgeReady: "vui-routes-configroute statusBadgeReady [color:var(--state-success)] [background:color-mix(in_srgb,var(--accent-cool)_14%,transparent)] [border-color:color-mix(in_srgb,var(--accent-cool)_26%,transparent)]",
} as const;

export default styles;
