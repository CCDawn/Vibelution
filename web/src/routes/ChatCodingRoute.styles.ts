// ChatCodingRoute styles (Wave 8D dead-key prune after 8C panel extraction).
// Removed 116 unused keys; panel/component maps own former residue.

import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
  vuiRailFillClass,
  vuiStateCoolInfoClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSuccessSoftClass,
  vuiStateWarmSoftClass,
  vuiStateWarningSoftClass,
  vuiChatFillClass,
} from "../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  activeSkillStatus_active:
    `vui-routes-chatcodingroute activeSkillStatus_active min-w-0 ${vuiStateSelectedRowClass}`,
  activeSkillStatus_missing:
    `vui-routes-chatcodingroute activeSkillStatus_missing min-w-0 ${vuiStateSelectedRowClass}`,
  activeSkillStatus_stale:
    `vui-routes-chatcodingroute activeSkillStatus_stale min-w-0 ${vuiStateSelectedRowClass}`,
  agentAvatarImage:
    `vui-routes-chatcodingroute agentAvatarImage min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateCoolInfoClass}`,
  agentOptionAvatar:
    `vui-routes-chatcodingroute agentOptionAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateCoolInfoClass}`,
  agentRoleTag:
    `vui-routes-chatcodingroute agentRoleTag min-w-0 ${vuiControlPillClass} ${vuiStateCoolInfoClass}`,
  agentRoleTag_chat:
    `vui-routes-chatcodingroute agentRoleTag_chat min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_general:
    `vui-routes-chatcodingroute agentRoleTag_general min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_memory:
    `vui-routes-chatcodingroute agentRoleTag_memory min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_research:
    `vui-routes-chatcodingroute agentRoleTag_research min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_self:
    `vui-routes-chatcodingroute agentRoleTag_self min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_supervised:
    `vui-routes-chatcodingroute agentRoleTag_supervised min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_tool:
    `vui-routes-chatcodingroute agentRoleTag_tool min-w-0 ${vuiStateCoolInfoClass}`,
  blockEyebrow:
    "vui-routes-chatcodingroute blockEyebrow min-w-0 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  sectionEyebrowRow:
    "vui-routes-chatcodingroute sectionEyebrowRow flex min-w-0 items-center gap-1",
  // Wave 6H dialog policy: viewport clamp only — not workbench pane-heights.,
  centerPane:
    `vui-routes-chatcodingroute centerPane min-w-0 grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${vuiChatFillClass} [grid-column:3] [grid-row:1]`,
  centerPaneOverlay:
    "vui-routes-chatcodingroute centerPaneOverlay [grid-column:1] [grid-row:1]",
  centerSurface:
    `vui-routes-chatcodingroute centerSurface grid h-full min-h-0 overflow-hidden ${vuiChatFillClass}`,
  chatReturnLink:
    "vui-routes-chatcodingroute chatReturnLink min-w-0 [&_span]:truncate",
  contextCompositionSegmentAgent:
    `vui-routes-chatcodingroute contextCompositionSegmentAgent min-w-0 ${vuiStateCoolInfoClass}`,
  contextCompositionSegmentAttachments:
    `vui-routes-chatcodingroute contextCompositionSegmentAttachments min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentGuidance:
    `vui-routes-chatcodingroute contextCompositionSegmentGuidance min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentHistory:
    `vui-routes-chatcodingroute contextCompositionSegmentHistory min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentOther:
    `vui-routes-chatcodingroute contextCompositionSegmentOther min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentSkill:
    `vui-routes-chatcodingroute contextCompositionSegmentSkill min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentTask:
    `vui-routes-chatcodingroute contextCompositionSegmentTask min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUser:
    `vui-routes-chatcodingroute contextCompositionSegmentUser min-w-0 ${vuiStateWarmSoftClass}`,
  contextLineCompact: `vui-routes-chatcodingroute contextLineCompact min-w-0 ${vuiOpaqueRowClass} px-1.5 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] leading-snug shadow-none [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] overflow-hidden [overflow-wrap:anywhere]`,
  layout:
    "vui-routes-chatcodingroute layout relative min-w-0 grid !gap-0 !p-0 [--chat-workbench-gap:4px] [--chat-pane-gutter:0px] h-[calc(100dvh_-_var(--shell-topbar-height))] max-h-[calc(100dvh_-_var(--shell-topbar-height))] overflow-hidden grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)_var(--chat-pane-gutter)_var(--chat-right-pane-width,240px)]",
  layoutCompactDesktop:
    "vui-routes-chatcodingroute layoutCompactDesktop grid min-w-0 grid-cols-[minmax(220px,var(--chat-left-pane-width,248px))_var(--chat-pane-gutter)_minmax(0,1fr)] overflow-hidden",
  layoutStatusRailCollapsed:
    "vui-routes-chatcodingroute layoutStatusRailCollapsed grid !grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)]",
  layoutOverlay:
    "vui-routes-chatcodingroute layoutOverlay relative grid min-w-0 grid-cols-[minmax(0,1fr)] overflow-hidden",
  leftBlock:
    "vui-routes-chatcodingroute leftBlock grid min-w-0 shrink-0 gap-1.5 border-0 border-b border-[var(--vui-border-subtle)] bg-transparent p-2 shadow-none last:border-b-0",
  // Use non-important flex so paneCollapsed `!hidden` always wins when the status rail is closed.
  // Important flex + grid-column:5 previously forced implicit tracks and a blank right strip.,
  leftRail: `vui-routes-chatcodingroute leftRail min-w-0 flex h-full min-h-0 flex-col overflow-auto rounded-none border-0 border-l border-[var(--vui-border-subtle)] ${vuiRailFillClass} p-1 shadow-none [scrollbar-gutter:stable] [grid-column:5] [grid-row:1]`,
  mentalStateBadge:
    `vui-routes-chatcodingroute mentalStateBadge min-w-0 ${vuiControlPillClass}`,
  oneLineValue: `vui-routes-chatcodingroute oneLineValue min-w-0 ${vuiOpaqueRowClass} px-1.5 py-1 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&_span]:mr-1.5 [&_span]:font-semibold [&_span]:text-[var(--fg-tertiary)]`,
  paneCollapsed:
    "vui-routes-chatcodingroute paneCollapsed min-w-0 !hidden invisible pointer-events-none !overflow-hidden opacity-0",
  overlayBackdrop:
    "vui-routes-chatcodingroute overlayBackdrop fixed inset-0 z-30 border-0 bg-black/35",
  overlayPane:
    `vui-routes-chatcodingroute overlayPane fixed inset-y-[var(--shell-topbar-height)] z-40 w-[min(86vw,320px)] ${vuiRailFillClass} shadow-[var(--vui-elevation-panel)]`,
  overlayPaneControls:
    "vui-routes-chatcodingroute overlayPaneControls ml-auto flex min-w-0 items-center gap-1",
  overlayPaneLeft:
    "vui-routes-chatcodingroute overlayPaneLeft left-0",
  overlayPaneRight:
    "vui-routes-chatcodingroute overlayPaneRight right-0",
  overlayPaneToggle:
    "vui-routes-chatcodingroute overlayPaneToggle inline-flex min-h-[30px] items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)]",
  panelNotice:
    "vui-routes-chatcodingroute panelNotice grid min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_5%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)]",
  panelState:
    "vui-routes-chatcodingroute panelState min-h-[72px] place-items-center !content-center !text-center",
  petShowcaseAvatar_active:
    `vui-routes-chatcodingroute petShowcaseAvatar_active min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateSelectedRowClass}`,
  petShowcaseAvatar_answering:
    "vui-routes-chatcodingroute petShowcaseAvatar_answering min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_blocked:
    `vui-routes-chatcodingroute petShowcaseAvatar_blocked min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateWarningSoftClass}`,
  petShowcaseAvatar_bunny:
    "vui-routes-chatcodingroute petShowcaseAvatar_bunny min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_cache:
    "vui-routes-chatcodingroute petShowcaseAvatar_cache min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_cat:
    "vui-routes-chatcodingroute petShowcaseAvatar_cat min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_chat:
    "vui-routes-chatcodingroute petShowcaseAvatar_chat min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_checking:
    "vui-routes-chatcodingroute petShowcaseAvatar_checking min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_chick:
    "vui-routes-chatcodingroute petShowcaseAvatar_chick min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_compression:
    "vui-routes-chatcodingroute petShowcaseAvatar_compression min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_crab:
    "vui-routes-chatcodingroute petShowcaseAvatar_crab min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_danger:
    `vui-routes-chatcodingroute petShowcaseAvatar_danger min-w-0 ${vuiStateDangerSoftClass} inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]`,
  petShowcaseAvatar_default:
    "vui-routes-chatcodingroute petShowcaseAvatar_default min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_disoriented:
    "vui-routes-chatcodingroute petShowcaseAvatar_disoriented min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_done:
    "vui-routes-chatcodingroute petShowcaseAvatar_done min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_editing:
    "vui-routes-chatcodingroute petShowcaseAvatar_editing min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_error:
    `vui-routes-chatcodingroute petShowcaseAvatar_error min-w-0 ${vuiStateDangerSoftClass} inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]`,
  petShowcaseAvatar_failed:
    `vui-routes-chatcodingroute petShowcaseAvatar_failed min-w-0 ${vuiStateDangerSoftClass} inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]`,
  petShowcaseAvatar_general:
    "vui-routes-chatcodingroute petShowcaseAvatar_general min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_healthy:
    "vui-routes-chatcodingroute petShowcaseAvatar_healthy min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_idle:
    "vui-routes-chatcodingroute petShowcaseAvatar_idle min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  petShowcaseAvatar_info:
    `vui-routes-chatcodingroute petShowcaseAvatar_info min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateCoolInfoClass}`,
  petShowcaseAvatar_lobster:
    "vui-routes-chatcodingroute petShowcaseAvatar_lobster min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_looping:
    "vui-routes-chatcodingroute petShowcaseAvatar_looping min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_memory:
    "vui-routes-chatcodingroute petShowcaseAvatar_memory min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_mental:
    "vui-routes-chatcodingroute petShowcaseAvatar_mental min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_missing:
    "vui-routes-chatcodingroute petShowcaseAvatar_missing min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_modelInput:
    "vui-routes-chatcodingroute petShowcaseAvatar_modelInput min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  petShowcaseAvatar_moose:
    "vui-routes-chatcodingroute petShowcaseAvatar_moose min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_muted:
    "vui-routes-chatcodingroute petShowcaseAvatar_muted min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  petShowcaseAvatar_needs_input:
    "vui-routes-chatcodingroute petShowcaseAvatar_needs_input min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  petShowcaseAvatar_neutral:
    "vui-routes-chatcodingroute petShowcaseAvatar_neutral min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_normal:
    "vui-routes-chatcodingroute petShowcaseAvatar_normal min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_offline:
    "vui-routes-chatcodingroute petShowcaseAvatar_offline min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_ok:
    `vui-routes-chatcodingroute petShowcaseAvatar_ok min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateSuccessSoftClass}`,
  petShowcaseAvatar_pending:
    "vui-routes-chatcodingroute petShowcaseAvatar_pending min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_penguin:
    "vui-routes-chatcodingroute petShowcaseAvatar_penguin min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_planning:
    "vui-routes-chatcodingroute petShowcaseAvatar_planning min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_productive:
    "vui-routes-chatcodingroute petShowcaseAvatar_productive min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_reading:
    "vui-routes-chatcodingroute petShowcaseAvatar_reading min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_ready:
    `vui-routes-chatcodingroute petShowcaseAvatar_ready min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateSuccessSoftClass}`,
  petShowcaseAvatar_research:
    "vui-routes-chatcodingroute petShowcaseAvatar_research min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_running:
    `vui-routes-chatcodingroute petShowcaseAvatar_running min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateSuccessSoftClass}`,
  petShowcaseAvatar_self:
    "vui-routes-chatcodingroute petShowcaseAvatar_self min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_shrimp:
    "vui-routes-chatcodingroute petShowcaseAvatar_shrimp min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_slime:
    "vui-routes-chatcodingroute petShowcaseAvatar_slime min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_stale:
    "vui-routes-chatcodingroute petShowcaseAvatar_stale min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_status:
    "vui-routes-chatcodingroute petShowcaseAvatar_status min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_success:
    `vui-routes-chatcodingroute petShowcaseAvatar_success min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateSuccessSoftClass}`,
  petShowcaseAvatar_supervised:
    "vui-routes-chatcodingroute petShowcaseAvatar_supervised min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_thinking:
    "vui-routes-chatcodingroute petShowcaseAvatar_thinking min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_thought:
    "vui-routes-chatcodingroute petShowcaseAvatar_thought min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_thrashing:
    "vui-routes-chatcodingroute petShowcaseAvatar_thrashing min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_tool:
    `vui-routes-chatcodingroute petShowcaseAvatar_tool min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateWarmSoftClass}`,
  petShowcaseAvatar_tooling:
    "vui-routes-chatcodingroute petShowcaseAvatar_tooling min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_tunnel_vision:
    "vui-routes-chatcodingroute petShowcaseAvatar_tunnel_vision min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_unhealthy:
    "vui-routes-chatcodingroute petShowcaseAvatar_unhealthy min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_unknown:
    "vui-routes-chatcodingroute petShowcaseAvatar_unknown min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_verifying:
    "vui-routes-chatcodingroute petShowcaseAvatar_verifying min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_waiting:
    "vui-routes-chatcodingroute petShowcaseAvatar_waiting min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_warn:
    "vui-routes-chatcodingroute petShowcaseAvatar_warn min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAvatar_warning:
    `vui-routes-chatcodingroute petShowcaseAvatar_warning min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateWarningSoftClass}`,
  resizeHandleLeft:
    "vui-routes-chatcodingroute resizeHandleLeft h-full w-full min-w-0 max-[860px]:block [grid-column:2] [grid-row:1]",
  resizeHandleRight:
    "vui-routes-chatcodingroute resizeHandleRight h-full w-full min-w-0 max-[860px]:block [grid-column:4] [grid-row:1]",
  resourceMetric:
    "vui-routes-chatcodingroute resourceMetric min-w-0",
  resourceSplit:
    "vui-routes-chatcodingroute resourceSplit min-w-0 !grid grid-cols-[repeat(auto-fit,minmax(118px,1fr))] gap-[5px]",
  rightPane: `vui-routes-chatcodingroute rightPane min-w-0 grid h-full min-h-0 gap-[var(--chat-workbench-gap)] overflow-hidden rounded-none border-0 border-r border-[var(--vui-border-subtle)] ${vuiRailFillClass} p-[var(--chat-workbench-gap)] shadow-none [grid-column:1] [grid-row:1]`,
  rightPaneWithTabs:
    "vui-routes-chatcodingroute rightPaneWithTabs grid-rows-[auto_auto_minmax(0,1fr)]",
  rightPaneWithoutTabs:
    "vui-routes-chatcodingroute rightPaneWithoutTabs grid-rows-[auto_minmax(0,1fr)]",
  sectionHeader:
    "vui-routes-chatcodingroute sectionHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_max-content] items-start gap-1.5",
  sectionIdentity:
    "vui-routes-chatcodingroute sectionIdentity grid min-w-0 gap-0.5",
  sectionTitle:
    "vui-routes-chatcodingroute sectionTitle m-0 min-w-0 truncate [font-size:var(--vui-font-sm)] font-[760] leading-tight text-[var(--fg-primary)]",
  // Section labels (运行模式 / Token / 陪伴): quieter than surface titles.,
  railSectionHeading:
    "vui-routes-chatcodingroute railSectionHeading m-0 min-w-0 truncate [font-size:var(--vui-font-xs)] font-[650] leading-tight text-[var(--fg-secondary)]",
  sessionLoadMoreButton:
    `vui-routes-chatcodingroute sessionLoadMoreButton min-w-0 ${vuiControlQuietClass}`,
  sessionLoadMoreStatus:
    "vui-routes-chatcodingroute sessionLoadMoreStatus min-w-0",
  tab:
    `vui-routes-chatcodingroute tab min-w-0 ${vuiControlQuietClass}`,
  tabActive:
    `vui-routes-chatcodingroute tabActive min-w-0 ${vuiStateSelectedRowClass}`,
  tabStrip:
    "vui-routes-chatcodingroute tabStrip min-w-0 flex h-9 items-end gap-1 overflow-hidden border-b border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] px-1 pt-1",

};

export default styles;
