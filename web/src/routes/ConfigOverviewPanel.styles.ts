const styles = {
  actionButton:
    "vui-routes-configoverviewpanel actionButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_var(--border-soft)] [background:var(--surface-card-subtle)] [color:var(--fg-primary)] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--surface-card)_14%,transparent)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]",
  actionsRow:
    "vui-routes-configoverviewpanel actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  detailCard:
    "vui-routes-configoverviewpanel detailCard [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--vui-gradient-route-soft),var(--surface-panel)] [box-shadow:none] [display:grid] [gap:6px] [padding:8px] [align-content:center] [min-height:48px] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)] [&>_span]:[font-weight:600] [&>_strong]:[color:var(--fg-primary)] [&>_strong]:[font-size:0.98rem] [&>_strong]:[overflow-wrap:anywhere]",
  eyebrow:
    "vui-routes-configoverviewpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  hashGrid:
    "vui-routes-configoverviewpanel hashGrid [display:grid] [gap:8px] [grid-template-columns:minmax(280px,1.4fr)_minmax(180px,0.6fr)] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  hashValue:
    "vui-routes-configoverviewpanel hashValue [overflow:auto] [overflow-wrap:anywhere] [font-family:Consolas,'SFMono-Regular',monospace] [font-size:var(--vui-font-xs)] [color:var(--fg-primary)]",
  helperText:
    "vui-routes-configoverviewpanel helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  rawConfigPanel:
    "vui-routes-configoverviewpanel rawConfigPanel [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.38] [display:grid] [gap:6px] [padding:7px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--surface-card-muted)] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--fg-primary)] [&_summary]:[font-weight:600]",
  rawToml:
    "vui-routes-configoverviewpanel rawToml [overflow:auto] [overflow-wrap:anywhere] [font-family:Consolas,'SFMono-Regular',monospace] [font-size:var(--vui-font-xs)] [margin:0] [padding:8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--surface-code)] [color:var(--fg-secondary)] [line-height:1.55]",
  sectionHeader:
    "vui-routes-configoverviewpanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] [border-bottom:1px_solid_var(--border-hairline)] [background:var(--vui-gradient-route-soft),var(--surface-panel)]",
  sectionIcon:
    "vui-routes-configoverviewpanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    "vui-routes-configoverviewpanel sectionSurface [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--vui-gradient-route-soft),var(--surface-panel)] [box-shadow:none] [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.hashGrid,.actionsRow,.rawConfigPanel_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.hashGrid,.actionsRow,.rawConfigPanel_)]:[margin-top:6px]",
  sectionText:
    "vui-routes-configoverviewpanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configoverviewpanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
};

export default styles;
