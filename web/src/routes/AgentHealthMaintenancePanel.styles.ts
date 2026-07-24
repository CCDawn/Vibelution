import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  contextualHintRow: "inline-flex [align-items:center] [gap:6px]",
  detailSection: `min-w-0 ${vuiFlatPanelClass} [&_svg]:[grid-area:icon] [&_svg]:[color:var(--accent-cool)] grid [gap:8px] [padding:10px]`,
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  issueList: "grid [align-content:start] [gap:5px] min-w-0",
  issueItem: `grid [gap:4px] min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [overflow-wrap:anywhere] [&_strong]:min-w-0 [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.4]`,
  issueItem_blocking: "[border-color:color-mix(in_srgb,_var(--state-error)_32%,_transparent)]",
  issueItem_warning: "[border-color:color-mix(in_srgb,_var(--accent-warm)_32%,_transparent)]",
  emptyText: "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
  maintenanceIntro: `grid [grid-template-columns:minmax(0,_0.8fr)_minmax(0,_1.2fr)] [align-items:center] [gap:10px] min-w-0 [padding:9px_10px] ${vuiOpaqueRowClass} [overflow-wrap:anywhere] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36] max-[860px]:[grid-template-columns:1fr]`,
} as const;

export default styles;
