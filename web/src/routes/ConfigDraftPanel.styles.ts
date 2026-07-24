import {
  vuiElevatedPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const readablePanelSurface = vuiElevatedPanelClass;
const readableRowSurface = vuiOpaqueRowClass;
const mutedControl =
  "[display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [border:1px_solid_var(--vui-border-soft)] [background:var(--vui-control-muted)] [color:var(--vui-fg-primary)] hover:[cursor:pointer] hover:[border-color:var(--vui-border-soft)] hover:[background:var(--vui-control-muted-hover)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]";
const sectionHeaderSurface =
  "[border-bottom:1px_solid_var(--vui-border-subtle)] !bg-[var(--vui-surface-toolbar)]";

const styles = {
  actionButton:
    `vui-routes-configdraftpanel actionButton ${mutedControl}`,
  actionsRow:
    "vui-routes-configdraftpanel actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  draftActionRail:
    `vui-routes-configdraftpanel draftActionRail ${readableRowSurface} [display:grid] [grid-template-columns:auto_auto_minmax(0,1fr)] [align-items:center] [gap:6px] [padding:7px] max-[760px]:[grid-template-columns:1fr]`,
  draftWorkbench:
    `vui-routes-configdraftpanel draftWorkbench ${readableRowSurface} [display:grid] [grid-template-rows:auto_minmax(22rem,1fr)_auto] [gap:10px] [padding:10px] [min-height:0] [overflow:hidden]`,
  editorWrap:
    "vui-routes-configdraftpanel editorWrap [min-height:22rem] [height:100%] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [overflow:hidden] [background:var(--vui-surface-workspace)] [&.cm-editor]:[height:100%] [&.cm-editor]:[min-height:22rem] [&.cm-scroller]:[overflow:auto]",
  eyebrow:
    "vui-routes-configdraftpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  helperText:
    "vui-routes-configdraftpanel helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  rawConfigPanel:
    `vui-routes-configdraftpanel rawConfigPanel ${readableRowSurface} [display:grid] [gap:8px] [padding:10px] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--vui-fg-primary)] [&_summary]:[font-weight:700]`,
  configPath:
    "vui-routes-configdraftpanel configPath [display:block] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [color:var(--vui-fg-secondary)]",
  rawToml:
    "vui-routes-configdraftpanel rawToml [max-height:18rem] [overflow:auto] [overflow-wrap:anywhere] [margin:0] [padding:10px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:8px] [background:var(--vui-surface-workspace)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [line-height:1.55] [color:var(--vui-fg-secondary)]",
  sectionHeader:
    `vui-routes-configdraftpanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionIcon:
    "vui-routes-configdraftpanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    `vui-routes-configdraftpanel sectionSurface ${readablePanelSurface} [display:grid] [grid-template-rows:auto_auto_minmax(0,1fr)] [gap:0] [padding:0] [min-height:0] [height:100%] [scroll-margin-top:84px] [overflow:hidden] [&>_.sectionText]:[padding:10px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-sm)] [&>_:where(_.actionsRow,.draftWorkbench_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.actionsRow,.draftWorkbench_)]:[margin-top:8px]`,
  sectionText:
    "vui-routes-configdraftpanel sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configdraftpanel sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:1rem] [font-weight:700]",
};

export default styles;
