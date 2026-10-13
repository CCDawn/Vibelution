import { vuiChatFillClass } from "../../design/vuiSurfaceRecipes";

const quietButton = "!border-0 !bg-transparent !bg-none !shadow-none";

const styles = {
  shell: "vui-routes-chatrightrail shell flex h-full min-h-0 min-w-0 flex-col !overflow-hidden !pt-0 [&.overlayPane]:!h-auto [&.overlayPane]:!bottom-0",
  panel: `vui-routes-chatrightrail panel flex min-h-0 flex-1 flex-col overflow-hidden !rounded-[12px] ${vuiChatFillClass}`,
  toolbar: "vui-routes-chatrightrail toolbar flex h-[44px] shrink-0 items-center gap-0.5 bg-[var(--vui-surface-row)] px-1",
  title: "vui-routes-chatrightrail title pl-2 [font-size:var(--vui-font-xs)] font-medium text-[var(--fg-secondary)]",
  tabs: "vui-routes-chatrightrail tabs flex min-w-0 flex-1 items-center gap-1 overflow-auto",
  tab: "vui-routes-chatrightrail tab flex min-w-0 shrink-0 items-center",
  tabActive: "vui-routes-chatrightrail tabActive min-w-0 rounded-[6px] bg-[color-mix(in_srgb,var(--fg-primary)_6%,var(--shell-surface))]",
  tabLabel:
    `vui-routes-chatrightrail tabLabel !h-7 !min-h-7 !min-w-0 ${quietButton} !px-2 [font-size:var(--vui-font-xs)] font-normal text-[var(--fg-secondary)]`,
  tabClose:
    `vui-routes-chatrightrail tabClose !h-6 !w-6 !min-w-6 ${quietButton} !px-0 text-[var(--fg-tertiary)]`,
  tools: "vui-routes-chatrightrail tools flex shrink-0 items-center gap-1",
  iconButton:
    `vui-routes-chatrightrail iconButton !h-7 !min-h-7 !w-7 !min-w-7 ${quietButton} !px-0 !rounded-[6px] text-[var(--fg-secondary)] hover:!bg-[var(--vui-control-muted-hover)]`,
  search: "vui-routes-chatrightrail search flex shrink-0 flex-col gap-2 bg-[var(--vui-surface-row)] px-2 py-2",
  searchList: "vui-routes-chatrightrail searchList m-0 flex max-h-40 list-none flex-col gap-1 overflow-auto p-0",
  searchButton:
    "vui-routes-chatrightrail searchButton !h-auto !w-full !min-w-0 !justify-start !border-0 !bg-transparent !px-2 !shadow-none [font-size:var(--vui-font-xs)]",
  searchHeading: "vui-routes-chatrightrail searchHeading m-0 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  body: "vui-routes-chatrightrail body flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
  launcher: "vui-routes-chatrightrail launcher flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto px-2.5 py-[18px]",
  launcherHint: "vui-routes-chatrightrail launcherHint m-0 px-2.5 pb-1 [font-size:var(--vui-font-2xs)] font-normal text-[var(--fg-tertiary)]",
  launcherIcon: "vui-routes-chatrightrail launcherIcon h-4 w-4 shrink-0 text-[var(--fg-secondary)]",
  launcherList: "vui-routes-chatrightrail launcherList m-0 flex list-none flex-col gap-1 p-0",
  launcherButton:
    `vui-routes-chatrightrail launcherButton !h-9 !min-h-9 !w-full !min-w-0 !justify-start !gap-2.5 !px-2.5 !rounded-[7px] ${quietButton} font-normal [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] hover:!bg-[var(--vui-control-muted-hover)]`,
  review: "vui-routes-chatrightrail review flex min-h-0 flex-1 flex-col overflow-auto",
  thread: "vui-routes-chatrightrail thread flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3",
  transcript: "vui-routes-chatrightrail transcript flex min-h-0 flex-1 flex-col gap-2 overflow-auto",
  bubbleUser:
    "vui-routes-chatrightrail bubbleUser max-w-full self-end rounded-[var(--radius-control)] bg-[var(--vui-surface-sunken)] px-2 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-primary)]",
  bubbleAssistant:
    "vui-routes-chatrightrail bubbleAssistant max-w-full self-start rounded-[var(--radius-control)] px-2 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-primary)]",
  composer: "vui-routes-chatrightrail composer mt-auto flex shrink-0 flex-col gap-2",
  note: "vui-routes-chatrightrail note m-0 [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  error: "vui-routes-chatrightrail error m-0 [font-size:var(--vui-font-xs)] text-[var(--vui-status-danger-fg)]",
  browser: "vui-routes-chatrightrail browser flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3",
  frame: "vui-routes-chatrightrail frame min-h-0 w-full flex-1 border-0 bg-[var(--vui-surface-sunken)]",
  metrics: "vui-routes-chatrightrail metrics m-0 flex min-h-0 flex-1 flex-col overflow-auto px-4 py-[18px]",
  metric: "vui-routes-chatrightrail metric flex min-w-0 items-center justify-between gap-3 border-b border-[color-mix(in_srgb,var(--fg-primary)_4%,transparent)] py-3",
  metricLabel: "vui-routes-chatrightrail metricLabel [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  metricValue: "vui-routes-chatrightrail metricValue m-0 min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-primary)]",
  plain: "vui-routes-chatrightrail plain flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-3",
  fileBody: "vui-routes-chatrightrail fileBody m-0 min-w-0 whitespace-pre-wrap break-words font-[var(--font-mono)] [font-size:var(--vui-font-xs)] text-[var(--fg-primary)]",
  terminal: "vui-routes-chatrightrail terminal min-h-0 flex-1 overflow-hidden",
} as const;

export default styles;
