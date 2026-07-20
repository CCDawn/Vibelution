const styles = {
  groupBubble: "vui-routes-chatcodingroute groupBubble min-w-0",
  groupBubbleAvatar:
    "vui-routes-chatcodingroute groupBubbleAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  groupBubbleHeader: "vui-routes-chatcodingroute groupBubbleHeader min-w-0 flex flex-wrap items-center gap-1.5",
  groupBubbleMeta: "vui-routes-chatcodingroute groupBubbleMeta min-w-0 flex flex-wrap items-center gap-1.5",
  groupBubbleRow:
    "vui-routes-chatcodingroute groupBubbleRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 !grid grid-cols-[30px_minmax(0,1fr)] items-start gap-[7px]",
  groupBubbleRowFailed:
    "vui-routes-chatcodingroute groupBubbleRowFailed min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  groupBubbleRowPending:
    "vui-routes-chatcodingroute groupBubbleRowPending min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  groupComposerBar:
    "vui-routes-chatcodingroute groupComposerBar min-w-0 !grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-t border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)] p-2",
  groupConversationFrame:
    "vui-routes-chatcodingroute groupConversationFrame grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_78%,transparent)] shadow-[var(--vui-shadow-hairline)]",
  groupConversationHeader:
    "vui-routes-chatcodingroute groupConversationHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-b border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_74%,transparent)] px-2 py-2 [&_div]:grid [&_div]:min-w-0 [&_div]:gap-0.5 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:truncate [&_h2]:[font-size:var(--vui-font-title)] [&_h2]:font-semibold [&_h2]:leading-tight [&_h2]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:truncate [&_p]:text-[10px] [&_p]:font-medium [&_p]:leading-tight [&_p]:text-[var(--fg-tertiary)] [&_span]:min-w-0 [&_span]:truncate [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:text-[var(--fg-secondary)]",
  groupConversationTitleRow: "vui-routes-chatcodingroute groupConversationTitleRow flex min-w-0 items-center gap-1",
  groupEmptyState:
    "vui-routes-chatcodingroute groupEmptyState grid min-h-[min(220px,calc(100dvh_-_260px))] min-w-0 place-items-center px-6 text-center [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_svg]:mb-2 [&_svg]:text-[var(--accent-cool)]",
  groupMessageList:
    "vui-routes-chatcodingroute groupMessageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupMessageTimeline:
    "vui-routes-chatcodingroute groupMessageTimeline min-w-0 grid min-h-0 content-start gap-2 overflow-auto p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [scrollbar-gutter:stable]",
  groupRefreshButton:
    "vui-routes-chatcodingroute groupRefreshButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  groupRoundBlock: "vui-routes-chatcodingroute groupRoundBlock min-w-0",
  groupRoundDivider: "vui-routes-chatcodingroute groupRoundDivider min-w-0",
  groupRoundSummary:
    "vui-routes-chatcodingroute groupRoundSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  groupStopButton:
    "vui-routes-chatcodingroute groupStopButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  groupTopicBubble: "vui-routes-chatcodingroute groupTopicBubble min-w-0",
  groupTopicMessage:
    "vui-routes-chatcodingroute groupTopicMessage min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupTypingDots: "vui-routes-chatcodingroute groupTypingDots min-w-0",
  inlineNotice:
    "vui-routes-chatcodingroute inlineNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  kernelTraceLink: "vui-routes-chatcodingroute kernelTraceLink min-w-0",
  projectBusEvent: "vui-routes-chatcodingroute projectBusEvent min-w-0",
  projectBusEventActions: "vui-routes-chatcodingroute projectBusEventActions min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventBody:
    "vui-routes-chatcodingroute projectBusEventBody min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  projectBusEventHeader: "vui-routes-chatcodingroute projectBusEventHeader min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventMeta: "vui-routes-chatcodingroute projectBusEventMeta min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventRevoked: "vui-routes-chatcodingroute projectBusEventRevoked min-w-0",
  projectBusInterruptToggle: "vui-routes-chatcodingroute projectBusInterruptToggle min-w-0",
} as const;

export default styles;
