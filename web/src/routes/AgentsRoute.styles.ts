// Wave 8 prune: removed 94 unused keys (AgentsRoute panel-componentization residue).
// Explicit Tailwind style map converted from the former AgentsRoute stylesheet
// by web/scripts/convert-css-module.mjs (2026-07-02 refined
// target: one styling system). Declarations are Tailwind arbitrary properties
// emitting byte-identical CSS; descendant .a .b rules were flattened onto the
// child key. Edit values directly.
import {
  vuiDenseRowClass,
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateAccentBannerClass,
  vuiStateSelectedRowFillClass,
  vuiStateSelectedWarmRowClass,
  vuiStateSuccessSoftClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  activityTimelineItem: `grid [gap:4px] min-w-0 max-w-full [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  activityTimelineItem_context:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_22%,_var(--vui-border-subtle))]",
  activityTimelineItem_inbox:
    `[border-color:color-mix(in_srgb,_var(--state-success)_28%,_var(--vui-border-subtle))] ${vuiStateSuccessSoftClass}`,
  activityTimelineItem_run:
    `[border-color:color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] ${vuiStateSelectedRowFillClass}`,
  activityTimelineItem_sub_run:
    `[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_var(--vui-border-subtle))] ${vuiStateSelectedWarmRowClass}`,
  activityTimelineList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  advancedFilterSummary: `max-w-full [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:8px] [min-height:34px] [padding:6px_9px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:760] [cursor:pointer] [list-style:none] hidden [content:\"\"] [width:7px] [height:7px] [border-right:1.5px_solid_currentColor] [border-bottom:1.5px_solid_currentColor] [transform:rotate(45deg)] [transition:transform_160ms_ease] hover:[border-color:var(--border-strong)] hover:[color:var(--fg-primary)] hover:!bg-[var(--vui-surface-row-hover)] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:inline-flex [&_strong]:[align-items:center] [&_strong]:[justify-content:center] [&_strong]:[min-width:22px] [&_strong]:[min-height:22px] [&_strong]:[border-radius:999px] [&_strong]:[background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [&_strong]:[color:var(--accent-cool)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:800]`,
  agentAvatarImage:
    "block [width:100%] [height:100%] [border-radius:inherit] [object-fit:cover]",
  agentPanel:
    "min-w-0 min-h-0 [grid-template-rows:auto_auto_minmax(0,_1fr)] max-[1040px]:min-h-0 max-[860px]:[min-height:240px]",
  agentRow:
    `grid [grid-template-columns:minmax(180px,_1.3fr)_minmax(120px,_0.86fr)_minmax(110px,_0.82fr)_minmax(88px,_0.48fr)_minmax(104px,_0.72fr)_minmax(128px,_0.68fr)] [gap:8px] [align-items:center] min-w-0 max-w-full [width:100%] [min-height:44px] [padding:var(--agent-row-pad-y)_8px] ${vuiDenseRowClass} [color:var(--fg-primary)] [text-align:left] [transition:border-color_160ms_ease,_background_160ms_ease] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] max-[860px]:[grid-template-columns:1fr] max-[860px]:[align-items:start]`,
  agentRowActive:
    `${vuiStateSelectedWarmRowClass} shadow-none [border-color:color-mix(in_srgb,var(--accent-warm)_34%,transparent)]`,
  agentRowBulkSelected:
    `${vuiStateSelectedRowFillClass}`,
  avatarEditorActions:
    "flex [flex-wrap:wrap] [gap:7px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  avatarEditorPanel: `max-w-full [position:absolute] [top:52px] [left:0] [z-index:5] grid [gap:9px] [width:min(320px,_82vw)] [padding:10px] ${vuiFlatPanelClass} [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.4]`,
  avatarLibraryHeader:
    "flex [align-items:center] [justify-content:space-between] [gap:8px] min-w-0 [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:800] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  avatarOption:
    "grid w-full [place-items:center] [aspect-ratio:1] min-w-0 [padding:2px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:50%] !bg-[var(--vui-surface-row)] [cursor:pointer] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] focus-visible:[outline:none] [&_img]:block [&_img]:[width:100%] [&_img]:[height:100%] [&_img]:[border-radius:inherit] [&_img]:[object-fit:cover]",
  boundarySummaryGrid:
    "grid [align-content:start] [gap:5px] min-w-0 max-w-full [grid-template-columns:repeat(3,_minmax(0,_1fr))] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_span]:[padding:7px_8px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:!bg-[var(--vui-surface-row)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  bulkFieldHeader:
    "inline-flex [align-items:center] [gap:6px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:800] [&_input]:[width:14px] [&_input]:[height:14px] [&_input]:[margin:0] [&_input]:[accent-color:var(--accent-cool)]",
  bulkSelectionList:
    "flex [flex-wrap:wrap] [gap:6px] min-w-0 [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[padding:3px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:!bg-[var(--vui-surface-row)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  checkField: `flex [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:30px] [padding:0_8px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [&_input]:[flex:0_0_auto] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]`,
  compressionPolicyFooter:
    "grid [gap:7px] min-w-0 [grid-template-columns:minmax(110px,_1fr)_repeat(2,_minmax(0,_1fr))] [align-items:end] max-[860px]:[grid-template-columns:1fr]",
  compressionPolicyGrid:
    "grid [gap:7px] min-w-0 [grid-template-columns:repeat(4,_minmax(0,_1fr))] max-[860px]:[grid-template-columns:1fr]",
  compressionPolicySubgrid:
    "grid [gap:7px] min-w-0 [grid-template-columns:repeat(4,_minmax(0,_1fr))] [padding:7px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-border-subtle))] [border-radius:var(--radius-control)] !bg-[var(--vui-surface-panel)] max-[860px]:[grid-template-columns:1fr]",
  configDeepLinkRow:
    "flex [flex-wrap:wrap] [justify-content:flex-end] [gap:6px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  configEditor: `grid [gap:8px] min-w-0 max-w-full [padding:10px] ${vuiFlatPanelClass}`,
  contextModeGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  createAgentGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  createAgentPanel:
    "grid [align-content:start] [gap:8px] min-w-0 min-h-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_26%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_6%,_transparent)] [overflow:auto] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere]",
  createToolBundleGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 [max-height:184px] [overflow:auto] [padding-right:3px] max-[860px]:[grid-template-columns:1fr]",
  createToolBundleOption: `grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:flex-start] [gap:7px] min-w-0 [padding:8px] ${vuiOpaqueRowClass} [&_input]:[margin-top:2px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[white-space:nowrap]`,
  createToolBundleSelected:
    `grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:flex-start] [gap:7px] min-w-0 [padding:8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_var(--vui-border-subtle))] ${vuiStateSelectedRowFillClass} [&_input]:[margin-top:2px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[white-space:nowrap]`,
  dangerButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-error)_40%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  dangerZone:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--state-error)_32%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--state-error)_7%,_transparent)] [&_svg]:[color:var(--state-error)]",
  detailAvatarButton:
    "grid w-[46px] h-[46px] [place-items:center] [width:46px] [height:46px] [padding:0] [border:0] [border-radius:50%] [background:transparent] [color:inherit] [cursor:pointer] focus-visible:[outline:none]",
  detailHeader:
    "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0 [&_p]:[margin:4px_0_0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42]",
  detailHealthStatus:
    "flex [align-items:center] [justify-items:start] min-w-0 [flex:0_0_auto] [justify-content:flex-end]",
  detailPanel:
    "min-w-0 min-h-0 [overflow:auto] max-[1040px]:[grid-column:1_/_-1] max-[1040px]:[min-height:220px] max-[1040px]:[max-height:none] max-[860px]:[min-height:420px] max-[860px]:[max-height:none]",
  detailSection:
    `min-w-0 max-w-full ${vuiFlatPanelClass} [&_svg]:[grid-area:icon] [&_svg]:[color:var(--accent-cool)] grid [gap:8px] [padding:10px]`,
  detailTab:
    "grid w-full [justify-items:center] [gap:2px] min-w-0 [min-height:30px] [padding:5px_4px] [border:1px_solid_transparent] [border-radius:var(--radius-control)] [background:transparent] [color:var(--fg-tertiary)] [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)] hover:[background:var(--vui-surface-row-hover)] hover:[color:var(--fg-secondary)]",
  detailTabActive:
    "grid w-full [justify-items:center] [gap:2px] min-w-0 [min-height:30px] [padding:5px_4px] [border:1px_solid_transparent] [border-radius:var(--radius-control)] [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[font-size:var(--vui-font-xs)] [border-color:color-mix(in_srgb,_var(--accent-cool)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [color:var(--accent-cool)] [&_strong]:[color:var(--accent-cool)]",
  detailTabs: `grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:4px] min-w-0 [padding:4px] ${vuiOpaqueRowClass} max-[860px]:[grid-template-columns:1fr]`,
  emptyState:
    "grid [place-items:start] [align-content:start] [justify-items:start] [gap:6px] [min-height:72px] [padding:10px] [border:1px_dashed_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [color:var(--fg-secondary)] [text-align:left] [&_svg]:[width:17px] [&_svg]:[height:17px] [&_svg]:[color:var(--accent-cool)] [&_strong]:[color:var(--fg-primary)] [&_p]:[margin:0] [&_p]:[max-width:52ch] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.34] [&_p]:[overflow-wrap:anywhere]",
  factGrid:
    "grid [grid-template-columns:repeat(auto-fit,_minmax(190px,_1fr))] [gap:6px] [&_section]:min-w-0 [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:!bg-[var(--vui-surface-row)] [&_section]:grid [&_section]:[grid-template-columns:18px_minmax(0,_1fr)] [&_section]:[grid-template-rows:auto_auto] [&_section]:[align-items:center] [&_section]:[column-gap:8px] [&_section]:[row-gap:2px] [&_section]:[padding:7px_8px_8px] [&_svg]:[grid-column:1] [&_svg]:[grid-row:1_/_span_2] [&_svg]:[width:16px] [&_svg]:[height:16px] [&_svg]:[align-self:center] [&_svg]:[color:var(--accent-cool)] [&_span]:[grid-column:2] [&_span]:[grid-row:1] [&_span]:block [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[grid-column:2] [&_strong]:[grid-row:2] [&_strong]:block [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] max-[860px]:[grid-template-columns:1fr]",
  fieldWide:
    "grid [grid-column:1_/_-1] [gap:4px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32] [&_textarea]:[width:100%] [&_textarea]:min-w-0 [&_textarea]:[border:1px_solid_var(--vui-border-subtle)] [&_textarea]:[border-radius:var(--radius-control)] [&_textarea]:[background:var(--vui-surface-row)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-xs)] [&_textarea]:[min-height:62px] [&_textarea]:[resize:vertical] [&_textarea]:[padding:7px_9px] [&_textarea]:[line-height:1.35] [&_textarea]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_textarea]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  filterPanel:
    "min-w-0 min-h-0 [grid-template-rows:auto_minmax(0,_1fr)_auto] max-[1040px]:min-h-0 max-[860px]:[min-height:150px]",
  groupButton:
    `grid max-w-full [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:8px] [width:100%] [min-height:34px] [padding:6px_9px] ${vuiDenseRowClass} [color:var(--fg-secondary)] [text-align:left] [transition:border-color_160ms_ease,_background_160ms_ease,_color_160ms_ease] [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[gap:8px] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:inline-flex [&_strong]:[align-items:center] [&_strong]:[justify-content:center] [&_strong]:[min-width:22px] [&_strong]:[min-height:22px] [&_strong]:[border-radius:999px] [&_strong]:[font-style:normal] [&_strong]:[font-size:var(--vui-font-xs)] [&_em]:inline-flex [&_em]:[align-items:center] [&_em]:[justify-content:center] [&_em]:[min-width:22px] [&_em]:[min-height:22px] [&_em]:[border-radius:999px] [&_em]:[font-style:normal] [&_em]:[font-size:var(--vui-font-xs)] [&_strong]:[background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [&_strong]:[color:var(--accent-cool)] [&_em]:[gap:4px] [&_em]:[padding:0_7px] [&_em]:[background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)] [&_em]:[color:var(--accent-warm-2)]`,
  groupButtonActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_34%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_var(--vui-surface-row))] [color:var(--fg-primary)]",
  healthCell:
    "flex [align-items:center] [justify-items:start] min-w-0",
  healthGuide_blocking:
    "[border-color:color-mix(in_srgb,_var(--state-error)_28%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_7%,_var(--vui-surface-row))]",
  healthGuide_info:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_var(--vui-surface-row))]",
  healthGuide_ok:
    "[border-color:color-mix(in_srgb,_var(--state-success)_24%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_7%,_var(--vui-surface-row))]",
  healthGuide_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_var(--vui-surface-row))]",
  iconButton: `grid w-[26px] h-[26px] [place-items:center] [width:26px] [height:26px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [font:inherit] [font-size:1rem] [cursor:pointer]`,
  inboxMessageItem: `grid [gap:5px] min-w-0 max-w-full [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  inboxMessageItemFocused:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)]",
  inboxMessageList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  inlineAdd: `grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:6px] min-w-0 [&_input]:min-w-0 [&_input]:[min-height:32px] [&_input]:[border-radius:var(--radius-control)] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:[width:100%] [&_input]:[padding:0_8px] [&_input]:[border:1px_solid_var(--vui-border-subtle)] [&_input]:!${vuiWorkspaceFillClass} [&_input]:[color:var(--fg-primary)] [&_[data-vui=\"button\"]]:[white-space:nowrap]`,
  issueItem_blocking:
    "[border-color:color-mix(in_srgb,_var(--state-error)_32%,_transparent)]",
  issueItem_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_32%,_transparent)]",
  issueList:
    "grid [align-content:start] [gap:5px] min-w-0",
  llmSlotGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] min-w-0",
  maintenanceIntro:
    "grid [grid-template-columns:minmax(0,_0.8fr)_minmax(0,_1.2fr)] [align-items:center] [gap:10px] min-w-0 [padding:9px_10px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] !bg-[var(--vui-surface-row)] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]",
  managementBriefPanel:
    "grid [gap:7px] min-w-0 [padding:9px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_5%,_transparent)]",
  managementChecklistDone:
    "w-full [&_svg]:[color:var(--state-success)]",
  managementChecklistMissing:
    "w-full [&_svg]:[color:var(--accent-warm)]",
  managementNav:
    "[margin:0] max-[1120px]:[justify-self:start]",
  memoryPolicyGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:6px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_var(--vui-border-subtle)] [&_section]:[border-radius:var(--radius-control)] [&_section]:[background:var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
  nextActionList:
    "grid [grid-template-columns:auto_repeat(3,_minmax(0,_1fr))] [align-items:stretch] [gap:5px] min-w-0 [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:760] [&_span]:[white-space:nowrap] [&_button]:grid [&_button]:[gap:2px] [&_button]:min-w-0 [&_button]:[margin:0] [&_button]:[padding:6px_7px] [&_button]:[border:1px_solid_var(--vui-border-subtle)] [&_button]:[border-radius:var(--radius-control)] [&_button]:!bg-[var(--vui-surface-row)] [&_button]:[color:var(--fg-secondary)] [&_button]:[text-align:left] [&_p]:grid [&_p]:[gap:2px] [&_p]:[margin:0] [&_p]:[padding:6px_7px] [&_p]:[border:1px_solid_var(--vui-border-subtle)] [&_p]:[border-radius:var(--radius-control)] [&_p]:!bg-[var(--vui-surface-row)] [&_p]:[text-align:left] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_p]:[color:var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)]",
  policyGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] [&_div]:min-w-0 [&_div]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_div]:[border-radius:var(--radius-control)] [&_div]:!bg-[var(--vui-surface-row)] [&_div]:grid [&_div]:[grid-template-columns:auto_minmax(0,_1fr)] [&_div]:[grid-template-rows:auto_auto] [&_div]:[column-gap:8px] [&_div]:[row-gap:2px] [&_div]:[padding:7px_8px_8px] [&_svg]:[grid-column:1] [&_svg]:[grid-row:1_/_3] [&_svg]:[color:var(--accent-cool)] [&_span]:[grid-column:2] [&_span]:[grid-row:1] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[grid-column:2] [&_strong]:[grid-row:2] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] max-[860px]:[grid-template-columns:1fr]",
  policySummaryGrid:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] min-w-0 max-w-full [&_span]:min-w-0 [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:!bg-[var(--vui-surface-row)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)]",
  primaryButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_38%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_16%,_transparent)] [color:var(--accent-cool)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  promptConfigRow:
    "grid [grid-template-columns:minmax(0,_1fr)_max-content] [align-items:center] [gap:6px] min-w-0 [&_select]:min-w-0 [&_[data-vui=\"button\"]]:[white-space:nowrap] [&_select]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_select]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  protectedZone:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_7%,_transparent)] [&_svg]:[color:var(--accent-cool)]",
  referenceList:
    "grid [align-content:start] [gap:5px] min-w-0",
  resetOptionField: `grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:start] [gap:8px] min-w-0 [min-height:58px] [padding:7px_8px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [&_input]:[margin-top:3px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_small]:min-w-0 [&_small]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32]`,
  returnBanner:
    `grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:10px] min-w-0 [padding:9px_10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_38%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] ${vuiStateAccentBannerClass} [box-shadow:none] max-[860px]:[grid-template-columns:1fr]`,
  returnBannerButton:
    "inline-flex w-fit max-w-full max-[860px]:w-fit [align-items:center] [justify-content:center] [gap:6px] [min-width:116px] [min-height:34px] [padding:0_12px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_68%,_var(--vui-border-subtle))] [border-radius:var(--radius-control)] [background:var(--accent-cool)] [color:var(--accent-cool-contrast)] [font-size:var(--vui-font-xs)] [font-weight:800] [white-space:nowrap] [cursor:pointer] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_86%,_var(--vui-border-subtle))] hover:[background:color-mix(in_srgb,_var(--accent-cool)_90%,_var(--fg-primary))] hover:[outline:none] hover:[box-shadow:var(--focus-ring)] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_86%,_var(--vui-border-subtle))] focus-visible:[background:color-mix(in_srgb,_var(--accent-cool)_90%,_var(--fg-primary))] focus-visible:[outline:none] focus-visible:[box-shadow:var(--focus-ring)]",
  roomCheckField: `grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:36px] [padding:6px_8px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [&_input]:[margin:0] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  roomMembershipList:
    "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  route:
    `grid max-w-full [grid-template-rows:auto_minmax(0,_1fr)] [height:100%] min-h-0 [overflow:hidden] [--agent-density-gap:0px] [--agent-panel-pad:8px] [--agent-row-pad-y:6px] [--agent-control-height:24px] [&_[data-vui-product=\"agent-workspace-panel\"]]:max-w-full [&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-hidden [&_[data-vui-product=\"agent-workspace-panel\"]]:[scrollbar-gutter:stable] [&_[data-vui-product=\"agent-workspace-panel\"]]:[overflow-wrap:anywhere] [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap] max-[860px]:[height:100%] max-[860px]:min-h-0 max-[860px]:[grid-template-rows:auto_minmax(0,_1fr)] max-[860px]:[overflow:hidden] max-[860px]:[&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-visible ${vuiWorkspaceFillClass}`,
  runHistoryItem: `grid [gap:3px] min-w-0 max-w-full [padding:7px_8px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  runHistoryList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:260px] [overflow:auto] [padding-right:3px]",
  runtimeEvidenceHint: `grid [grid-template-columns:auto_auto_minmax(0,_1fr)] [gap:8px] [align-items:center] min-w-0 max-w-full [padding:8px_10px] ${vuiOpaqueRowClass} [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[text-transform:uppercase] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_code]:[color:var(--fg-primary)] [&_code]:[font-family:var(--font-mono,_ui-monospace,_SFMono-Regular,_Consolas,_monospace)] [&_code]:[font-size:var(--vui-font-xs)]`,
  runtimeFocusPanel:
    `grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] ${vuiStateAccentBannerClass} [box-shadow:none] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)]`,
  runtimeNextStep:
    "grid [gap:4px] min-w-0 [padding:9px_10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_20%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_transparent)] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[text-transform:uppercase] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  runtimePill:
    "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  runtimePolicyGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 max-w-full [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:7px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:!bg-[var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] max-[860px]:[grid-template-columns:1fr]",
  runtime_archived:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_blocked:
    "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  runtime_failed:
    "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  runtime_idle:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_running:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_34%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [color:var(--accent-cool)]",
  runtime_stopped:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_unknown:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  secondaryButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_var(--vui-border-subtle)] !bg-[var(--vui-surface-row)] [color:var(--fg-secondary)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  segmentedControl: `inline-grid max-w-full [grid-template-columns:repeat(3,_minmax(56px,_auto))] [gap:3px] [padding:3px] ${vuiOpaqueRowClass}`,
  storagePanel: `grid [gap:5px] min-w-0 max-w-full [padding:8px] ${vuiFlatPanelClass} [&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap]`,
  tagList:
    "flex [flex-wrap:wrap] [gap:5px] min-w-0 [min-height:28px] [&_button]:inline-flex [&_button]:[align-items:center] [&_button]:[min-height:24px] [&_button]:[max-width:100%] [&_button]:[padding:0_7px] [&_button]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_button]:[border-radius:999px] [&_button]:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [&_button]:[color:var(--accent-cool)] [&_button]:[font-size:var(--vui-font-xs)] [&_button]:[overflow:hidden] [&_button]:[text-overflow:ellipsis] [&_button]:[white-space:nowrap] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  timelineActions:
    "flex [flex-wrap:wrap] [gap:5px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  toggleGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] max-[860px]:[grid-template-columns:1fr]",
  toolBundleActions:
    "[grid-column:2] [grid-row:1_/_3] inline-flex [align-items:center] [gap:5px] min-w-0",
  toolBundleItem: `grid [grid-template-columns:minmax(0,_1fr)_auto] [grid-template-rows:auto_auto] [align-items:center] [gap:4px_8px] min-w-0 max-w-full [padding:7px_8px] ${vuiOpaqueRowClass} [&_span]:[grid-column:1] [&_span]:[grid-row:1] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_p]:[grid-column:1] [&_p]:[grid-row:2] [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]`,
  toolGovernanceItem: `grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 max-w-full [padding:8px] ${vuiOpaqueRowClass} [&_div]:first-child:grid [&_div]:first-child:[gap:3px] [&_div]:first-child:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  toolGovernanceList:
    "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  toolPermissionGroup: `grid [gap:6px] min-w-0 max-w-full [padding:7px] ${vuiOpaqueRowClass}`,
  toolPermissionRow: `grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:40px] [padding:6px_8px] ${vuiOpaqueRowClass} [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]`,
  workspaceScopePanel: `grid [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:6px] min-w-0 max-w-full [padding:7px_8px] ${vuiOpaqueRowClass} [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-secondary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]`,
} as const;

export default styles;
