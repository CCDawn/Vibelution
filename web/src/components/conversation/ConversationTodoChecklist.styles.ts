const scope = "vui-components-conversationtodochecklist";

function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  card: cv(
    "card",
    "min-w-0 max-w-[min(100%,830px)] rounded-[14px] border border-[color-mix(in_srgb,var(--border-soft)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_92%,var(--vui-surface-workspace))] px-3 py-2 text-[var(--fg-secondary)] shadow-none",
  ),
  header: cv(
    "header",
    "flex min-w-0 cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-left [font-size:var(--vui-type-caption-size)] text-[var(--fg-secondary)]",
  ),
  chevron: cv("chevron", "shrink-0 text-[var(--fg-tertiary)]"),
  title: cv("title", "min-w-0 truncate font-medium"),
  counter: cv(
    "counter",
    "shrink-0 rounded-full border border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] px-1.5 py-px text-[var(--fg-tertiary)] tabular-nums",
  ),
  warning: cv(
    "warning",
    "mt-1.5 flex min-w-0 items-center gap-1.5 text-[var(--fg-secondary)] [font-size:var(--vui-type-caption-size)] text-[var(--accent-warm)]",
  ),
  list: cv("list", "mt-1.5 grid min-w-0 list-none gap-1 p-0"),
  item: cv("item", "flex min-w-0 items-center gap-2 [font-size:var(--vui-font-sm)] leading-snug"),
  itemCompleted: cv("itemCompleted", "text-[var(--fg-tertiary)]"),
  itemActive: cv("itemActive", "text-[var(--fg-primary)]"),
  checkIcon: cv("checkIcon", "shrink-0 text-[var(--accent-cool)]"),
  spinnerIcon: cv("spinnerIcon", "shrink-0 animate-spin text-[var(--accent-cool)]"),
  pendingIcon: cv("pendingIcon", "shrink-0 text-[var(--fg-tertiary)] opacity-60"),
  itemText: cv("itemText", "min-w-0"),
} as const;

export default styles;
