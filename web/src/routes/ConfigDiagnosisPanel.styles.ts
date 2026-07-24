const panelSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_94%,var(--fg-primary)_6%)] [border-radius:var(--radius-panel)] [background:var(--vui-surface-panel)] [box-shadow:0_10px_28px_color-mix(in_srgb,var(--fg-primary)_8%,transparent)]";
const rowSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_96%,var(--fg-primary)_4%)] [border-radius:8px] [background:var(--vui-surface-row)]";

const styles = {
  actionButton: "vui-routes-configdiagnosispanel actionButton min-h-10 px-3.5 [font-size:var(--vui-font-sm)] font-semibold",
  affectedDetails: `vui-routes-configdiagnosispanel affectedDetails ${rowSurface} [padding:8px_10px] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--vui-fg-secondary)] [&_summary]:[font-size:var(--vui-font-xs)] [&_summary]:[font-weight:650]`,
  affectedList: "vui-routes-configdiagnosispanel affectedList [display:flex] [gap:6px] [flex-wrap:wrap] [margin:8px_0_0] [padding:0] [list-style:none]",
  affectedPill: "vui-routes-configdiagnosispanel affectedPill [display:inline-flex] [min-height:24px] [align-items:center] [padding:0_8px] [border-radius:999px] [background:var(--vui-surface-row)] [color:var(--vui-fg-secondary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)]",
  blockerCard: `vui-routes-configdiagnosispanel blockerCard ${rowSurface} [display:grid] [gap:10px] [min-width:0] [padding:12px] [border-color:color-mix(in_srgb,var(--state-error)_24%,var(--vui-border-subtle))]`,
  blockerHeader: "vui-routes-configdiagnosispanel blockerHeader [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:12px] [&_h3]:[margin:3px_0_0] [&_h3]:[color:var(--vui-fg-primary)] [&_h3]:[font-size:0.96rem] [&_h3]:[line-height:1.4] [&_h3]:[overflow-wrap:anywhere]",
  blockerList: "vui-routes-configdiagnosispanel blockerList [display:grid] [gap:10px]",
  content: "vui-routes-configdiagnosispanel diagnosticsGrid [display:grid] [align-content:start] [gap:10px] [min-width:0]",
  eyebrow: "vui-routes-configdiagnosispanel eyebrow [margin:0] [color:var(--state-error)] [font-size:var(--vui-font-xs)] [font-weight:700] [text-transform:uppercase] [letter-spacing:0.06em]",
  helperText: "vui-routes-configdiagnosispanel helperText [margin:0] [color:var(--vui-fg-secondary)] [font-size:var(--vui-font-sm)] [line-height:1.45]",
  issueList: "vui-routes-configdiagnosispanel issueList [display:grid] [gap:7px] [margin:0] [padding:0] [list-style:none] [&_li]:[min-width:0] [&_li]:[padding:8px_10px] [&_li]:[border-radius:7px] [&_li]:[background:var(--vui-surface-row)] [&_li]:[color:var(--vui-fg-secondary)] [&_li]:[font-size:var(--vui-font-sm)] [&_li]:[overflow-wrap:anywhere]",
  metricCard: `vui-routes-configdiagnosispanel metricCard ${rowSurface} [display:flex] [align-items:baseline] [gap:8px] [min-width:0] [padding:10px_12px] [&_strong]:[color:var(--vui-fg-primary)] [&_strong]:[font-family:var(--font-display)] [&_strong]:[font-size:1.45rem] [&_strong]:[line-height:1] [&_span]:[color:var(--vui-fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:650]`,
  sectionHeader: "vui-routes-configdiagnosispanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] [border-bottom:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_96%,var(--fg-primary)_4%)] [background:var(--vui-surface-toolbar)]",
  sectionIcon: "vui-routes-configdiagnosispanel sectionIcon [color:var(--state-error)]",
  sectionSurface: `vui-routes-configdiagnosispanel sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.diagnosticsGrid]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)]`,
  sectionText: "vui-routes-configdiagnosispanel sectionText [margin:0] [color:var(--vui-fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.45]",
  summaryGrid: "vui-routes-configdiagnosispanel summaryGrid [display:grid] [grid-template-columns:repeat(3,minmax(0,1fr))] [gap:8px]",
  supportCard: `vui-routes-configdiagnosispanel supportCard ${rowSurface} [display:grid] [align-content:start] [gap:8px] [min-width:0] [padding:12px]`,
  supportGrid: "vui-routes-configdiagnosispanel supportGrid [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [align-items:start] [gap:10px]",
  supportTitle: "vui-routes-configdiagnosispanel supportTitle [margin:0] [color:var(--vui-fg-primary)] [font-size:var(--vui-font-sm)] [font-weight:700]",
} as const;

export default styles;
