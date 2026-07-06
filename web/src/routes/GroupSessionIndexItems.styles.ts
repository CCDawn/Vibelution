const styles = {
  conversationAvatar:
    "vui-routes-chatcodingroute conversationAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarGroup:
    "vui-routes-chatcodingroute conversationAvatarGroup min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationCopy:
    "vui-routes-chatcodingroute conversationCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  conversationKindBadge:
    "vui-routes-chatcodingroute conversationKindBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  conversationKindBadgeGroup:
    "vui-routes-chatcodingroute conversationKindBadgeGroup min-w-0",
  conversationMetaRow:
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  groupSessionItem:
    "vui-routes-chatcodingroute groupSessionItem pr-0 border-transparent bg-transparent shadow-none",
  sessionItem:
    "vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 overflow-hidden rounded-[var(--radius-control)] border border-transparent bg-transparent !px-1 !py-0 text-left transition-colors before:absolute before:inset-y-1.5 before:left-0 before:w-[2px] before:rounded-full before:bg-[var(--accent-cool)] before:opacity-0 before:transition-opacity hover:bg-[color-mix(in_srgb,var(--surface-card)_46%,transparent)] focus-within:bg-[color-mix(in_srgb,var(--surface-card)_48%,transparent)]",
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--surface-card))] shadow-[var(--vui-shadow-inset-accent)] before:opacity-100",
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-h-[50px] min-w-0 appearance-none grid-cols-[27px_minmax(0,1fr)] items-center justify-stretch gap-1.5 rounded-none border-0 [border:0] bg-transparent !px-1.5 !py-1 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionState:
    "vui-routes-chatcodingroute sessionState !inline-flex !h-[22px] !min-h-[22px] !w-fit shrink-0 items-center justify-center overflow-hidden border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-1.5 text-[var(--state-success)] [&_svg]:size-[10px] [&_svg]:shrink-0",
  teamTreeItem:
    "vui-routes-chatcodingroute teamTreeItem min-w-0 grid min-h-0 content-start gap-1.5 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
} as const;

export default styles;
