// ChatCodingRoute styles (Wave 8C prune + panel extraction).
// Panel-owned maps: CacheDetailDialog, TokenCoreStatusPanel, ChatConversationIndexRail, ChatStatusRail.
// Remaining keys: shell/layout shared + multi-consumer + layout-test contracts still on this map.

import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiGlassPanelClass,
  vuiOpaqueRowClass,
  vuiRailFillClass,
  vuiStateCoolInfoClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSuccessSoftClass,
  vuiStateWarmSoftClass,
  vuiStateWarningSoftClass,
  vuiChatFillClass,
  vuiWorkspaceFillClass,
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
  agentMention:
    `vui-routes-chatcodingroute agentMention min-w-0 ${vuiStateCoolInfoClass}`,
  agentMissingLine: `vui-routes-chatcodingroute agentMissingLine min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateCoolInfoClass}`,
  agentModelTitleTag:
    "vui-routes-chatcodingroute agentModelTitleTag max-w-[96px]",
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
  agentSessionTab:
    `vui-routes-chatcodingroute agentSessionTab min-w-0 ${vuiControlQuietClass} ${vuiStateCoolInfoClass}`,
  agentSessionTabActive:
    `vui-routes-chatcodingroute agentSessionTabActive min-w-0 ${vuiStateSelectedRowClass}`,
  agentSessionTabContextTarget:
    `vui-routes-chatcodingroute agentSessionTabContextTarget min-w-0 ${vuiStateSelectedRowClass}`,
  agentSessionTabChild:
    `vui-routes-chatcodingroute agentSessionTabChild min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabCli:
    `vui-routes-chatcodingroute agentSessionTabCli min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabClosable:
    `vui-routes-chatcodingroute agentSessionTabClosable min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabCloseButton:
    `vui-routes-chatcodingroute agentSessionTabCloseButton min-w-0 ${vuiControlQuietClass} ${vuiStateCoolInfoClass}`,
  agentSessionTabCopy:
    `vui-routes-chatcodingroute agentSessionTabCopy min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] ${vuiStateCoolInfoClass}`,
  agentSessionTabCopyCompact:
    `vui-routes-chatcodingroute agentSessionTabCopyCompact min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] ${vuiStateCoolInfoClass}`,
  agentSessionTabEditActions:
    `vui-routes-chatcodingroute agentSessionTabEditActions min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  agentSessionTabEditButton:
    `vui-routes-chatcodingroute agentSessionTabEditButton min-w-0 ${vuiControlQuietClass} ${vuiStateCoolInfoClass}`,
  agentSessionTabEditing:
    `vui-routes-chatcodingroute agentSessionTabEditing min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabGroup:
    `vui-routes-chatcodingroute agentSessionTabGroup min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabIcon:
    `vui-routes-chatcodingroute agentSessionTabIcon min-w-0 shrink-0 text-[var(--fg-tertiary)] ${vuiStateCoolInfoClass}`,
  agentSessionTabKicker:
    `vui-routes-chatcodingroute agentSessionTabKicker min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabMainAction:
    `vui-routes-chatcodingroute agentSessionTabMainAction min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  agentSessionTabMeta:
    `vui-routes-chatcodingroute agentSessionTabMeta min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  agentSessionTabRoot:
    `vui-routes-chatcodingroute agentSessionTabRoot min-w-0 ${vuiStateCoolInfoClass}`,
  agentSessionTabTitle:
    `vui-routes-chatcodingroute agentSessionTabTitle min-w-0 [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] ${vuiStateCoolInfoClass}`,
  agentSessionTabTitleInput:
    `vui-routes-chatcodingroute agentSessionTabTitleInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] ${vuiStateCoolInfoClass}`,
  blockEyebrow:
    "vui-routes-chatcodingroute blockEyebrow min-w-0 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  sectionEyebrowRow:
    "vui-routes-chatcodingroute sectionEyebrowRow flex min-w-0 items-center gap-1",
  // Wave 6H dialog policy: viewport clamp only — not workbench pane-heights.,
  cacheDonutShell:
    "vui-routes-chatcodingroute cacheDonutShell min-w-0 grid h-full min-h-0 content-start overflow-hidden text-[var(--fg-primary)]",
  cacheDonutStats:
    "vui-routes-chatcodingroute cacheDonutStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  centerPane:
    `vui-routes-chatcodingroute centerPane min-w-0 grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${vuiChatFillClass} [grid-column:3] [grid-row:1]`,
  centerPaneOverlay:
    "vui-routes-chatcodingroute centerPaneOverlay [grid-column:1] [grid-row:1]",
  centerSurface:
    `vui-routes-chatcodingroute centerSurface grid h-full min-h-0 overflow-hidden ${vuiChatFillClass}`,
  chatReturnLink:
    "vui-routes-chatcodingroute chatReturnLink min-w-0 [&_span]:truncate",
  childTopLevelSessionItem:
    `vui-routes-chatcodingroute childTopLevelSessionItem min-w-0 ${vuiOpaqueRowClass} p-2`,
  cliAgentRunPanel: `vui-routes-chatcodingroute cliAgentRunPanel min-w-0 ${vuiGlassPanelClass} p-2 ${vuiStateCoolInfoClass}`,
  cliAgentRunPanelHidden: `vui-routes-chatcodingroute cliAgentRunPanelHidden min-w-0 ${vuiGlassPanelClass} p-2 hidden ${vuiStateCoolInfoClass} hidden`,
  cliAgentTerminalAction:
    `vui-routes-chatcodingroute cliAgentTerminalAction min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalCommand:
    `vui-routes-chatcodingroute cliAgentTerminalCommand min-w-0 ${vuiStateCoolInfoClass} !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2`,
  cliAgentTerminalFrame:
    `vui-routes-chatcodingroute cliAgentTerminalFrame min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalOutput:
    `vui-routes-chatcodingroute cliAgentTerminalOutput min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalOutputShell: `vui-routes-chatcodingroute cliAgentTerminalOutputShell min-w-0 grid h-full min-h-0 content-start overflow-hidden ${vuiWorkspaceFillClass} text-[var(--fg-primary)] ${vuiStateCoolInfoClass} bg-[var(--bg-canvas)]`,
  cliAgentTerminalOverlay:
    `vui-routes-chatcodingroute cliAgentTerminalOverlay min-w-0 ${vuiStateCoolInfoClass}`,
  cliAgentTerminalStatus:
    `vui-routes-chatcodingroute cliAgentTerminalStatus min-w-0 ${vuiStateCoolInfoClass}`,
  // Wave 6H: outer <details> is chrome only; open body height uses PersistedHeightListShell.,
  contextCompositionSegmentAgent:
    `vui-routes-chatcodingroute contextCompositionSegmentAgent min-w-0 ${vuiStateCoolInfoClass}`,
  contextCompositionSegmentAttachments:
    `vui-routes-chatcodingroute contextCompositionSegmentAttachments min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentCacheWrite:
    `vui-routes-chatcodingroute contextCompositionSegmentCacheWrite min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentCached:
    `vui-routes-chatcodingroute contextCompositionSegmentCached min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentExact:
    `vui-routes-chatcodingroute contextCompositionSegmentExact min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentGuidance:
    `vui-routes-chatcodingroute contextCompositionSegmentGuidance min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentHistory:
    `vui-routes-chatcodingroute contextCompositionSegmentHistory min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentMissing:
    `vui-routes-chatcodingroute contextCompositionSegmentMissing min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentOther:
    `vui-routes-chatcodingroute contextCompositionSegmentOther min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentSkill:
    `vui-routes-chatcodingroute contextCompositionSegmentSkill min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentTask:
    `vui-routes-chatcodingroute contextCompositionSegmentTask min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUncached:
    `vui-routes-chatcodingroute contextCompositionSegmentUncached min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUnused:
    `vui-routes-chatcodingroute contextCompositionSegmentUnused min-w-0 ${vuiStateWarmSoftClass}`,
  contextCompositionSegmentUser:
    `vui-routes-chatcodingroute contextCompositionSegmentUser min-w-0 ${vuiStateWarmSoftClass}`,
  contextLineCompact: `vui-routes-chatcodingroute contextLineCompact min-w-0 ${vuiOpaqueRowClass} px-1.5 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] leading-snug shadow-none [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] overflow-hidden [overflow-wrap:anywhere]`,
  conversationAvatar:
    "vui-routes-chatcodingroute conversationAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarDirect:
    "vui-routes-chatcodingroute conversationAvatarDirect min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarGroup:
    "vui-routes-chatcodingroute conversationAvatarGroup min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationCopy:
    "vui-routes-chatcodingroute conversationCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  conversationGroup:
    "vui-routes-chatcodingroute conversationGroup grid min-w-0 gap-0.5",
  conversationGroupHeader:
    "vui-routes-chatcodingroute conversationGroupHeader !grid !w-full min-h-[28px] grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-1 rounded-[var(--radius-control)] border-0 bg-transparent px-1.5 py-0 text-left [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-secondary)] shadow-none transition-colors hover:border-transparent hover:!bg-[var(--vui-surface-card)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_36%,transparent)] [&_svg]:transition-transform [&[aria-expanded=true]_svg]:rotate-90 [&_span]:min-w-0 [&_span]:truncate [&_strong]:inline-grid [&_strong]:min-w-5 [&_strong]:place-items-center [&_strong]:rounded-full [&_strong]:bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] [&_strong]:px-1.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:font-semibold [&_strong]:text-[var(--fg-secondary)]",
  conversationGroupList:
    "vui-routes-chatcodingroute conversationGroupList grid min-w-0 gap-1",
  conversationKindBadge:
    `vui-routes-chatcodingroute conversationKindBadge min-w-0 ${vuiControlPillClass}`,
  conversationKindBadgeChild:
    "vui-routes-chatcodingroute conversationKindBadgeChild min-w-0",
  conversationKindBadgeDirect:
    "vui-routes-chatcodingroute conversationKindBadgeDirect min-w-0",
  conversationKindBadgeGroup:
    "vui-routes-chatcodingroute conversationKindBadgeGroup min-w-0",
  conversationMetaMain:
    "vui-routes-chatcodingroute conversationMetaMain inline-flex min-w-0 items-center gap-1 overflow-hidden [font-size:var(--vui-font-xs)] font-medium leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  conversationMetaRow:
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationMetaTime:
    "vui-routes-chatcodingroute conversationMetaTime inline-flex max-w-[112px] shrink-0 items-center justify-end gap-0.5 overflow-visible whitespace-nowrap [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationTitleMain:
    "vui-routes-chatcodingroute conversationTitleMain inline-flex min-w-0 max-w-full items-center gap-1.5 overflow-hidden",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  directSessionItem:
    "vui-routes-chatcodingroute directSessionItem pr-0 shadow-none",
  // Run-mode toggle: label left + state pill right. No leading status dots (they duplicated 开/关).,
  groupBubble:
    "vui-routes-chatcodingroute groupBubble min-w-0",
  groupBubbleAvatar:
    "vui-routes-chatcodingroute groupBubbleAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  groupBubbleBody:
    "vui-routes-chatcodingroute groupBubbleBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupBubbleBodyCollapsed:
    "vui-routes-chatcodingroute groupBubbleBodyCollapsed min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] hidden",
  groupBubbleHeader:
    "vui-routes-chatcodingroute groupBubbleHeader min-w-0 flex flex-wrap items-center gap-1.5",
  groupBubbleMeta:
    "vui-routes-chatcodingroute groupBubbleMeta min-w-0 flex flex-wrap items-center gap-1.5",
  groupBubbleRow:
    `vui-routes-chatcodingroute groupBubbleRow min-w-0 ${vuiOpaqueRowClass} p-2 !grid grid-cols-[30px_minmax(0,1fr)] items-start gap-[7px]`,
  groupBubbleRowFailed: `vui-routes-chatcodingroute groupBubbleRowFailed min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateDangerSoftClass}`,
  groupBubbleRowPending:
    `vui-routes-chatcodingroute groupBubbleRowPending min-w-0 ${vuiOpaqueRowClass} p-2`,
  groupBubbleToggle:
    "vui-routes-chatcodingroute groupBubbleToggle min-w-0",
  groupComposerBar:
    "vui-routes-chatcodingroute groupComposerBar min-w-0 !grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-t border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] p-2",
  groupConversationFrame: `vui-routes-chatcodingroute groupConversationFrame grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden ${vuiFlatPanelClass} shadow-[var(--vui-shadow-hairline)]`,
  groupConversationHeader:
    "vui-routes-chatcodingroute groupConversationHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-b border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] px-2 py-2 [&_div]:grid [&_div]:min-w-0 [&_div]:gap-0.5 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:truncate [&_h2]:[font-size:var(--vui-font-title)] [&_h2]:font-semibold [&_h2]:leading-tight [&_h2]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:truncate [&_p]:text-[10px] [&_p]:font-medium [&_p]:leading-tight [&_p]:text-[var(--fg-tertiary)] [&_span]:min-w-0 [&_span]:truncate [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-secondary)]",
  groupEmptyState:
    "vui-routes-chatcodingroute groupEmptyState grid min-h-[min(220px,calc(100dvh_-_260px))] min-w-0 place-items-center px-6 text-center [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_svg]:mb-2 [&_svg]:text-[var(--accent-cool)]",
  groupConversationTitleRow:
    "vui-routes-chatcodingroute groupConversationTitleRow flex min-w-0 items-center gap-1",
  groupMessageList:
    "vui-routes-chatcodingroute groupMessageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupMessageTimeline:
    "vui-routes-chatcodingroute groupMessageTimeline min-w-0 grid min-h-0 content-start gap-2 overflow-auto p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [scrollbar-gutter:stable]",
  groupRefreshButton:
    `vui-routes-chatcodingroute groupRefreshButton min-w-0 ${vuiControlQuietClass}`,
  groupRoundBlock:
    "vui-routes-chatcodingroute groupRoundBlock min-w-0",
  groupRoundDivider:
    "vui-routes-chatcodingroute groupRoundDivider min-w-0",
  groupRoundSummary: `vui-routes-chatcodingroute groupRoundSummary min-w-0 ${vuiGlassPanelClass} p-2`,
  groupSessionItem:
    "vui-routes-chatcodingroute groupSessionItem pr-0 border-transparent bg-transparent shadow-none",
  groupStopButton:
    `vui-routes-chatcodingroute groupStopButton min-w-0 ${vuiControlQuietClass}`,
  groupTopicBubble:
    "vui-routes-chatcodingroute groupTopicBubble min-w-0",
  groupTopicMessage:
    "vui-routes-chatcodingroute groupTopicMessage min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupTypingDots:
    "vui-routes-chatcodingroute groupTypingDots min-w-0",
  inlineNotice: `vui-routes-chatcodingroute inlineNotice min-w-0 ${vuiGlassPanelClass} p-2`,
  kernelTraceLink:
    "vui-routes-chatcodingroute kernelTraceLink min-w-0",
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
  projectBusEvent:
    "vui-routes-chatcodingroute projectBusEvent min-w-0",
  projectBusEventActions:
    "vui-routes-chatcodingroute projectBusEventActions min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventBody:
    "vui-routes-chatcodingroute projectBusEventBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  projectBusEventHeader:
    "vui-routes-chatcodingroute projectBusEventHeader min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventMeta:
    "vui-routes-chatcodingroute projectBusEventMeta min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventRevoked:
    "vui-routes-chatcodingroute projectBusEventRevoked min-w-0",
  projectBusInterruptToggle:
    "vui-routes-chatcodingroute projectBusInterruptToggle min-w-0",
  // Wave 4B: visual resize rule lives on PaneCollapseHandle; route only places the seam.,
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
  sessionActionStack:
    "vui-routes-chatcodingroute sessionActionStack min-w-0 flex flex-wrap items-center gap-1.5",
  sessionContextMenu: `vui-routes-chatcodingroute sessionContextMenu fixed z-[80] grid w-[188px] max-w-[calc(100vw-24px)] content-start gap-1 ${vuiGlassPanelClass} p-1 text-[var(--fg-primary)] shadow-[var(--vui-shadow-hairline)] backdrop-blur`,
  sessionContextMenuDanger:
    `vui-routes-chatcodingroute sessionContextMenuDanger min-w-0 ${vuiStateDangerSoftClass}`,
  sessionContextMenuItem: `vui-routes-chatcodingroute sessionContextMenuItem min-w-0 !w-full justify-start ${vuiOpaqueRowClass} px-2 py-1.5 text-left text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_[data-slot=vui-button-label]]:col-span-full`,
  sessionIconButton:
    "vui-routes-chatcodingroute sessionIconButton min-w-0 inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] shrink-0 text-[var(--fg-tertiary)]",
  sessionItem:
    "vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 overflow-hidden rounded-[var(--radius-control)] border border-transparent bg-transparent !px-1 !py-0 text-left transition-colors before:absolute before:inset-y-1.5 before:left-0 before:w-[2px] before:rounded-full before:bg-[var(--accent-cool)] before:opacity-0 before:transition-opacity hover:!bg-[var(--vui-surface-card)] focus-within:!bg-[var(--vui-surface-card)]",
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-card))] shadow-[var(--vui-shadow-inset-accent)] before:opacity-100",
  sessionItemContextTarget:
    "vui-routes-chatcodingroute sessionItemContextTarget border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] !bg-[var(--vui-surface-card)] shadow-[var(--vui-shadow-inset-accent)] before:opacity-70",
  sessionItemError: `vui-routes-chatcodingroute sessionItemError min-w-0 ${vuiOpaqueRowClass} p-2 ${vuiStateDangerSoftClass}`,
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-h-[50px] min-w-0 appearance-none grid-cols-[27px_minmax(0,1fr)] items-center justify-stretch gap-1.5 rounded-none border-0 [border:0] bg-transparent !px-1.5 !py-1 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
  sessionItemNotice: `vui-routes-chatcodingroute sessionItemNotice min-w-0 ${vuiGlassPanelClass} p-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row)]`,
  sessionItemSummary:
    "vui-routes-chatcodingroute sessionItemSummary block min-w-0 truncate [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionLoadMoreButton:
    `vui-routes-chatcodingroute sessionLoadMoreButton min-w-0 ${vuiControlQuietClass}`,
  sessionLoadMoreStatus:
    "vui-routes-chatcodingroute sessionLoadMoreStatus min-w-0",
  sessionRunningBadge:
    "vui-routes-chatcodingroute sessionRunningBadge !inline-flex !h-[22px] !min-h-[22px] !w-fit max-w-full shrink-0 items-center justify-center gap-1 overflow-hidden border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--state-success)] [&_span]:leading-none [&_svg]:size-[10px] [&_svg]:shrink-0 [&_svg]:animate-spin",
  sessionState:
    "vui-routes-chatcodingroute sessionState !inline-flex !h-[22px] !min-h-[22px] !w-fit shrink-0 items-center justify-center overflow-hidden border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-1.5 text-[var(--state-success)] [&_svg]:size-[10px] [&_svg]:shrink-0",
  sessionStatusCluster:
    "vui-routes-chatcodingroute sessionStatusCluster inline-flex min-w-0 items-center justify-end gap-1",
  sessionTitleInput:
    "vui-routes-chatcodingroute sessionTitleInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionUnreadBadge:
    "vui-routes-chatcodingroute sessionUnreadBadge !inline-flex !h-[22px] !min-h-[22px] !w-fit max-w-full shrink-0 items-center justify-center gap-1 overflow-hidden border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] px-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--state-warning)] [&_span]:leading-none",
  tab:
    `vui-routes-chatcodingroute tab min-w-0 ${vuiControlQuietClass}`,
  tabActive:
    `vui-routes-chatcodingroute tabActive min-w-0 ${vuiStateSelectedRowClass}`,
  tabStrip:
    "vui-routes-chatcodingroute tabStrip min-w-0 flex h-9 items-end gap-1 overflow-hidden border-b border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] px-1 pt-1",
  teamTreeChild:
    "vui-routes-chatcodingroute teamTreeChild min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamTreeChildren:
    "vui-routes-chatcodingroute teamTreeChildren min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamTreeGroup:
    "vui-routes-chatcodingroute teamTreeGroup min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamTreeItem:
    "vui-routes-chatcodingroute teamTreeItem min-w-0 overflow-hidden border-transparent bg-transparent shadow-none",
  teamTreeLabelRow: `vui-routes-chatcodingroute teamTreeLabelRow min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiOpaqueRowClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
};

export default styles;
