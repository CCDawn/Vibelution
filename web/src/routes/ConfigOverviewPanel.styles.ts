import {
  vuiElevatedPanelClass,
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = vuiElevatedPanelClass;
const sectionHeaderSurface =
  `[border-bottom:1px_solid_var(--vui-border-subtle)] !${vuiToolbarFillClass}`;

const styles = {
  detailCard:
    "vui-routes-configoverviewpanel detailCard flex items-baseline gap-3 py-2 [&>span]:text-sm [&>span]:text-vui-fg-secondary [&>strong]:text-lg [&>strong]:font-semibold",
  eyebrow:
    "vui-routes-configoverviewpanel eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  summaryGrid:
    "vui-routes-configoverviewpanel summaryGrid flex flex-wrap gap-x-10 gap-y-2",
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
