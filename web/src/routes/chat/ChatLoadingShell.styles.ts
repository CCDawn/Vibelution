import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  pulse:
    "animate-pulse bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)]",
  indexShell:
    "grid min-w-0 content-start gap-2 px-1 py-0.5",
  indexGroup:
    "grid min-w-0 gap-1.5 rounded-[var(--vui-radius-panel-soft)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] !bg-[var(--vui-surface-row)] p-1.5",
  indexGroupHeader:
    "flex min-h-6 items-center justify-between gap-3 px-0.5",
  indexGroupTitle:
    "h-2.5 w-24 rounded-full",
  indexGroupCount:
    "size-4 rounded-full",
  indexCard:
    "grid min-h-[48px] grid-cols-[30px_minmax(0,1fr)] items-center gap-2 rounded-[var(--radius-control)] px-1.5 py-1",
  indexAvatar:
    "size-7 rounded-full",
  indexCopy:
    "grid min-w-0 gap-2",
  indexTitle:
    "h-2.5 w-[62%] rounded-full",
  indexMeta:
    "h-2 w-[82%] rounded-full opacity-70",
  workspaceShell:
    "relative grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden",
  transcript:
    "grid min-h-0 content-start gap-7 overflow-hidden px-[clamp(18px,7vw,112px)] pb-6 pt-8",
  assistantTurn:
    "grid max-w-[760px] grid-cols-[32px_minmax(0,1fr)] items-start gap-3",
  userTurn:
    "ml-auto grid w-[min(420px,68%)] justify-items-end gap-2",
  avatar:
    "size-8 rounded-full",
  messageCopy:
    "grid min-w-0 gap-2.5 pt-1",
  messageHeading:
    "h-2.5 w-28 rounded-full",
  messageLineWide:
    "h-2.5 w-full rounded-full",
  messageLine:
    "h-2.5 w-[78%] rounded-full opacity-80",
  userBubble:
    "h-10 w-full rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_74%,transparent)] !bg-[var(--vui-surface-row)]",
  composerWrap: `mx-auto mb-3 grid w-[min(calc(100%_-_32px),960px)] gap-2 ${vuiFlatPanelClass} p-3 shadow-[var(--vui-shadow-hairline)]`,
  composerInput:
    "h-11 w-full rounded-[var(--radius-control)] !bg-[var(--vui-surface-row)]",
  composerToolbar:
    "flex items-center justify-between gap-3",
  composerTools:
    "flex items-center gap-2",
  composerTool:
    "h-6 w-20 rounded-full",
  composerToolSmall:
    "size-6 rounded-full",
  composerSend:
    "size-8 rounded-[var(--radius-control)]",
} as const;

export default styles;
