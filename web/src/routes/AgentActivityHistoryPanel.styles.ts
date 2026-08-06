import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailSection: `min-w-0 ${vuiFlatPanelClass} [&_svg]:[grid-area:icon] [&_svg]:[color:var(--accent-cool)] grid [gap:8px] [padding:10px]`,
  panelHeader: "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelHeaderActions: "inline-flex [align-items:center] [justify-content:flex-end] [gap:8px] min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  metadataTrigger: "min-w-0 [border-radius:6px] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  tooltipMeta: "grid min-w-0 [gap:3px] [&_code]:min-w-0 [&_code]:[overflow-wrap:anywhere] [&_code]:[font-family:var(--font-mono)]",
  activityTimelineList: "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  activityTimelineItem: `grid [gap:4px] min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2]`,
  activityTimelineItem_context: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_22%,_var(--vui-border-subtle))]",
  activityTimelineItem_inbox: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_22%,_var(--vui-border-subtle))]",
  activityTimelineItem_run: "[border-color:color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-cool)_5%,_var(--vui-surface-row))]",
  activityTimelineItem_sub_run: "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-warm)_5%,_var(--vui-surface-row))]",
  timelineActions: "flex [flex-wrap:wrap] [gap:5px] min-w-0 [&_[data-vui=\\\"button\\\"]]:[max-width:100%] [&_[data-vui=\\\"button\\\"]]:[white-space:nowrap]",
  runHistoryList: "grid [align-content:start] [gap:5px] min-w-0 [max-height:260px] [overflow:auto] [padding-right:3px]",
  runHistoryItem: `grid [gap:3px] min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)]`,
  inboxMessageList: "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  inboxMessageItem: `grid [gap:5px] min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2]`,
  inboxMessageItemFocused: "[border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)]",
  inboxMessageTop: "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0",
} as const;

export default styles;
