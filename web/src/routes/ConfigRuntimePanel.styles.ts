const styles = {
  eyebrow:
    "vui-routes-configruntimepanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  matrixCard:
    "vui-routes-configruntimepanel matrixCard [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--vui-gradient-route-soft),var(--surface-panel)] [box-shadow:none] [display:grid] [gap:6px] [padding:8px]",
  matrixGrid:
    "vui-routes-configruntimepanel matrixGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  matrixTitle:
    "vui-routes-configruntimepanel matrixTitle [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.06em]",
  sectionHeader:
    "vui-routes-configruntimepanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] [border-bottom:1px_solid_var(--border-hairline)] [background:var(--vui-gradient-route-soft),var(--surface-panel)]",
  sectionIcon:
    "vui-routes-configruntimepanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    "vui-routes-configruntimepanel sectionSurface [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--vui-gradient-route-soft),var(--surface-panel)] [box-shadow:none] [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.matrixGrid_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.matrixGrid_)]:[margin-top:6px]",
  sectionText:
    "vui-routes-configruntimepanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configruntimepanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
  segmented:
    "vui-routes-configruntimepanel segmented [display:inline-flex] [align-items:center] [gap:4px] [padding:3px] [border:1px_solid_var(--border-soft)] [border-radius:999px] [background:color-mix(in_srgb,var(--surface-panel)_82%,transparent)] [flex-wrap:wrap]",
  segmentButton:
    "vui-routes-configruntimepanel segmentButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_transparent] [background:transparent] [color:var(--fg-secondary)] hover:[cursor:pointer] hover:[color:var(--fg-primary)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]",
  segmentButtonActive:
    "vui-routes-configruntimepanel segmentButtonActive [background:color-mix(in_srgb,var(--accent-cool)_15%,transparent)] [border-color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] [color:var(--accent-warm-2)]",
};

export default styles;
