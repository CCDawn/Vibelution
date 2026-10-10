import {
  vuiControlQuietClass,
} from "../../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiGlassPanelClass,
  vuiStateDangerSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  groupBubble: "vui-routes-chatcodingroute groupBubble min-w-0",
  groupBubbleAvatar:
    "vui-routes-chatcodingroute groupBubbleAvatar inline-grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] text-vui-micro-13 font-semibold text-[var(--fg-secondary)]",
  groupBubbleHeader: "vui-routes-chatcodingroute groupBubbleHeader flex min-w-0 flex-wrap items-baseline gap-1.5",
  groupBubbleMeta: "vui-routes-chatcodingroute groupBubbleMeta text-vui-micro-11 leading-tight text-[var(--fg-tertiary)]",
  groupBubbleRow:
    "vui-routes-chatcodingroute groupBubbleRow grid min-w-0 gap-1 border-0 bg-transparent p-0 shadow-none",
  groupBubbleRowFailed: `vui-routes-chatcodingroute groupBubbleRowFailed min-w-0 ${vuiStateDangerSoftClass} rounded-[var(--radius-control)] p-1`,
  groupBubbleRowPending: "vui-routes-chatcodingroute groupBubbleRowPending min-w-0",
  groupStreamIdentity:
    "vui-routes-chatcodingroute groupStreamIdentity flex min-w-0 flex-nowrap items-center gap-2.5",
  groupStreamCopy: "vui-routes-chatcodingroute groupStreamCopy grid min-w-0 gap-1 pl-12",
  groupStreamCluster:
    "vui-routes-chatcodingroute groupStreamCluster grid min-w-0 content-start gap-2 pt-5 first:pt-0",
  groupStreamName:
    "vui-routes-chatcodingroute groupStreamName [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
  groupComposerBar:
    "vui-routes-chatcodingroute groupComposerBar min-w-0 !grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-t border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] p-2",
  groupConversationFrame: `vui-routes-chatcodingroute groupConversationFrame grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden ${vuiFlatPanelClass} !rounded-none !border-0`,
  groupConversationHeader:
    "vui-routes-chatcodingroute groupConversationHeader flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-7 py-5 max-[600px]:px-4 max-[600px]:py-3 [&>div:first-child]:min-w-0 [&_h2]:m-0 [&_h2]:break-words [&_h2]:[font-size:var(--vui-font-title)] [&_h2]:font-semibold [&_h2]:leading-tight [&_h2]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:mb-1 [&_p]:text-vui-2xs [&_p]:text-[var(--fg-tertiary)]",
  groupHeaderActions: "flex shrink-0 items-center gap-2 [&_button]:min-h-11 max-[600px]:gap-1",
  groupConversationTitleRow: "vui-routes-chatcodingroute groupConversationTitleRow flex min-w-0 items-center gap-1",
  groupEmptyState:
    "vui-routes-chatcodingroute groupEmptyState grid min-h-[min(220px,calc(100dvh_-_260px))] min-w-0 place-items-center px-6 text-center [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [&_svg]:mb-2 [&_svg]:text-[var(--accent-cool)]",
  groupMessageList:
    "vui-routes-chatcodingroute groupMessageList min-w-0 grid content-start gap-3 [font-size:var(--vui-font-chat)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupMessageTimeline:
    "vui-routes-chatcodingroute groupMessageTimeline min-w-0 min-h-0 overflow-y-auto overflow-x-hidden overscroll-contain px-7 pb-6 pt-2 max-[600px]:px-4 [font-size:var(--vui-font-chat)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [scrollbar-gutter:stable]",
  groupRefreshButton:
    `vui-routes-chatcodingroute groupRefreshButton min-w-0 ${vuiControlQuietClass}`,
  groupRoundBlock: "vui-routes-chatcodingroute groupRoundBlock mx-auto w-full max-w-[860px] min-w-0",
  groupRoundActions: "flex flex-wrap items-center gap-2 py-2",
  groupRoundDivider:
    "vui-routes-chatcodingroute groupRoundDivider mx-auto mb-3 mt-5 flex w-full max-w-[860px] min-w-0 flex-wrap items-center gap-x-3 gap-y-1 py-2 text-vui-2xs text-[var(--fg-tertiary)] before:h-px before:flex-1 before:bg-[var(--vui-border-subtle)] after:h-px after:flex-1 after:bg-[var(--vui-border-subtle)] [&>span]:max-w-full [&>span]:break-words",
  groupRoundSummary: "vui-routes-chatcodingroute groupRoundSummary ml-12 mt-5 min-w-0 rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] p-4 [&_strong]:[font-size:var(--vui-font-sm)] [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:break-words [&_p]:[font-size:var(--vui-font-sm)]",
  groupRoundResult: "ml-12 mt-3 min-w-0",
  groupResultToggle: "!justify-start !px-0 !text-[var(--fg-tertiary)] max-[600px]:!min-h-11",
  groupResultCopy: "mt-2 break-words [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  groupStopButton:
    `vui-routes-chatcodingroute groupStopButton min-w-0 !min-h-11 ${vuiControlQuietClass}`,
  groupTopicComposer: "min-w-0 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-7 pb-4 pt-4 max-[600px]:px-3 max-[600px]:py-3 [&>div]:mx-auto [&>div]:max-w-[860px]",
  groupTopicComposerField: "rounded-xl border border-[var(--vui-border-subtle)] focus-within:ring-2 focus-within:ring-[var(--vui-border-strong)]",
  groupTopicInput: "!min-h-[72px] !w-full !resize-none !rounded-xl !border-0 !bg-transparent !px-4 !py-3 [font-size:var(--vui-font-md)] !shadow-none",
  groupTopicComposerActions: "flex min-w-0 items-center justify-between gap-2 px-2 pb-2 [&_button]:!min-h-11",
  groupComposerFootnote: "mt-2 flex justify-between gap-3 text-vui-2xs text-[var(--fg-tertiary)] max-[600px]:[&>span:last-child]:hidden",
  groupMembers: "grid divide-y divide-[var(--vui-border-subtle)]",
  groupMemberRow: "flex min-w-0 items-center gap-3 py-4",
  groupMemberMeta: "break-words [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  groupTopicBubble: "vui-routes-chatcodingroute groupTopicBubble min-w-0 grid gap-0.5",
  groupTopicMessage:
    "vui-routes-chatcodingroute groupTopicMessage mb-4 min-w-0 [font-size:var(--vui-font-chat)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupTypingDots: "vui-routes-chatcodingroute groupTypingDots min-w-0",
  groupTypingStaleNote:
    "vui-routes-chatcodingroute groupTypingStaleNote min-w-0 m-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  inlineNotice: `vui-routes-chatcodingroute inlineNotice min-w-0 ${vuiGlassPanelClass} p-2`,
  kernelTraceLink: "vui-routes-chatcodingroute kernelTraceLink min-w-0",
  projectBusEvent: "vui-routes-chatcodingroute projectBusEvent min-w-0",
  projectBusEventActions: "vui-routes-chatcodingroute projectBusEventActions min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventBody:
    "vui-routes-chatcodingroute projectBusEventBody min-w-0 [overflow-wrap:anywhere] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  projectBusEventHeader: "vui-routes-chatcodingroute projectBusEventHeader min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventMeta: "vui-routes-chatcodingroute projectBusEventMeta min-w-0 flex flex-wrap items-center gap-1.5",
  projectBusEventRevoked: "vui-routes-chatcodingroute projectBusEventRevoked min-w-0",
  projectBusInterruptToggle: "vui-routes-chatcodingroute projectBusInterruptToggle min-w-0",
} as const;

export default styles;
