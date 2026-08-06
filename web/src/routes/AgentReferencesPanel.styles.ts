import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  cleanPill: "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [background:var(--vui-surface-toolbar)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:700]",
  configEditor: `grid [gap:8px] min-w-0 [padding:10px] ${vuiFlatPanelClass}`,
  detailSection: `min-w-0 ${vuiFlatPanelClass} [&_svg]:[grid-area:icon] [&_svg]:[color:var(--accent-cool)] grid [gap:8px] [padding:10px]`,
  metadataTrigger: "min-w-0 focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  referenceHeader: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  referenceItem: `grid [gap:4px] min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[margin:0] [&_span]:min-w-0 [&_span]:[overflow-wrap:anywhere] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]`,
  referenceList: "grid [align-content:start] [gap:5px] min-w-0",
  referenceMetaRow: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:6px] min-w-0 [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[white-space:nowrap] max-[860px]:[grid-template-columns:1fr]",
  referenceStatusActive: "inline-flex [align-items:center] [min-height:19px] [padding:0_6px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_transparent)] [border-radius:999px] [background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [color:var(--accent-cool)] [font-size:var(--vui-font-xs)] [font-weight:760] [text-transform:uppercase] [white-space:nowrap]",
  referenceStatusStale: "inline-flex [align-items:center] [min-height:19px] [padding:0_6px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:760] [text-transform:uppercase] [white-space:nowrap] [border-color:color-mix(in_srgb,_var(--accent-warm)_32%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  roomCheckField: `grid [grid-template-columns:auto_minmax(0,_1fr)_max-content] [align-items:center] [gap:8px] min-w-0 [min-height:36px] [padding:6px_8px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [&_span]:grid [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[white-space:nowrap] max-[860px]:[grid-template-columns:auto_minmax(0,_1fr)] max-[860px]:[align-items:start]`,
  roomMembershipList: "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
} as const;

export default styles;
