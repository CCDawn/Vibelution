const panelSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_94%,var(--fg-primary)_6%)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [box-shadow:0_10px_28px_color-mix(in_srgb,var(--fg-primary)_8%,transparent)]";
const sectionHeaderSurface =
  "[border-bottom:1px_solid_var(--vui-border-subtle)] [background:color-mix(in_srgb,var(--vui-surface-toolbar)_72%,transparent)]";

const styles = {
  detailCard:
    `vui-routes-configoverviewpanel detailCard ${panelSurface} [display:grid] [gap:8px] [padding:14px] [align-content:center] [min-height:96px] [&>_span]:[color:var(--vui-fg-tertiary)] [&>_span]:[font-size:var(--vui-font-sm)] [&>_span]:[font-weight:650] [&>_strong]:[color:var(--vui-fg-primary)] [&>_strong]:[font-size:1.45rem] [&>_strong]:[overflow-wrap:anywhere] [&[data-summary-tone=error]]:[border-color:color-mix(in_srgb,var(--state-error)_34%,var(--vui-border-subtle))] [&[data-summary-tone=warning]]:[border-color:color-mix(in_srgb,var(--state-warning)_34%,var(--vui-border-subtle))]`,
  eyebrow:
    "vui-routes-configoverviewpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  summaryGrid:
    "vui-routes-configoverviewpanel summaryGrid [display:grid] [gap:12px] [grid-template-columns:repeat(3,minmax(0,1fr))]",
  sectionHeader:
    `vui-routes-configoverviewpanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionIcon:
    "vui-routes-configoverviewpanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    `vui-routes-configoverviewpanel sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:12px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-sm)] [&>_.summaryGrid]:[margin:12px_var(--config-section-x)_var(--config-section-x)]`,
  sectionText:
    "vui-routes-configoverviewpanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configoverviewpanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
};

export default styles;
