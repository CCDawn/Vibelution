const scope = "vui-components-conversationactiveturnstatusnote";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  note: cv(
    "note",
    "min-w-0 inline-flex max-w-[min(100%,920px)] items-center gap-2 border-l border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent py-1 pl-2.5 text-vui-sm leading-tight text-[var(--fg-secondary)]",
  ),
  body: cv("body", "min-w-0 inline-flex max-w-full flex-wrap items-center gap-x-2 gap-y-1"),
  textRow: cv("textRow", "min-w-0 inline-flex max-w-full items-center gap-1.5"),
  spinner: cv("spinner", "shrink-0 animate-spin text-[var(--accent-cool)]"),
  text: cv(
    "text",
    "min-w-0 max-w-[min(100%,48ch)] truncate text-vui-sm text-[var(--fg-secondary)]",
  ),
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
