const styles = {
  actionButton:
    "vui-routes-configdraftpanel actionButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_var(--border-soft)] [background:var(--surface-card-subtle)] [color:var(--fg-primary)] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--surface-card)_14%,transparent)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]",
  actionsRow:
    "vui-routes-configdraftpanel actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  editorWrap:
    "vui-routes-configdraftpanel editorWrap [min-height:360px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [overflow:hidden] [background:var(--surface-code)] [&.cm-editor]:[height:100%] [&.cm-editor]:[min-height:360px] [&.cm-scroller]:[overflow:auto]",
  eyebrow:
    "vui-routes-configdraftpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  helperText:
    "vui-routes-configdraftpanel helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionHeader:
    "vui-routes-configdraftpanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] [border-bottom:1px_solid_var(--border-hairline)] [background:var(--vui-gradient-route-soft),var(--surface-panel)]",
  sectionIcon:
    "vui-routes-configdraftpanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    "vui-routes-configdraftpanel sectionSurface [border:1px_solid_var(--border-soft)] [border-radius:var(--radius-panel)] [background:var(--vui-gradient-route-soft),var(--surface-panel)] [box-shadow:none] [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.actionsRow,.editorWrap_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.actionsRow,.editorWrap_)]:[margin-top:6px]",
  sectionText:
    "vui-routes-configdraftpanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configdraftpanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
};

export default styles;
