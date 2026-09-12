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
  vuiStateSelectedRowClass,
  vuiStateWarmSoftClass,
  vuiChatFillClass,
} from "../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
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
    `vui-routes-chatcodingroute centerPane min-w-0 w-full grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${vuiChatFillClass} [grid-column:3] [grid-row:1]`,
  centerPaneOverlay:
    "vui-routes-chatcodingroute centerPaneOverlay [grid-column:1] [grid-row:1]",
  centerSurface:
    `vui-routes-chatcodingroute centerSurface grid h-full min-h-0 w-full overflow-hidden ${vuiChatFillClass}`,
  // Compact back chip: never compete with session tabs for width.
  chatReturnLink:
    "vui-routes-chatcodingroute chatReturnLink inline-flex h-7 max-w-[7.5rem] shrink-0 items-center gap-1 self-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 no-underline [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)] [&_span]:min-w-0 [&_span]:truncate",
  chatReturnLinkIcon:
    "vui-routes-chatcodingroute chatReturnLinkIcon shrink-0 text-[var(--fg-tertiary)]",
  // Session + file tabs share one scroll region so the back chip stays pinned left.
  tabStripSessions:
    "vui-routes-chatcodingroute tabStripSessions min-w-0 flex flex-1 items-end gap-1 overflow-x-auto overflow-y-hidden [scrollbar-width:thin]",
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
    "vui-routes-chatcodingroute layout relative w-full min-w-0 grid !gap-0 !p-0 [--chat-workbench-gap:4px] [--chat-pane-gutter:0px] h-[calc(100dvh_-_var(--shell-topbar-height))] max-h-[calc(100dvh_-_var(--shell-topbar-height))] overflow-hidden grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)_var(--chat-pane-gutter)_var(--chat-right-pane-width,240px)]",
  layoutCompactDesktop:
    "vui-routes-chatcodingroute layoutCompactDesktop w-full grid min-w-0 grid-cols-[minmax(220px,var(--chat-left-pane-width,248px))_var(--chat-pane-gutter)_minmax(0,1fr)] overflow-hidden",
  layoutStatusRailCollapsed:
    "vui-routes-chatcodingroute layoutStatusRailCollapsed w-full grid !grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)]",
  layoutOverlay:
    "vui-routes-chatcodingroute layoutOverlay relative w-full grid min-w-0 grid-cols-[minmax(0,1fr)] overflow-hidden",
  // Rail sections separate by whitespace rhythm (p-2 vertical), not hairline rules;
  // state emphasis moves to the active block accent (currentSessionBlock_active).
  leftBlock:
    "vui-routes-chatcodingroute leftBlock grid min-w-0 shrink-0 gap-1.5 border-0 bg-transparent p-2 shadow-none",
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
  // ml-auto only when this block is the last flex child (narrow overlay toggles).
  // Never put ml-auto on the first tabStrip child — it pushes session tabs to the right.
  overlayPaneControls:
    "vui-routes-chatcodingroute overlayPaneControls ml-auto flex min-w-0 shrink-0 items-center gap-1",
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
  // Section labels (运行模式 / Token / 陪伴): smaller than surface titles but primary-ink
  // so the rail scans as titled groups after hairline separators were removed.
  railSectionHeading:
    "vui-routes-chatcodingroute railSectionHeading m-0 min-w-0 truncate [font-size:var(--vui-font-xs)] font-[650] leading-tight text-[var(--fg-primary)]",
  conversationIndexToggle:
    "vui-routes-chatcodingroute conversationIndexToggle !size-[30px] !min-h-[30px] !min-w-[30px] !border-0 !bg-transparent text-[var(--fg-secondary)] shadow-none hover:!bg-[var(--vui-control-muted-hover)]",
  sessionBulkBar:
    "vui-routes-chatcodingroute sessionBulkBar mx-2 mb-2 min-w-0",
  tab:
    `vui-routes-chatcodingroute tab min-w-0 ${vuiControlQuietClass}`,
  tabActive:
    `vui-routes-chatcodingroute tabActive min-w-0 ${vuiStateSelectedRowClass}`,
  tabStrip:
    "vui-routes-chatcodingroute tabStrip min-w-0 flex h-9 items-center gap-1.5 overflow-hidden border-b border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] px-1.5 pt-1",

};

export default styles;
