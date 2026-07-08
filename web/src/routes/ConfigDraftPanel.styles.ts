const readablePanelSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,var(--surface-panel)_96%,var(--surface-page))] [box-shadow:var(--vui-shadow-hairline)]";
const readableRowSurface =
  "[border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] [background:color-mix(in_srgb,var(--surface-card)_94%,var(--surface-page))]";
const mutedControl =
  "[display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_var(--vui-border-soft)] [background:var(--vui-control-muted)] [color:var(--vui-fg-primary)] hover:[cursor:pointer] hover:[border-color:var(--vui-border-soft)] hover:[background:var(--vui-control-muted-hover)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]";
const sectionHeaderSurface =
  "[border-bottom:1px_solid_var(--vui-border-subtle)] [background:color-mix(in_srgb,var(--vui-surface-toolbar)_72%,transparent)]";

const styles = {
  actionButton:
    `vui-routes-configdraftpanel actionButton ${mutedControl}`,
  actionsRow:
    "vui-routes-configdraftpanel actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  draftActionRail:
    `vui-routes-configdraftpanel draftActionRail ${readableRowSurface} [display:grid] [grid-template-columns:auto_auto_minmax(0,1fr)] [align-items:center] [gap:6px] [padding:7px] max-[760px]:[grid-template-columns:1fr]`,
  draftWorkbench:
    `vui-routes-configdraftpanel draftWorkbench ${readableRowSurface} [display:grid] [gap:6px] [padding:7px] [max-height:min(520px,_54vh)] [overflow:hidden]`,
  editorWrap:
    "vui-routes-configdraftpanel editorWrap [min-height:260px] [max-height:min(430px,_44vh)] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [overflow:hidden] [background:var(--surface-code)] [&.cm-editor]:[height:100%] [&.cm-editor]:[min-height:260px] [&.cm-scroller]:[overflow:auto]",
  eyebrow:
    "vui-routes-configdraftpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  helperText:
    "vui-routes-configdraftpanel helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionHeader:
    `vui-routes-configdraftpanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionIcon:
    "vui-routes-configdraftpanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    `vui-routes-configdraftpanel sectionSurface ${readablePanelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.actionsRow,.draftWorkbench_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.actionsRow,.draftWorkbench_)]:[margin-top:6px]`,
  sectionText:
    "vui-routes-configdraftpanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configdraftpanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
};

export default styles;
