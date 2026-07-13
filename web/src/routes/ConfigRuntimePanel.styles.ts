const panelSurface =
  "[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_94%,var(--fg-primary)_6%)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))] [box-shadow:0_10px_28px_color-mix(in_srgb,var(--fg-primary)_8%,transparent)]";
const mutedControl =
  "[display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_transparent] [background:transparent] [color:var(--vui-fg-secondary)] hover:[cursor:pointer] hover:[color:var(--vui-fg-primary)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]";
const activeControl =
  "[background:color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-control-muted))] [border-color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] [color:var(--accent-warm-2)]";
const sectionHeaderSurface =
  "[border-bottom:1px_solid_var(--vui-border-subtle)] [background:color-mix(in_srgb,var(--vui-surface-toolbar)_72%,transparent)]";

const styles = {
  behaviorCopy:
    "vui-routes-configruntimepanel behaviorCopy [display:grid] [gap:4px] [min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:[font-weight:700] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  behaviorRow:
    "vui-routes-configruntimepanel behaviorRow [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:center] [gap:24px] [padding:14px_var(--config-section-x)] [background:color-mix(in_srgb,var(--surface-card)_76%,var(--surface-panel))]",
  sectionHeader:
    `vui-routes-configruntimepanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionIcon:
    "vui-routes-configruntimepanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    `vui-routes-configruntimepanel sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible]`,
  segmented:
    "vui-routes-configruntimepanel segmented [display:inline-flex] [align-items:center] [justify-self:end] [gap:6px] [padding:4px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--control-radius)] [background:var(--vui-surface-toolbar)]",
  segmentButton:
    `vui-routes-configruntimepanel segmentButton ${mutedControl} min-w-28 min-h-10 px-4`,
  segmentButtonActive:
    `vui-routes-configruntimepanel segmentButtonActive ${activeControl}`,
};

export default styles;
