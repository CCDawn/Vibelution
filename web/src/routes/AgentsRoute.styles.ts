// Explicit Tailwind style map converted from the former AgentsRoute stylesheet
// by web/scripts/convert-css-module.mjs (2026-07-02 refined
// target: one styling system). Declarations are Tailwind arbitrary properties
// emitting byte-identical CSS; descendant .a .b rules were flattened onto the
// child key. Edit values directly.
const styles = {
  activityTimelineItem:
    "grid [gap:4px] min-w-0 max-w-full [padding:7px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  activityTimelineItem_context:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_22%,_var(--vui-border-subtle))]",
  activityTimelineItem_inbox:
    "[border-color:color-mix(in_srgb,_var(--state-success)_28%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--state-success)_5%,_var(--vui-surface-row))]",
  activityTimelineItem_run:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-cool)_5%,_var(--vui-surface-row))]",
  activityTimelineItem_sub_run:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-warm)_5%,_var(--vui-surface-row))]",
  activityTimelineList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  advancedFilterBody:
    "grid [gap:10px] min-w-0 [padding-top:8px]",
  advancedFilterSection:
    "grid min-w-0",
  advancedFilterSummary:
    "max-w-full [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:8px] [min-height:34px] [padding:6px_9px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:760] [cursor:pointer] [list-style:none] hidden [content:\"\"] [width:7px] [height:7px] [border-right:1.5px_solid_currentColor] [border-bottom:1.5px_solid_currentColor] [transform:rotate(45deg)] [transition:transform_160ms_ease] hover:[border-color:var(--border-strong)] hover:[color:var(--fg-primary)] hover:[background:color-mix(in_srgb,_var(--vui-surface-row-hover)_70%,_transparent)] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:inline-flex [&_strong]:[align-items:center] [&_strong]:[justify-content:center] [&_strong]:[min-width:22px] [&_strong]:[min-height:22px] [&_strong]:[border-radius:999px] [&_strong]:[background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [&_strong]:[color:var(--accent-cool)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:800]",
  agentAvatar:
    "grid [place-items:center] [flex:0_0_auto] [border-radius:50%] [color:var(--fg-primary)] [background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [font-family:var(--font-display)] [font-weight:800] [box-shadow:none] [overflow:hidden] [width:30px] [height:30px] [font-size:var(--vui-font-xs)]",
  agentAvatarImage:
    "block [width:100%] [height:100%] [border-radius:inherit] [object-fit:cover]",
  agentColumn:
    "grid [align-content:start] [gap:6px] min-w-0 [padding:7px_0_0] [border-top:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] first-child:[padding-top:0] first-child:[border-top:0]",
  agentColumnGrid:
    "grid [align-content:start] [gap:8px] min-h-0 [overflow:auto] [padding-right:4px]",
  agentColumnHeader:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [padding:0_4px_2px] [&_div]:flex [&_div]:[align-items:center] [&_div]:[gap:6px] [&_div]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:820] [&_em]:inline-flex [&_em]:[align-items:center] [&_em]:[justify-content:center] [&_em]:[min-width:24px] [&_em]:[min-height:22px] [&_em]:[padding:0_7px] [&_em]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_22%,_var(--vui-border-subtle))] [&_em]:[border-radius:999px] [&_em]:[background:color-mix(in_srgb,_var(--accent-cool)_9%,_transparent)] [&_em]:[color:var(--accent-cool)] [&_em]:[font-size:var(--vui-font-xs)] [&_em]:[font-style:normal] [&_em]:[font-weight:800]",
  agentIdentity:
    "min-w-0 [overflow:hidden] [text-overflow:ellipsis] grid [grid-template-columns:30px_minmax(0,_1fr)] [align-items:center] [gap:8px]",
  agentIdentityCopy:
    "grid min-w-0 [gap:4px] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:color-mix(in_srgb,_var(--fg-primary)_88%,_var(--accent-cool))] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  agentPanel:
    "min-w-0 min-h-0 [grid-template-rows:auto_auto_minmax(0,_1fr)] max-[1040px]:min-h-0 max-[860px]:[min-height:240px]",
  agentPanelCreating:
    "[grid-template-rows:auto_minmax(360px,_1.4fr)_minmax(120px,_0.6fr)] max-[1040px]:[grid-template-rows:auto_minmax(410px,_1fr)_minmax(96px,_0.28fr)]",
  agentRoleTag:
    "inline-flex [align-items:center] [justify-content:center] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-weight:700] [white-space:nowrap] [justify-self:start] [min-height:22px] [max-width:100%] [padding:0_7px] [font-size:var(--vui-font-xs)] [line-height:1] [overflow:hidden] [text-overflow:ellipsis]",
  agentRoleTag_chat:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_34%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)] [color:var(--accent-warm-2)]",
  agentRoleTag_general:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  agentRoleTag_memory:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_30%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--fg-tertiary)_10%,_transparent)] [color:var(--fg-secondary)]",
  agentRoleTag_research:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_36%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-cool)_13%,_transparent)] [color:var(--accent-cool-2)]",
  agentRoleTag_self:
    "[border-color:color-mix(in_srgb,_var(--state-success)_34%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--state-success)_12%,_transparent)] [color:var(--state-success)]",
  agentRoleTag_supervised:
    "[border-color:color-mix(in_srgb,_var(--state-warning)_36%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--state-warning)_12%,_transparent)] [color:var(--state-warning)]",
  agentRoleTag_tool:
    "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_30%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--fg-tertiary)_10%,_transparent)] [color:var(--fg-secondary)]",
  agentRow:
    "grid [grid-template-columns:minmax(180px,_1.3fr)_minmax(120px,_0.86fr)_minmax(110px,_0.82fr)_minmax(88px,_0.48fr)_minmax(104px,_0.72fr)_minmax(128px,_0.68fr)] [gap:8px] [align-items:center] min-w-0 max-w-full [width:100%] [min-height:44px] [padding:var(--agent-row-pad-y)_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-primary)] [text-align:left] [transition:border-color_160ms_ease,_background_160ms_ease] hover:[border-color:var(--border-strong)] hover:[background:color-mix(in_srgb,_var(--vui-surface-row-hover)_70%,_transparent)] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] max-[860px]:[grid-template-columns:1fr] max-[860px]:[align-items:start]",
  agentRowActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_34%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-warm)_9%,_transparent)]",
  agentRowBulkSelected:
    "[background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)]",
  agentRowShell:
    "grid [grid-template-columns:28px_minmax(0,_1fr)] [align-items:center] [gap:5px] min-w-0",
  agentTable:
    "grid [align-content:start] [gap:4px] min-h-0",
  agentTableHead:
    "grid [grid-template-columns:minmax(180px,_1.3fr)_minmax(120px,_0.86fr)_minmax(110px,_0.82fr)_minmax(88px,_0.48fr)_minmax(104px,_0.72fr)_minmax(128px,_0.68fr)] [gap:8px] [align-items:center] min-w-0 [position:sticky] [top:0] [z-index:1] [padding:0_8px_5px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [background:var(--vui-surface-panel)] max-[860px]:hidden",
  avatarEditorActions:
    "flex [flex-wrap:wrap] [gap:7px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  avatarEditorAnchor:
    "[position:relative] [flex:0_0_auto]",
  avatarEditorHeader:
    "flex [align-items:center] [justify-content:space-between] [gap:8px] min-w-0 [&_strong]:block [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem]",
  avatarEditorPanel:
    "max-w-full [position:absolute] [top:52px] [left:0] [z-index:5] grid [gap:9px] [width:min(320px,_82vw)] [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_26%,_transparent)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_72%,_transparent)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.4]",
  avatarLibraryHeader:
    "flex [align-items:center] [justify-content:space-between] [gap:8px] min-w-0 [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:800] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  avatarOption:
    "grid w-full [place-items:center] [aspect-ratio:1] min-w-0 [padding:2px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:50%] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [cursor:pointer] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] focus-visible:[outline:none] [&_img]:block [&_img]:[width:100%] [&_img]:[height:100%] [&_img]:[border-radius:inherit] [&_img]:[object-fit:cover]",
  avatarOptionGrid:
    "grid [grid-template-columns:repeat(auto-fill,_minmax(42px,_1fr))] [gap:7px] [max-height:178px] [overflow:auto] [padding-right:2px]",
  avatarOptionSelected:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_58%,_transparent)] [box-shadow:none]",
  boundarySummaryGrid:
    "grid [align-content:start] [gap:5px] min-w-0 max-w-full [grid-template-columns:repeat(3,_minmax(0,_1fr))] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_span]:[padding:7px_8px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  bulkFieldHeader:
    "inline-flex [align-items:center] [gap:6px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:800] [&_input]:[width:14px] [&_input]:[height:14px] [&_input]:[margin:0] [&_input]:[accent-color:var(--accent-cool)]",
  bulkSelectionList:
    "flex [flex-wrap:wrap] [gap:6px] min-w-0 [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[padding:3px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  capabilityPreviewPanel:
    "grid [grid-template-columns:minmax(150px,_1.35fr)_repeat(4,_minmax(0,_1fr))] [gap:6px] min-w-0 [padding:8px] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_20%,_var(--vui-border-subtle))] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--accent-warm)_5%,_transparent)] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:760] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_strong]:[align-self:stretch] [&_strong]:[padding:5px_6px] [&_strong]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_strong]:[border-radius:var(--radius-control)] [&_strong]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:[color:var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)]",
  checkField:
    "flex [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:30px] [padding:0_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [&_input]:[flex:0_0_auto] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  cleanPill:
    "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-success)_26%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  compressionInlineCheck:
    "inline-flex [align-items:center] [gap:7px] min-w-0 [min-height:30px] [padding:0_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:700] [&_input]:[flex:0_0_auto] [&_input]:[width:16px] [&_input]:[height:16px] [&_input]:[min-height:16px] [&_input]:[margin:0] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[color:inherit] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  compressionPolicyFooter:
    "grid [gap:7px] min-w-0 [grid-template-columns:minmax(110px,_1fr)_repeat(2,_minmax(0,_1fr))] [align-items:end] max-[860px]:[grid-template-columns:1fr]",
  compressionPolicyGrid:
    "grid [gap:7px] min-w-0 [grid-template-columns:repeat(4,_minmax(0,_1fr))] max-[860px]:[grid-template-columns:1fr]",
  compressionPolicySubgrid:
    "grid [gap:7px] min-w-0 [grid-template-columns:repeat(4,_minmax(0,_1fr))] [padding:7px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_14%,_var(--vui-border-subtle))] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_70%,_transparent)] max-[860px]:[grid-template-columns:1fr]",
  compressionToggleField:
    "[&_input]:[justify-self:start] [&_input]:[width:18px] [&_input]:[min-height:18px] [&_input]:[padding:0]",
  configDeepLinkRow:
    "flex [flex-wrap:wrap] [justify-content:flex-end] [gap:6px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  configEditor:
    "grid [gap:8px] min-w-0 max-w-full [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_58%,_transparent)]",
  contextModeGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  controlStrip:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:center] [gap:6px] min-w-0 [padding:4px_12px_0] max-[1120px]:[grid-template-columns:1fr] max-[860px]:[grid-template-columns:1fr]",
  countPill:
    "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  createAgentGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  createAgentPanel:
    "grid [align-content:start] [gap:8px] min-w-0 min-h-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_26%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_6%,_transparent)] [overflow:auto] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere]",
  createToolBundleGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 [max-height:184px] [overflow:auto] [padding-right:3px] max-[860px]:[grid-template-columns:1fr]",
  createToolBundleOption:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:flex-start] [gap:7px] min-w-0 [padding:8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_78%,_transparent)] [&_input]:[margin-top:2px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[white-space:nowrap]",
  createToolBundlePreview:
    "[padding:7px_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_72%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap]",
  createToolBundleSelected:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:flex-start] [gap:7px] min-w-0 [padding:8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_var(--vui-border-subtle))] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_var(--vui-surface-row))] [&_input]:[margin-top:2px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[white-space:nowrap]",
  dangerButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--state-error)_40%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  dangerZone:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--state-error)_32%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--state-error)_7%,_transparent)] [&_svg]:[color:var(--state-error)]",
  detailAvatar:
    "grid [place-items:center] [flex:0_0_auto] [border-radius:50%] [color:var(--fg-primary)] [background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [font-family:var(--font-display)] [font-weight:800] [overflow:hidden] [width:46px] [height:46px] [font-size:var(--vui-font-xs)] [outline:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)]",
  detailAvatarButton:
    "grid w-[46px] h-[46px] [place-items:center] [width:46px] [height:46px] [padding:0] [border:0] [border-radius:50%] [background:transparent] [color:inherit] [cursor:pointer] focus-visible:[outline:none]",
  detailHeader:
    "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0 [&_p]:[margin:4px_0_0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42]",
  detailHeaderActions:
    "flex [flex-direction:column] [align-items:flex-end] [gap:6px] min-w-0",
  detailHealthStatus:
    "flex [align-items:center] [justify-items:start] min-w-0 [flex:0_0_auto] [justify-content:flex-end]",
  detailPanel:
    "min-w-0 min-h-0 [overflow:auto] max-[1040px]:[grid-column:1_/_-1] max-[1040px]:[min-height:220px] max-[1040px]:[max-height:none] max-[860px]:[min-height:420px] max-[860px]:[max-height:none]",
  detailPanelCreating:
    "max-[1040px]:hidden",
  detailSection:
    "min-w-0 max-w-full [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_58%,_transparent)] [&_svg]:[grid-area:icon] [&_svg]:[color:var(--accent-cool)] grid [gap:8px] [padding:10px]",
  detailTab:
    "grid w-full [justify-items:center] [gap:2px] min-w-0 [min-height:30px] [padding:5px_4px] [border:1px_solid_transparent] [border-radius:var(--radius-control)] [background:transparent] [color:var(--fg-tertiary)] [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)] hover:[background:var(--vui-surface-row-hover)] hover:[color:var(--fg-secondary)]",
  detailTabActive:
    "grid w-full [justify-items:center] [gap:2px] min-w-0 [min-height:30px] [padding:5px_4px] [border:1px_solid_transparent] [border-radius:var(--radius-control)] [&_span]:[max-width:100%] [&_span]:[overflow:hidden] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[font-size:var(--vui-font-xs)] [border-color:color-mix(in_srgb,_var(--accent-cool)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [color:var(--accent-cool)] [&_strong]:[color:var(--accent-cool)]",
  detailTabs:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:4px] min-w-0 [padding:4px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] max-[860px]:[grid-template-columns:1fr]",
  dirtyPill:
    "inline-flex [align-items:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  editorActions:
    "flex [flex-wrap:wrap] [justify-content:flex-end] [gap:6px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  editorGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] max-[860px]:[grid-template-columns:1fr]",
  emptyState:
    "grid [place-items:start] [align-content:start] [justify-items:start] [gap:6px] [min-height:72px] [padding:10px] [border:1px_dashed_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [color:var(--fg-secondary)] [text-align:left] [&_svg]:[width:17px] [&_svg]:[height:17px] [&_svg]:[color:var(--accent-cool)] [&_strong]:[color:var(--fg-primary)] [&_p]:[margin:0] [&_p]:[max-width:52ch] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.34] [&_p]:[overflow-wrap:anywhere]",
  emptyText:
    "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
  errorText:
    "[margin:0] [font-size:var(--vui-font-xs)] [line-height:1.4] [overflow-wrap:anywhere] [color:var(--state-error)]",
  eyebrow:
    "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  factGrid:
    "grid [grid-template-columns:repeat(auto-fit,_minmax(190px,_1fr))] [gap:6px] [&_section]:min-w-0 [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_section]:grid [&_section]:[grid-template-columns:18px_minmax(0,_1fr)] [&_section]:[grid-template-rows:auto_auto] [&_section]:[align-items:center] [&_section]:[column-gap:8px] [&_section]:[row-gap:2px] [&_section]:[padding:7px_8px_8px] [&_svg]:[grid-column:1] [&_svg]:[grid-row:1_/_span_2] [&_svg]:[width:16px] [&_svg]:[height:16px] [&_svg]:[align-self:center] [&_svg]:[color:var(--accent-cool)] [&_span]:[grid-column:2] [&_span]:[grid-row:1] [&_span]:block [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[grid-column:2] [&_strong]:[grid-row:2] [&_strong]:block [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] max-[860px]:[grid-template-columns:1fr]",
  field:
    "last-child:[grid-column:1_/_-1] grid [gap:4px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32] [&_input]:min-w-0 [&_input]:[border:1px_solid_var(--vui-border-subtle)] [&_input]:[border-radius:var(--radius-control)] [&_input]:[background:var(--vui-surface-row)] [&_input]:[color:var(--fg-primary)] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-xs)] [&_select]:[width:100%] [&_select]:min-w-0 [&_select]:[min-height:30px] [&_select]:[border:1px_solid_var(--vui-border-subtle)] [&_select]:[border-radius:var(--radius-control)] [&_select]:[background:var(--vui-surface-row)] [&_select]:[color:var(--fg-primary)] [&_select]:[font:inherit] [&_select]:[font-size:var(--vui-font-xs)] [&_input]:[flex:0_0_auto] [&_input]:[width:14px] [&_input]:[height:14px] [&_input]:[min-height:14px] [&_input]:[padding:0] [&_select]:[padding:0_8px] [&_input]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_input]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] [&_select]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_select]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  fieldWide:
    "grid [grid-column:1_/_-1] [gap:4px] min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32] [&_textarea]:[width:100%] [&_textarea]:min-w-0 [&_textarea]:[border:1px_solid_var(--vui-border-subtle)] [&_textarea]:[border-radius:var(--radius-control)] [&_textarea]:[background:var(--vui-surface-row)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-xs)] [&_textarea]:[min-height:62px] [&_textarea]:[resize:vertical] [&_textarea]:[padding:7px_9px] [&_textarea]:[line-height:1.35] [&_textarea]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_textarea]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  filterPanel:
    "min-w-0 min-h-0 [grid-template-rows:auto_minmax(0,_1fr)_auto] max-[1040px]:min-h-0 max-[860px]:[min-height:150px]",
  governanceActions:
    "inline-flex [align-items:center] [gap:6px] min-w-0",
  governanceEditorGrid:
    "grid [grid-template-columns:minmax(0,_1.4fr)_minmax(140px,_0.6fr)] [gap:7px] min-w-0",
  groupButton:
    "grid max-w-full [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:8px] [width:100%] [min-height:34px] [padding:6px_9px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [text-align:left] [transition:border-color_160ms_ease,_background_160ms_ease,_color_160ms_ease] hover:[border-color:var(--border-strong)] hover:[color:var(--fg-primary)] hover:[background:color-mix(in_srgb,_var(--vui-surface-row-hover)_70%,_transparent)] [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[gap:8px] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:inline-flex [&_strong]:[align-items:center] [&_strong]:[justify-content:center] [&_strong]:[min-width:22px] [&_strong]:[min-height:22px] [&_strong]:[border-radius:999px] [&_strong]:[font-style:normal] [&_strong]:[font-size:var(--vui-font-xs)] [&_em]:inline-flex [&_em]:[align-items:center] [&_em]:[justify-content:center] [&_em]:[min-width:22px] [&_em]:[min-height:22px] [&_em]:[border-radius:999px] [&_em]:[font-style:normal] [&_em]:[font-size:var(--vui-font-xs)] [&_strong]:[background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [&_strong]:[color:var(--accent-cool)] [&_em]:[gap:4px] [&_em]:[padding:0_7px] [&_em]:[background:color-mix(in_srgb,_var(--accent-warm)_12%,_transparent)] [&_em]:[color:var(--accent-warm-2)]",
  groupButtonActive:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_34%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--fg-primary)]",
  groupList:
    "grid [align-content:start] [gap:10px] min-h-0 [overflow:auto]",
  groupSection:
    "grid [gap:5px] min-w-0",
  groupSectionItems:
    "grid [gap:5px] min-w-0",
  groupSectionTitle:
    "[margin:0] [padding:0_2px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:700] [letter-spacing:0.08em] [line-height:1.2] [text-transform:uppercase]",
  healthCell:
    "flex [align-items:center] [justify-items:start] min-w-0",
  healthGuidePanel:
    "grid [gap:7px] min-w-0 [padding:8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-surface-panel)] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:760] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.38] [&_strong]:[margin-right:6px] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)]",
  healthGuide_blocking:
    "[border-color:color-mix(in_srgb,_var(--state-error)_28%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_7%,_var(--vui-surface-row))]",
  healthGuide_info:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_var(--vui-surface-row))]",
  healthGuide_ok:
    "[border-color:color-mix(in_srgb,_var(--state-success)_24%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_7%,_var(--vui-surface-row))]",
  healthGuide_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_var(--vui-surface-row))]",
  healthPill:
    "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  health_blocked:
    "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  health_ok:
    "[border-color:color-mix(in_srgb,_var(--state-success)_28%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_9%,_transparent)] [color:var(--state-success)]",
  health_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  iconButton:
    "grid w-[26px] h-[26px] [place-items:center] [width:26px] [height:26px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [font:inherit] [font-size:1rem] [cursor:pointer]",
  inboxMessageItem:
    "grid [gap:5px] min-w-0 max-w-full [padding:7px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[display:-webkit-box] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[-webkit-box-orient:vertical] [&_p]:[-webkit-line-clamp:2] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  inboxMessageItemFocused:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_transparent)] [box-shadow:none] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)]",
  inboxMessageList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:280px] [overflow:auto] [padding-right:3px]",
  inboxMessageTop:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0",
  inlineAdd:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:6px] min-w-0 [&_input]:min-w-0 [&_input]:[min-height:32px] [&_input]:[border-radius:var(--radius-control)] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:[width:100%] [&_input]:[padding:0_8px] [&_input]:[border:1px_solid_var(--vui-border-subtle)] [&_input]:[background:color-mix(in_srgb,_var(--surface-input)_84%,_transparent)] [&_input]:[color:var(--fg-primary)] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  issueItem:
    "grid [gap:4px] min-w-0 [padding:7px_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.4]",
  issueItem_blocking:
    "[border-color:color-mix(in_srgb,_var(--state-error)_32%,_transparent)]",
  issueItem_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_32%,_transparent)]",
  issueList:
    "grid [align-content:start] [gap:5px] min-w-0",
  issuePill:
    "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  issue_blocking:
    "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  issue_info:
    "[border-color:color-mix(in_srgb,_var(--accent-cool)_28%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [color:var(--accent-cool)]",
  issue_ok:
    "[border-color:color-mix(in_srgb,_var(--state-success)_28%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_9%,_transparent)] [color:var(--state-success)]",
  issue_warning:
    "[border-color:color-mix(in_srgb,_var(--accent-warm)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  llmSlotField:
    "grid [gap:5px] min-w-0 [padding:7px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_88%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_78%,_transparent)] [&_span]:grid [&_span]:[grid-template-columns:minmax(0,_1fr)_auto] [&_span]:[align-items:center] [&_span]:[gap:8px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:[display:-webkit-box] [&_small]:[min-height:32px] [&_small]:[overflow:hidden] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32] [&_small]:[-webkit-box-orient:vertical] [&_small]:[-webkit-line-clamp:2] [&_select]:[width:100%] [&_select]:min-w-0 [&_select]:[min-height:30px] [&_select]:[border:1px_solid_var(--vui-border-subtle)] [&_select]:[border-radius:var(--radius-control)] [&_select]:[background:var(--vui-surface-row)] [&_select]:[color:var(--fg-primary)] [&_select]:[font:inherit] [&_select]:[font-size:var(--vui-font-xs)] [&_select]:[padding:0_8px] [&_select]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_select]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  llmSlotGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:8px] min-w-0",
  maintenanceIntro:
    "grid [grid-template-columns:minmax(0,_0.8fr)_minmax(0,_1.2fr)] [align-items:center] [gap:10px] min-w-0 [padding:9px_10px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-row)_72%,_transparent)] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.36]",
  managementBriefHeader:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:10px] min-w-0 [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:inline-flex [&_strong]:[align-items:center] [&_strong]:[justify-content:center] [&_strong]:[width:42px] [&_strong]:[min-height:28px] [&_strong]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_30%,_transparent)] [&_strong]:[border-radius:var(--radius-control)] [&_strong]:[background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [&_strong]:[color:var(--accent-cool)] [&_strong]:[font-size:0.9rem]",
  managementBriefPanel:
    "grid [gap:7px] min-w-0 [padding:9px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_5%,_transparent)]",
  managementChecklist:
    "grid [grid-template-columns:repeat(5,_minmax(0,_1fr))] [gap:4px] min-w-0 [&_button]:inline-flex [&_button]:[align-items:center] [&_button]:[justify-content:center] [&_button]:[gap:4px] [&_button]:min-w-0 [&_button]:[min-height:26px] [&_button]:[padding:3px_5px] [&_button]:[border:1px_solid_var(--vui-border-subtle)] [&_button]:[border-radius:var(--radius-control)] [&_button]:[background:var(--vui-surface-row)] [&_button]:[color:var(--fg-secondary)] [&_svg]:[flex:0_0_auto] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:720] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_button]:hover:[background:var(--vui-surface-row-hover)]",
  managementChecklistDone:
    "w-full [&_svg]:[color:var(--state-success)]",
  managementChecklistMissing:
    "w-full [&_svg]:[color:var(--accent-warm)]",
  managementNav:
    "[margin:0] max-[1120px]:[justify-self:start]",
  memoryPolicyGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:6px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_var(--vui-border-subtle)] [&_section]:[border-radius:var(--radius-control)] [&_section]:[background:var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
  modeList:
    "flex [flex-wrap:wrap] [gap:3px] [&_em]:inline-flex [&_em]:[align-items:center] [&_em]:[min-height:22px] [&_em]:[padding:0_6px] [&_em]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_22%,_transparent)] [&_em]:[border-radius:999px] [&_em]:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [&_em]:[color:var(--accent-cool)] [&_em]:[font-style:normal] [&_em]:[font-size:var(--vui-font-xs)] [&_em]:[white-space:nowrap]",
  nextActionList:
    "grid [grid-template-columns:auto_repeat(3,_minmax(0,_1fr))] [align-items:stretch] [gap:5px] min-w-0 [&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:760] [&_span]:[white-space:nowrap] [&_button]:grid [&_button]:[gap:2px] [&_button]:min-w-0 [&_button]:[margin:0] [&_button]:[padding:6px_7px] [&_button]:[border:1px_solid_var(--vui-border-subtle)] [&_button]:[border-radius:var(--radius-control)] [&_button]:[background:color-mix(in_srgb,_var(--vui-surface-row)_78%,_transparent)] [&_button]:[color:var(--fg-secondary)] [&_button]:[text-align:left] [&_p]:grid [&_p]:[gap:2px] [&_p]:[margin:0] [&_p]:[padding:6px_7px] [&_p]:[border:1px_solid_var(--vui-border-subtle)] [&_p]:[border-radius:var(--radius-control)] [&_p]:[background:color-mix(in_srgb,_var(--vui-surface-row)_78%,_transparent)] [&_p]:[text-align:left] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_p]:[color:var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)]",
  panelEyebrow:
    "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  panelHeader:
    "flex [align-items:flex-start] [justify-content:space-between] [gap:8px] min-w-0 [&_div]:min-w-0",
  panelHeaderActions:
    "inline-flex [align-items:center] [justify-content:flex-end] [gap:8px] min-w-0",
  pathList:
    "[&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] grid [align-content:start] [gap:5px] min-w-0 [&_span]:[margin:0] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  pillList:
    "[&_span]:inline-flex [&_span]:[align-items:center] [&_span]:[min-height:22px] [&_span]:[padding:0_6px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_22%,_transparent)] [&_span]:[border-radius:999px] [&_span]:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [&_span]:[color:var(--accent-cool)] [&_span]:[font-style:normal] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[white-space:nowrap] [align-content:start] [gap:5px] min-w-0 flex [flex-wrap:wrap]",
  policyGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] [&_div]:min-w-0 [&_div]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_div]:[border-radius:var(--radius-control)] [&_div]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_div]:grid [&_div]:[grid-template-columns:auto_minmax(0,_1fr)] [&_div]:[grid-template-rows:auto_auto] [&_div]:[column-gap:8px] [&_div]:[row-gap:2px] [&_div]:[padding:7px_8px_8px] [&_svg]:[grid-column:1] [&_svg]:[grid-row:1_/_3] [&_svg]:[color:var(--accent-cool)] [&_span]:[grid-column:2] [&_span]:[grid-row:1] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[grid-column:2] [&_strong]:[grid-row:2] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] max-[860px]:[grid-template-columns:1fr]",
  policyHint:
    "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.42] [overflow-wrap:anywhere]",
  policySummaryGrid:
    "grid [grid-template-columns:repeat(4,_minmax(0,_1fr))] [gap:6px] min-w-0 max-w-full [&_span]:min-w-0 [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)]",
  primaryButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_38%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_16%,_transparent)] [color:var(--accent-cool)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  promptConfigField:
    "[gap:6px]",
  promptConfigRow:
    "grid [grid-template-columns:minmax(0,_1fr)_max-content] [align-items:center] [gap:6px] min-w-0 [&_select]:min-w-0 [&_[data-vui=\"button\"]]:[white-space:nowrap] [&_select]:focus:[outline:2px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_select]:focus:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)]",
  protectedZone:
    "[&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.42] [&_p]:[overflow-wrap:anywhere] grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_7%,_transparent)] [&_svg]:[color:var(--accent-cool)]",
  referenceHeader:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:6px] min-w-0",
  referenceItem:
    "[&_small]:[grid-area:meta] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] grid [gap:4px] min-w-0 [padding:7px_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[margin:0] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  referenceList:
    "grid [align-content:start] [gap:5px] min-w-0",
  referenceMetaRow:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:6px] min-w-0",
  referenceStatusActive:
    "inline-flex [align-items:center] [min-height:19px] [padding:0_6px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:760] [text-transform:uppercase] [white-space:nowrap] [border-color:color-mix(in_srgb,_var(--state-success)_28%,_transparent)] [background:color-mix(in_srgb,_var(--state-success)_8%,_transparent)] [color:var(--state-success)]",
  referenceStatusStale:
    "inline-flex [align-items:center] [min-height:19px] [padding:0_6px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:760] [text-transform:uppercase] [white-space:nowrap] [border-color:color-mix(in_srgb,_var(--accent-warm)_32%,_transparent)] [background:color-mix(in_srgb,_var(--accent-warm)_10%,_transparent)] [color:var(--accent-warm-2)]",
  resetOptionField:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:start] [gap:8px] min-w-0 [min-height:58px] [padding:7px_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [&_input]:[margin-top:3px] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow-wrap:anywhere] [&_small]:min-w-0 [&_small]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.32]",
  resetOptionGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] min-w-0 max-[860px]:[grid-template-columns:1fr]",
  resetZone:
    "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--state-warning)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--state-warning)_7%,_transparent)] [&_svg]:[color:var(--state-warning)]",
  returnBanner:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:10px] min-w-0 [padding:9px_10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_38%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_8%,_var(--vui-surface-panel))] [box-shadow:none] max-[860px]:[grid-template-columns:1fr]",
  returnBannerButton:
    "inline-flex w-fit max-w-full max-[860px]:w-fit [align-items:center] [justify-content:center] [gap:6px] [min-width:116px] [min-height:34px] [padding:0_12px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_68%,_var(--vui-border-subtle))] [border-radius:var(--radius-control)] [background:var(--accent-cool)] [color:var(--accent-cool-contrast)] [font-size:var(--vui-font-xs)] [font-weight:800] [white-space:nowrap] [cursor:pointer] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_86%,_var(--vui-border-subtle))] hover:[background:color-mix(in_srgb,_var(--accent-cool)_90%,_var(--fg-primary))] hover:[outline:none] hover:[box-shadow:var(--focus-ring)] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_86%,_var(--vui-border-subtle))] focus-visible:[background:color-mix(in_srgb,_var(--accent-cool)_90%,_var(--fg-primary))] focus-visible:[outline:none] focus-visible:[box-shadow:var(--focus-ring)]",
  returnBannerCopy:
    "grid [gap:2px] min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:820] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.25] max-[860px]:[&_span]:[white-space:normal]",
  roomCheckField:
    "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:36px] [padding:6px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [&_input]:[margin:0] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  roomMembershipList:
    "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  route:
    "grid max-w-full [grid-template-rows:auto_minmax(0,_1fr)] [height:100%] min-h-0 [overflow:hidden] [--agent-density-gap:0px] [--agent-panel-pad:8px] [--agent-row-pad-y:6px] [--agent-control-height:24px] [&_[data-vui-product=\"agent-workspace-panel\"]]:max-w-full [&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-hidden [&_[data-vui-product=\"agent-workspace-panel\"]]:[scrollbar-gutter:stable] [&_[data-vui-product=\"agent-workspace-panel\"]]:[overflow-wrap:anywhere] [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap] max-[860px]:[height:100%] max-[860px]:min-h-0 max-[860px]:[grid-template-rows:auto_minmax(0,_1fr)] max-[860px]:[overflow:hidden] max-[860px]:[&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-visible",
  rowSelect:
    "grid [place-items:center] [width:28px] [height:36px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] [cursor:pointer] hover:[border-color:var(--border-strong)] hover:[color:var(--accent-warm-2)] [&_input]:[position:absolute] [&_input]:[width:1px] [&_input]:[height:1px] [&_input]:[opacity:0] [&_input]:[pointer-events:none]",
  runHistoryItem:
    "grid [gap:3px] min-w-0 max-w-full [padding:7px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  runHistoryList:
    "grid [align-content:start] [gap:5px] min-w-0 [max-height:260px] [overflow:auto] [padding-right:3px]",
  runtimeEvidenceHint:
    "grid [grid-template-columns:auto_auto_minmax(0,_1fr)] [gap:8px] [align-items:center] min-w-0 max-w-full [padding:8px_10px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[text-transform:uppercase] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] [&_code]:[color:var(--fg-primary)] [&_code]:[font-family:var(--font-mono,_ui-monospace,_SFMono-Regular,_Consolas,_monospace)] [&_code]:[font-size:var(--vui-font-xs)]",
  runtimeFocusHeader:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:10px] [align-items:center] min-w-0",
  runtimeFocusMeta:
    "[&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap] grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] min-w-0 [&_span]:grid [&_span]:[gap:3px] [&_span]:min-w-0 [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_span]:[border-radius:var(--radius-control)] [&_span]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[text-transform:uppercase] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-family:var(--font-mono,_ui-monospace,_SFMono-Regular,_Consolas,_monospace)] [&_code]:[font-size:var(--vui-font-xs)]",
  runtimeFocusPanel:
    "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_6%,_var(--vui-surface-panel))] [box-shadow:none] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)]",
  runtimeNextStep:
    "grid [gap:4px] min-w-0 [padding:9px_10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-warm)_20%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--accent-warm)_7%,_transparent)] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[text-transform:uppercase] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.4]",
  runtimePill:
    "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  runtimePolicyGrid:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:7px] min-w-0 max-w-full [&_section]:grid [&_section]:[align-content:start] [&_section]:[gap:7px] [&_section]:min-w-0 [&_section]:[padding:8px] [&_section]:[border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [&_section]:[border-radius:var(--radius-control)] [&_section]:[background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:700] max-[860px]:[grid-template-columns:1fr]",
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
  searchBox:
    "flex [align-items:center] [gap:8px] [min-height:32px] [padding:0_9px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--surface-input)_84%,_transparent)] [color:var(--fg-tertiary)] focus-within:[border-color:color-mix(in_srgb,_var(--accent-cool)_44%,_transparent)] focus-within:[box-shadow:var(--focus-ring)] focus-within:[color:var(--fg-secondary)] [&_input]:min-w-0 [&_input]:[width:100%] [&_input]:[border:0] [&_input]:[outline:0] [&_input]:[background:transparent] [&_input]:[color:var(--fg-primary)] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-xs)]",
  secondaryButton:
    "inline-flex w-fit max-w-full [align-items:center] [justify-content:center] [gap:7px] [min-height:30px] [padding:0_10px] [border-radius:var(--radius-control)] [font-weight:700] [border:1px_solid_var(--vui-border-subtle)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [color:var(--fg-secondary)] disabled:[cursor:not-allowed] disabled:[opacity:0.55]",
  segmentActive:
    "inline-flex [align-items:center] [justify-content:center] [min-height:24px] [padding:0_7px] [border:1px_solid_transparent] [border-radius:calc(var(--radius-control)_-_2px)] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap] [border-color:color-mix(in_srgb,_var(--accent-cool)_30%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [color:var(--accent-cool)]",
  segmentActiveDanger:
    "inline-flex [align-items:center] [justify-content:center] [min-height:24px] [padding:0_7px] [border:1px_solid_transparent] [border-radius:calc(var(--radius-control)_-_2px)] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap] [border-color:color-mix(in_srgb,_var(--state-error)_30%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  segmentButton:
    "inline-flex [align-items:center] [justify-content:center] [min-height:24px] [padding:0_7px] [border:1px_solid_transparent] [border-radius:calc(var(--radius-control)_-_2px)] [background:transparent] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap] hover:[background:var(--vui-surface-row-hover)] hover:[color:var(--fg-secondary)]",
  segmentedControl:
    "inline-grid max-w-full [grid-template-columns:repeat(3,_minmax(56px,_auto))] [gap:3px] [padding:3px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)]",
  storagePanel:
    "grid [gap:5px] min-w-0 max-w-full [padding:8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_58%,_transparent)] [&_code]:min-w-0 [&_code]:[overflow:hidden] [&_code]:[color:var(--fg-secondary)] [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[text-overflow:ellipsis] [&_code]:[white-space:nowrap]",
  successText:
    "[margin:0] [font-size:var(--vui-font-xs)] [line-height:1.4] [overflow-wrap:anywhere] [color:var(--state-success)]",
  tagList:
    "flex [flex-wrap:wrap] [gap:5px] min-w-0 [min-height:28px] [&_button]:inline-flex [&_button]:[align-items:center] [&_button]:[min-height:24px] [&_button]:[max-width:100%] [&_button]:[padding:0_7px] [&_button]:[border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)] [&_button]:[border-radius:999px] [&_button]:[background:color-mix(in_srgb,_var(--accent-cool)_8%,_transparent)] [&_button]:[color:var(--accent-cool)] [&_button]:[font-size:var(--vui-font-xs)] [&_button]:[overflow:hidden] [&_button]:[text-overflow:ellipsis] [&_button]:[white-space:nowrap] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  timelineActions:
    "flex [flex-wrap:wrap] [gap:5px] min-w-0 max-w-full [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:[max-width:100%] [&_[data-vui=\"button\"]]:[white-space:nowrap]",
  title:
    "[margin:0] [font-family:var(--font-body)] [font-size:0.95rem] [font-weight:760] [line-height:1.1] [white-space:nowrap] max-[860px]:[white-space:normal]",
  toggleGrid:
    "grid [grid-template-columns:repeat(3,_minmax(0,_1fr))] [gap:6px] max-[860px]:[grid-template-columns:1fr]",
  toolBundleActions:
    "[grid-column:2] [grid-row:1_/_3] inline-flex [align-items:center] [gap:5px] min-w-0",
  toolBundleItem:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [grid-template-rows:auto_auto] [align-items:center] [gap:4px_8px] min-w-0 max-w-full [padding:7px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_span]:[grid-column:1] [&_span]:[grid-row:1] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_p]:[grid-column:1] [&_p]:[grid-row:2] [&_p]:[margin:0] [&_p]:min-w-0 [&_p]:[overflow:hidden] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.35] [&_p]:[text-overflow:ellipsis] [&_p]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
  toolBundleList:
    "grid [grid-template-columns:repeat(2,_minmax(0,_1fr))] [gap:6px] min-w-0 [max-height:210px] [overflow:auto] [padding-right:3px] max-[860px]:[grid-template-columns:1fr]",
  toolBundlePanel:
    "grid [gap:7px] min-w-0 [padding:8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-panel)_72%,_transparent)]",
  toolBundlePanelHeader:
    "grid [gap:2px] min-w-0 [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  toolGovernanceItem:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 max-w-full [padding:8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_div]:first-child:grid [&_div]:first-child:[gap:3px] [&_div]:first-child:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  toolGovernanceList:
    "grid [align-content:start] [gap:7px] min-w-0 [max-height:220px] [overflow:auto] [padding-right:3px]",
  toolPermissionGroup:
    "grid [gap:6px] min-w-0 max-w-full [padding:7px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)]",
  toolPermissionGroupHeader:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[padding:3px_7px] [&_small]:[border:1px_solid_color-mix(in_srgb,_var(--state-error)_22%,_transparent)] [&_small]:[border-radius:999px] [&_small]:[background:color-mix(in_srgb,_var(--state-error)_8%,_transparent)] [&_small]:[color:var(--state-error)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[font-weight:700]",
  toolPermissionGroupList:
    "grid [gap:5px] min-w-0",
  toolPermissionList:
    "grid [align-content:start] [gap:9px] min-w-0 [max-height:300px] [overflow:auto] [padding-right:3px]",
  toolPermissionMeta:
    "flex [align-items:center] [gap:6px] min-w-0 [color:var(--fg-tertiary)] [&_em]:[flex:0_0_auto] [&_em]:[padding:2px_5px] [&_em]:[border-radius:999px] [&_em]:[background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [&_em]:[color:var(--accent-cool)] [&_em]:[font-size:var(--vui-font-xs)] [&_em]:[font-style:normal] [&_em]:[font-weight:700] [&_small]:min-w-0 [&_small]:[color:var(--fg-tertiary)]",
  toolPermissionRow:
    "grid [grid-template-columns:minmax(0,_1fr)_auto] [align-items:center] [gap:8px] min-w-0 max-w-full [min-height:40px] [padding:6px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_span]:grid [&_span]:[gap:2px] [&_span]:min-w-0 [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  workspaceScopePanel:
    "grid [grid-template-columns:minmax(0,_1fr)_auto_auto] [align-items:center] [gap:6px] min-w-0 max-w-full [padding:7px_8px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:var(--radius-control)] [background:color-mix(in_srgb,_var(--vui-surface-row)_58%,_transparent)] [&_div]:grid [&_div]:[gap:2px] [&_div]:min-w-0 [&_span]:min-w-0 [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] [&_small]:min-w-0 [&_small]:[overflow:hidden] [&_small]:[text-overflow:ellipsis] [&_small]:[white-space:nowrap] [&_strong]:min-w-0 [&_strong]:[overflow:hidden] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-secondary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-template-columns:1fr]",
} as const;

export default styles;
