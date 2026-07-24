import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  conversationAvatar:
    "vui-routes-chatcodingroute conversationAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarGroup:
    "vui-routes-chatcodingroute conversationAvatarGroup min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationCopy:
    "vui-routes-chatcodingroute conversationCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  conversationKindBadge:
    `vui-routes-chatcodingroute conversationKindBadge min-w-0 ${vuiControlPillClass}`,
  conversationKindBadgeGroup:
    "vui-routes-chatcodingroute conversationKindBadgeGroup min-w-0",
  conversationMetaRow:
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  groupSessionItem:
    "vui-routes-chatcodingroute groupSessionItem pr-0",
  sessionItem: `vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 overflow-hidden ${vuiOpaqueRowClass} text-left shadow-none transition-[border-color,background-color,box-shadow] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] focus-within:bg-[color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))]`,
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-h-[60px] min-w-0 appearance-none grid-cols-[32px_minmax(0,1fr)] items-center justify-stretch gap-2.5 rounded-none border-0 [border:0] bg-transparent !px-2.5 !py-2 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionItemTooltip:
    "grid gap-1 [&_strong]:text-[var(--fg-primary)] [&_span]:text-[var(--fg-secondary)]",
  sessionState:
    "vui-routes-chatcodingroute sessionState !inline-flex !h-[22px] !min-h-[22px] !w-fit shrink-0 items-center justify-center overflow-hidden border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-1.5 text-[var(--state-success)] [&_svg]:size-[10px] [&_svg]:shrink-0",
  teamTreeItem:
    "vui-routes-chatcodingroute teamTreeItem min-w-0 overflow-hidden",
} as const;

export default styles;
