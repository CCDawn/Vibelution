const scope = "vui-components-conversationactiveturnstatusnote";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  note: cv(
    "note",
    "min-w-0 inline-flex max-w-[min(100%,920px)] items-center gap-2 bg-transparent py-1 text-vui-sm leading-tight text-[var(--fg-secondary)]",
  ),
  body: cv("body", "min-w-0 inline-flex max-w-full flex-wrap items-center gap-x-2 gap-y-1"),
  advisoryNote: cv("advisory-note", "min-w-0 max-w-full text-vui-sm"),
  // Whole row is the reasoning trigger (ZCode CollapsibleTrigger): the label,
  // the preview and the chevron share one hit target.
  textRow: cv(
    "textRow",
    "group/waiting min-w-0 flex w-full flex-wrap items-center gap-2 rounded-[var(--radius-control)] bg-transparent p-0 text-left",
  ),
  summary: cv(
    "summary",
    "min-w-0 flex-1 overflow-hidden whitespace-nowrap text-vui-sm text-[var(--fg-tertiary)] [mask-image:linear-gradient(to_right,transparent_0,black_16px,black_calc(100%-16px),transparent_100%)]",
  ),
  summaryText: cv("summaryText", "inline-block min-w-max"),
  // Hidden until hover, like ZCode: the affordance exists but never competes
  // with the status label.
  chevron: cv(
    "chevron",
    "shrink-0 text-[var(--fg-tertiary)] opacity-0 transition-[opacity,transform] duration-150 group-hover/waiting:opacity-100 data-[active-turn-thinking-chevron=expanded]:rotate-90 data-[active-turn-thinking-chevron=expanded]:opacity-100",
  ),
  thinkingBody: cv(
    "thinkingBody",
    "mt-1 basis-full max-h-60 overflow-auto whitespace-pre-wrap break-words border-l border-[var(--vui-border-subtle)] pl-3.5 text-vui-sm text-[var(--fg-tertiary)]",
  ),
  // Static semantic icon on the shared 16px column; the sweep in `textHead`
  // is what communicates activity.
  icon: cv("icon", "shrink-0 text-[var(--fg-tertiary)]"),
  text: cv("text", "min-w-0 flex-1 truncate text-vui-sm"),
  textHead: cv("textHead", "font-medium text-[var(--fg-secondary)]"),
  duration: cv("duration", "font-normal text-[var(--fg-tertiary)]"),
  label: cv("label", "sr-only"),
  advisory: cv("advisory", "shrink-0"),
  // Manual reconnect affordance beside the disconnect chip: same row, fixed
  // footprint so the flex-wrap body never squashes the control.
  reconnectAction: cv("reconnectAction", "shrink-0"),
  // Visible retry counter (attempt >= 3) only; the sweep itself lives in the
  // global `.vui-shimmer-text` keyframes (design/base.css).
  retryShimmer: cv("retryShimmer", "vui-shimmer-text"),
} as const;

export default styles;
