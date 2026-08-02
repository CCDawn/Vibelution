const scope = "vui-components-conversationactiveturnstatusnote";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  note: cv(
    "note",
    "min-w-0 inline-grid w-[min(100%,920px)] grid-cols-[auto_minmax(0,1fr)] items-start gap-2 border-l border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent py-1 pl-2.5 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  ),
  label: cv(
    "label",
    "min-w-0 shrink-0 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  ),
  body: cv("body", "min-w-0 grid gap-1"),
  textRow: cv("textRow", "min-w-0 inline-flex max-w-full items-center gap-1.5"),
  spinner: cv("spinner", "shrink-0 animate-spin text-[var(--accent-cool)]"),
  text: cv(
    "text",
    "min-w-0 max-w-[min(100%,128ch)] whitespace-normal [overflow-wrap:anywhere]",
  ),
  stageBar: cv(
    "stageBar",
    "min-w-0 inline-flex max-w-full flex-wrap items-center gap-1 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  ),
  stageItem: cv("stageItem", "shrink-0 text-[var(--fg-tertiary)] opacity-70"),
  stageItemReached: cv("stageItemReached", "shrink-0 text-[var(--fg-secondary)] opacity-100"),
  stageItemCurrent: cv(
    "stageItemCurrent",
    "shrink-0 font-semibold text-[var(--fg-secondary)] opacity-100",
  ),
  stageSeparator: cv("stageSeparator", "shrink-0 opacity-50"),
} as const;

export default styles;
