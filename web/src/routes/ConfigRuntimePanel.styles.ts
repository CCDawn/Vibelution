import {
  vuiElevatedPanelClass,
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = vuiElevatedPanelClass;
const sectionHeaderSurface =
  `[border-bottom:1px_solid_var(--vui-border-subtle)] !${vuiToolbarFillClass}`;

const styles = {
  behaviorCopy:
    "vui-routes-configruntimepanel behaviorCopy [display:grid] [gap:4px] [min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:[font-weight:700] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  behaviorRow:
    "vui-routes-configruntimepanel behaviorRow [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:center] [gap:24px] [padding:14px_var(--config-section-x)] [background:var(--vui-surface-row)]",
  sectionHeader:
    `vui-routes-configruntimepanel sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionIcon:
    "vui-routes-configruntimepanel sectionIcon [color:var(--accent-warm-2)] [margin-top:1px]",
  sectionSurface:
    `vui-routes-configruntimepanel sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible]`,
  intakeTabs: "vui-routes-configruntimepanel intakeTabs inline-grid w-fit max-w-full min-w-0 justify-self-end gap-0",
  intakeTabsList:
    "vui-routes-configruntimepanel intakeTabsList inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-[var(--control-radius)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-toolbar)] p-1",
  intakeTabsTrigger:
    "vui-routes-configruntimepanel intakeTabsTrigger min-h-10 min-w-28 px-4 font-semibold " +
    "data-[state=active]:border-[color-mix(in_srgb,var(--accent-cool)_32%,transparent)] " +
    "data-[state=active]:bg-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-control-muted))] " +
    "data-[state=active]:text-[var(--accent-warm-2)]",
};

export default styles;
