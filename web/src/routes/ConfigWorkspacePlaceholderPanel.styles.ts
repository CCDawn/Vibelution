const panelSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_94%,var(--fg-primary)_6%)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [box-shadow:0_10px_28px_color-mix(in_srgb,var(--fg-primary)_8%,transparent)]";
const rowSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_96%,var(--fg-primary)_4%)] [border-radius:8px] [background:color-mix(in_srgb,var(--surface-card)_94%,var(--surface-panel))]";

const styles = {
  eyebrow: "vui-routes-configroute eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  loadingBoard: `vui-routes-configroute loadingBoard ${panelSurface} [display:grid] [grid-template-rows:auto_auto_minmax(0,1fr)] [align-content:start] [gap:8px] [padding:10px] [min-width:0] [overflow:hidden]`,
  loadingBoardHeader: "vui-routes-configroute loadingBoardHeader [display:grid] [grid-template-columns:minmax(180px,0.9fr)_minmax(100px,0.32fr)_minmax(100px,0.32fr)] [gap:7px] [&_span]:[display:block] [&_span]:[border-radius:6px] [&_span]:[background:var(--vui-gradient-route-soft)] [&_span]:[min-height:32px] max-[720px]:[grid-template-columns:1fr]",
  loadingMetricGrid: "vui-routes-configroute loadingMetricGrid [&_strong]:[display:block] [&_strong]:[border-radius:6px] [&_strong]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] [gap:7px] [&_span]:[display:grid] [&_span]:[gap:5px] [&_span]:[min-height:54px] [&_span]:[padding:8px] [&_span]:[border:1px_solid_var(--vui-border-subtle)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_small]:[color:var(--vui-fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[text-transform:uppercase] [&_strong]:[min-height:16px] max-[1120px]:[grid-template-columns:repeat(2,minmax(0,1fr))] max-[520px]:[grid-template-columns:1fr]",
  loadingNavActive: "vui-routes-configroute loadingNavActive",
  loadingNavList: "vui-routes-configroute loadingNavList [display:grid] [gap:8px] [margin-top:4px] [&_span]:[display:flex] [&_span]:[align-items:center] [&_span]:[min-height:44px] [&_span]:[padding:0_12px] [&_span]:[border:1px_solid_var(--vui-border-subtle)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[color:var(--vui-fg-secondary)] [&_span]:[font-size:var(--vui-font-sm)] [&_.loadingNavActive]:[border-color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] [&_.loadingNavActive]:[background:color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] [&_.loadingNavActive]:[color:var(--accent-warm-2)]",
  loadingNavPanel: `vui-routes-configroute loadingNavPanel ${panelSurface} [display:grid] [align-content:start] [gap:8px] [padding:10px] [min-height:0]`,
  loadingShell: "vui-routes-configroute loadingShell [grid-column:1/-1] [display:grid] [grid-template-columns:minmax(240px,var(--sidebar-width,306px))_minmax(0,1fr)] [gap:6px] [min-height:0] [height:100%] max-[1120px]:[grid-template-columns:1fr]",
  loadingShellError: "vui-routes-configroute loadingShellError [&_.loadingNavPanel]:[border-color:color-mix(in_srgb,var(--state-error)_28%,transparent)] [&_.loadingBoard]:[border-color:color-mix(in_srgb,var(--state-error)_28%,transparent)]",
  loadingSpecGrid: "vui-routes-configroute loadingSpecGrid [&_span]:[display:block] [&_span]:[border-radius:6px] [&_span]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:7px] [&_span]:[min-height:76px] max-[720px]:[grid-template-columns:1fr]",
  subtitle: "vui-routes-configroute subtitle [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  title: "vui-routes-configroute title [margin:0] [font-family:var(--font-body)] [font-weight:760] [font-size:var(--route-topbar-title-size)] [line-height:1.1]",
} as const;

export default styles;
