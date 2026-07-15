const styles = {
  agentAvatarImage:
    "vui-routes-chatcodingroute agentAvatarImage min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentMissingLine:
    "vui-routes-chatcodingroute agentMissingLine min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentModelTag:
    "vui-routes-chatcodingroute agentModelTag inline-flex min-h-[18px] min-w-0 max-w-[96px] shrink items-center gap-0.5 overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,transparent)] px-1.5 py-0 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--accent-cool)] [&_span]:min-w-0 [&_span]:truncate [&_svg]:shrink-0",
  agentModelTitleTag:
    "vui-routes-chatcodingroute agentModelTitleTag max-w-[96px]",
  agentRoleTag:
    "vui-routes-chatcodingroute agentRoleTag min-w-0 inline-flex min-h-[18px] w-fit max-w-full items-center justify-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_6%,transparent)] px-1.5 text-[var(--vui-font-xs)] font-medium leading-none text-[var(--accent-cool)]",
  agentRoleTag_chat:
    "vui-routes-chatcodingroute agentRoleTag_chat min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_general:
    "vui-routes-chatcodingroute agentRoleTag_general min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_memory:
    "vui-routes-chatcodingroute agentRoleTag_memory min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_research:
    "vui-routes-chatcodingroute agentRoleTag_research min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_self:
    "vui-routes-chatcodingroute agentRoleTag_self min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_supervised:
    "vui-routes-chatcodingroute agentRoleTag_supervised min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentRoleTag_tool:
    "vui-routes-chatcodingroute agentRoleTag_tool min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  childTopLevelSessionItem:
    "vui-routes-chatcodingroute childTopLevelSessionItem min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  conversationAvatar:
    "vui-routes-chatcodingroute conversationAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationAvatarDirect:
    "vui-routes-chatcodingroute conversationAvatarDirect min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  conversationCopy:
    "vui-routes-chatcodingroute conversationCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  conversationKindBadge:
    "vui-routes-chatcodingroute conversationKindBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  conversationKindBadgeChild:
    "vui-routes-chatcodingroute conversationKindBadgeChild min-w-0",
  conversationKindBadgeDirect:
    "vui-routes-chatcodingroute conversationKindBadgeDirect min-w-0",
  conversationMetaMain:
    "vui-routes-chatcodingroute conversationMetaMain inline-flex min-w-0 items-center gap-1 overflow-hidden text-[var(--vui-font-xs)] font-medium leading-tight text-[var(--fg-tertiary)] [&>span]:min-w-0 [&>span]:truncate",
  conversationMetaRow:
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-start gap-x-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationMetaTime:
    "vui-routes-chatcodingroute conversationMetaTime inline-flex max-w-[112px] shrink-0 self-start items-center justify-end overflow-visible whitespace-nowrap pt-[1px] text-[var(--vui-font-xs)] leading-tight tabular-nums text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationTitleMain:
    "vui-routes-chatcodingroute conversationTitleMain inline-flex min-w-0 max-w-full items-center gap-1.5 overflow-hidden",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  directSessionItem:
    "vui-routes-chatcodingroute directSessionItem pr-0 shadow-none",
  sessionActionStack:
    "vui-routes-chatcodingroute sessionActionStack min-w-0 flex flex-wrap items-center gap-1.5",
  sessionIconButton:
    "vui-routes-chatcodingroute sessionIconButton min-w-0 inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] shrink-0 text-[var(--fg-tertiary)]",
  sessionItem:
    "vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_86%,transparent)] text-left shadow-none transition-[border-color,background-color,box-shadow] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] focus-within:bg-[color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-row))]",
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_46%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))] shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemContextTarget:
    "vui-routes-chatcodingroute sessionItemContextTarget border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--surface-card)_56%,transparent)] shadow-[var(--vui-shadow-inset-accent)] before:opacity-70",
  sessionItemError:
    "vui-routes-chatcodingroute sessionItemError mx-2.5 mb-2 min-w-0 border-l-2 border-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_6%,transparent)] px-2 py-1 text-[var(--vui-font-xs)] leading-tight text-[var(--state-error)] [overflow-wrap:anywhere]",
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-h-[60px] min-w-0 appearance-none grid-cols-[32px_minmax(0,1fr)] items-center justify-stretch gap-2.5 rounded-none border-0 [border:0] bg-transparent !px-2.5 !py-2 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]",
  sessionItemNotice:
    "vui-routes-chatcodingroute sessionItemNotice mx-2.5 mb-2 min-w-0 border-l-2 border-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_5%,transparent)] px-2 py-1 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  sessionItemSummary:
    "vui-routes-chatcodingroute sessionItemSummary block min-w-0 truncate text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionRunningBadge:
    "vui-routes-chatcodingroute sessionRunningBadge !inline-flex !h-[22px] !min-h-[22px] !w-fit max-w-full shrink-0 items-center justify-center gap-1 overflow-hidden border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-1.5 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--state-success)] [&_span]:leading-none [&_svg]:size-[10px] [&_svg]:shrink-0 [&_svg]:animate-spin",
  sessionStatusCluster:
    "vui-routes-chatcodingroute sessionStatusCluster inline-flex min-w-0 items-center justify-end gap-1",
  sessionTitleInput:
    "vui-routes-chatcodingroute sessionTitleInput min-w-0 grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionUnreadBadge:
    "vui-routes-chatcodingroute sessionUnreadBadge !inline-flex !h-[22px] !min-h-[22px] !w-fit max-w-full shrink-0 items-center justify-center gap-1 overflow-hidden border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] px-1.5 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--state-warning)] [&_span]:leading-none",
} as const;

export default styles;
