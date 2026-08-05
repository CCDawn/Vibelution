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
  // Compact 4-step track: no labels, only reached/current fill.
  stageBar: cv(
    "stageBar",
    "inline-flex shrink-0 items-center gap-1",
  ),
  stageBarItem: cv("stageBarItem", "inline-flex items-center"),
  stageDot: cv(
    "stageDot",
    "block h-1.5 w-1.5 shrink-0 rounded-full bg-[color-mix(in_srgb,var(--fg-tertiary)_42%,transparent)]",
  ),
  stageDotReached: cv(
    "stageDotReached",
    "block h-1.5 w-1.5 shrink-0 rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_48%,var(--fg-tertiary))]",
  ),
  stageDotCurrent: cv(
    "stageDotCurrent",
    "block h-2 w-2 shrink-0 rounded-full bg-[var(--accent-cool)] shadow-[0_0_0_2px_color-mix(in_srgb,var(--accent-cool)_20%,transparent)]",
  ),
  // Kept for older test selectors that sample class map keys.
  label: cv("label", "sr-only"),
  stageItem: cv("stageItem", "sr-only"),
  stageItemReached: cv("stageItemReached", "sr-only"),
  stageItemCurrent: cv("stageItemCurrent", "sr-only"),
  stageSeparator: cv("stageSeparator", "sr-only"),
} as const;

export default styles;
