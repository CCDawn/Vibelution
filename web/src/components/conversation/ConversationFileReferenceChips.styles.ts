const scope = "vui-components-conversationfilereferencechips";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  // One light chip row under the settled assistant body: neutral surface,
  // subtle border — reads as attachments, never as a second response block.
  row: cv(
    "row",
    "mt-1 flex flex-wrap items-center gap-1.5",
  ),
  chip: cv(
    "chip",
    "max-w-full min-w-0 gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-0.5 text-vui-xs font-medium text-[var(--fg-secondary)]",
  ),
  name: cv("name", "min-w-0 truncate font-mono"),
  badge: cv(
    "badge",
    "shrink-0 rounded-[var(--vui-radius-chip)] bg-[color-mix(in_srgb,var(--vui-border-subtle)_55%,transparent)] px-1 py-px text-[10px] font-semibold uppercase leading-tight text-[var(--fg-tertiary)]",
  ),
  hint: cv(
    "hint",
    "whitespace-nowrap text-vui-2xs text-[var(--fg-tertiary)]",
  ),
} as const;

export default styles;
