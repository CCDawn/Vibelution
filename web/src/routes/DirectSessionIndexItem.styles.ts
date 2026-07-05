const styles = {
  agentAvatarImage:
    "vui-routes-chatcodingroute agentAvatarImage min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentMissingLine:
    "vui-routes-chatcodingroute agentMissingLine min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentModelTag:
    "vui-routes-chatcodingroute agentModelTag inline-flex min-h-[18px] min-w-0 max-w-[96px] shrink items-center gap-0.5 overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,transparent)] px-1.5 py-0 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--accent-cool)] [&_span]:min-w-0 [&_span]:truncate [&_svg]:shrink-0",
  agentModelTitleTag:
    "vui-routes-chatcodingroute agentModelTitleTag max-w-[96px]",
  agentRoleTag:
    "vui-routes-chatcodingroute agentRoleTag min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
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
    "vui-routes-chatcodingroute conversationMetaRow grid min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-x-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationMetaTime:
    "vui-routes-chatcodingroute conversationMetaTime inline-flex max-w-[112px] shrink-0 items-center justify-end gap-0.5 overflow-visible whitespace-nowrap text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_time]:flex-none [&_time]:overflow-visible [&_time]:text-clip",
  conversationTitleMain:
    "vui-routes-chatcodingroute conversationTitleMain inline-flex min-w-0 max-w-full items-center gap-1.5 overflow-hidden",
  conversationTitleRow:
    "vui-routes-chatcodingroute conversationTitleRow grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-1",
  directSessionItem:
    "vui-routes-chatcodingroute directSessionItem pr-1 shadow-none",
  sessionActionStack:
    "vui-routes-chatcodingroute sessionActionStack min-w-0 flex flex-wrap items-center gap-1.5",
  sessionCurrentBadge:
    "vui-routes-chatcodingroute sessionCurrentBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)]",
  sessionIconButton:
    "vui-routes-chatcodingroute sessionIconButton min-w-0 inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] shrink-0 text-[var(--fg-tertiary)]",
  sessionItem:
    "vui-routes-chatcodingroute sessionItem relative grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0 rounded-[var(--radius-control)] border border-transparent bg-transparent !px-1 !py-0.5 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_58%,transparent)] hover:shadow-[var(--vui-shadow-inset-accent)] focus-within:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_58%,transparent)] focus-within:shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemActive:
    "vui-routes-chatcodingroute sessionItemActive border-[color-mix(in_srgb,var(--accent-cool)_20%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_68%,transparent)] shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemContextTarget:
    "vui-routes-chatcodingroute sessionItemContextTarget border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_58%,transparent)] shadow-[var(--vui-shadow-inset-accent)]",
  sessionItemError:
    "vui-routes-chatcodingroute sessionItemError min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  sessionItemMain:
    "vui-routes-chatcodingroute sessionItemMain !grid !w-full min-w-0 grid-cols-[27px_minmax(0,1fr)] items-center justify-stretch gap-1.5 rounded-none border-0 bg-transparent !p-0 text-left text-[var(--fg-primary)] shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none",
  sessionItemNotice:
    "vui-routes-chatcodingroute sessionItemNotice min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_62%,transparent)] p-2 shadow-none",
  sessionItemSummary:
    "vui-routes-chatcodingroute sessionItemSummary block min-w-0 truncate text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  sessionItemTitle:
    "vui-routes-chatcodingroute sessionItemTitle min-w-0 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionRunningBadge:
    "vui-routes-chatcodingroute sessionRunningBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  sessionStatusCluster:
    "vui-routes-chatcodingroute sessionStatusCluster inline-flex min-w-0 items-center justify-end gap-1",
  sessionTitleInput:
    "vui-routes-chatcodingroute sessionTitleInput min-w-0 grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  sessionUnreadBadge:
    "vui-routes-chatcodingroute sessionUnreadBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
