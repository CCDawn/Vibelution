/**
 * Group / team rows in the chat left rail.
 * Shared keys (sessionItem*, conversation*) stay merge-compatible with
 * DirectSessionIndexItem in ChatCodingRoute layout contracts. Team-specific
 * chrome lives on teamTreeItem / groupSessionItem so directory rows can stay
 * flat like AgentConversationDirectory agent rows.
 */

import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  conversationAvatar:
    "vui-routes-chatcodingroute conversationAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarGroup:
    "vui-routes-chatcodingroute conversationAvatarGroup grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] text-[var(--accent-cool)] [&_svg]:size-[15px]",
  conversationCopy:
    "vui-routes-chatcodingroute conversationCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  conversationKindBadge:
    `vui-routes-chatcodingroute conversationKindBadge min-w-0 ${vuiControlPillClass}`,
  conversationKindBadgeGroup:
    "vui-routes-chatcodingroute conversationKindBadgeGroup min-w-0",
  conversationMetaRow:
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationMetaItem:
    "vui-routes-chatcodingroute conversationMetaItem min-w-0 truncate",
  conversationMetaMuted:
    "vui-routes-chatcodingroute conversationMetaMuted shrink-0 text-[var(--fg-tertiary)]",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  groupSessionItem:
    "vui-routes-chatcodingroute groupSessionItem min-w-0 overflow-hidden !border-0 !bg-transparent shadow-none transition-[background-color] hover:!bg-vui-surface-card",
  sessionItem: `vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 overflow-hidden ${vuiOpaqueRowClass} text-left shadow-none transition-[border-color,background-color,box-shadow] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] focus-within:bg-[color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))]`,
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-h-[60px] min-w-0 appearance-none grid-cols-[32px_minmax(0,1fr)] items-center justify-stretch gap-2.5 rounded-none border-0 [border:0] bg-transparent !px-2.5 !py-2 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionItemTooltip:
    "grid gap-1 [&_strong]:text-[var(--fg-primary)] [&_span]:text-[var(--fg-secondary)]",
  sessionState:
    "vui-routes-chatcodingroute sessionState inline-grid shrink-0 place-items-center",
  sessionStatusDot:
    "vui-routes-chatcodingroute sessionStatusDot inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--state-success)] shadow-[0_0_0_2px_color-mix(in_srgb,var(--state-success)_18%,transparent)]",
  sessionStatusDotMuted:
    "vui-routes-chatcodingroute sessionStatusDotMuted inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--fg-tertiary)] opacity-70",
  sessionStatusDotPending:
    "vui-routes-chatcodingroute sessionStatusDotPending inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--state-warning)] shadow-[0_0_0_2px_color-mix(in_srgb,var(--state-warning)_18%,transparent)]",
  // Flat rail row: matches AgentConversationDirectory agent rows under the same team section.
  teamTreeItem:
    `vui-routes-chatcodingroute teamTreeItem min-w-0 overflow-hidden !border-0 !bg-transparent shadow-none transition-[background-color] hover:!bg-vui-surface-card focus-within:!bg-[color-mix(in_srgb,var(--accent-cool)_6%,transparent)]`,
  teamTreeItemActive:
    `vui-routes-chatcodingroute teamTreeItemActive !border-0 ${vuiStateSelectedRowFillClass} !text-[var(--accent-cool)] shadow-none`,
  // Team/group meta is a simple flex line (not the direct-session meta grid).
  teamConversationMetaRow:
    "vui-routes-chatcodingroute teamConversationMetaRow flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 overflow-hidden [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  teamSessionItemTitle:
    "vui-routes-chatcodingroute teamSessionItemTitle min-w-0 flex-1 truncate [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  teamSessionItemMain:
    "vui-routes-chatcodingroute teamSessionItemMain !grid !h-auto !min-h-[3.25rem] !w-full min-w-0 appearance-none grid-cols-[32px_minmax(0,1fr)] items-center justify-stretch gap-2.5 rounded-[var(--radius-control)] border-0 [border:0] bg-transparent !px-2.5 !py-2 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
} as const;

export default styles;
