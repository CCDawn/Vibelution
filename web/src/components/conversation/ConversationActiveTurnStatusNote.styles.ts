const scope = "vui-components-conversationactiveturnstatusnote";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  note: cv(
    "note",
    "min-w-0 inline-flex max-w-[min(100%,920px)] items-center gap-2 border-l border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent py-1 pl-2.5 [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  ),
  body: cv("body", "min-w-0 inline-flex max-w-full flex-wrap items-center gap-x-2 gap-y-1"),
  textRow: cv("textRow", "min-w-0 inline-flex max-w-full items-center gap-1.5"),
  spinner: cv("spinner", "shrink-0 animate-spin text-[var(--accent-cool)]"),
  text: cv(
    "text",
    "min-w-0 max-w-[min(100%,48ch)] truncate [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]",
  ),
  label: cv("label", "sr-only"),
} as const;

export default styles;
