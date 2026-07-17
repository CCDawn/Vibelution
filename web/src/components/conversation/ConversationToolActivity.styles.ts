const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  activity: cx("activity", "grid min-w-0 gap-1.5"),
  group: cx(
    "group",
    "group min-w-0 overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_68%,transparent)]",
  ),
  groupSummary: cx(
    "groupSummary",
    "grid min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 px-3 py-2 text-left [&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:ring-inset",
  ),
  groupIcon: cx("groupIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  groupBody: cx("groupBody", "grid min-w-0 gap-0.5"),
  groupTitleLine: cx("groupTitleLine", "flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5"),
  groupTitle: cx("groupTitle", "font-semibold text-[var(--vui-font-sm)] leading-5 text-[var(--fg-primary)]"),
  groupMeta: cx("groupMeta", "text-[var(--vui-font-xs)] leading-5 text-[var(--fg-tertiary)]"),
  groupPreview: cx("groupPreview", "min-w-0 truncate text-[var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]"),
  groupChevron: cx("groupChevron", "mt-0.5 shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150 group-open:rotate-90"),
  groupItems: cx("groupItems", "grid min-w-0 gap-0.5 border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] px-1.5 py-1.5"),
  item: cx("item", "min-w-0"),
  itemDetails: cx(
    "itemDetails",
    "group min-w-0 rounded-[var(--radius-control)] border border-transparent bg-transparent open:border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] open:bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)]",
  ),
  itemSummary: cx(
    "itemSummary",
    "grid min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 rounded-[var(--radius-control)] px-2 py-1.5 text-left hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_70%,transparent)] [&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:ring-inset",
  ),
  itemStatic: cx("itemStatic", "grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 rounded-[var(--radius-control)] px-2 py-1.5"),
  itemIcon: cx("itemIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--state-error)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx("itemBody", "grid min-w-0 gap-0.5"),
  itemTitleLine: cx("itemTitleLine", "flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5"),
  itemTitle: cx("itemTitle", "font-semibold text-[var(--vui-font-sm)] leading-5 text-[var(--fg-primary)]"),
  itemMeta: cx("itemMeta", "text-[var(--vui-font-xs)] leading-5 text-[var(--fg-tertiary)]"),
  itemPreview: cx("itemPreview", "min-w-0 truncate text-[var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]"),
  itemChevron: cx("itemChevron", "mt-0.5 shrink-0 text-[var(--fg-tertiary)] transition-transform duration-150 group-open:rotate-90"),
  itemDetailsBody: cx("itemDetailsBody", "min-w-0 border-t border-[color-mix(in_srgb,var(--vui-border-subtle)_65%,transparent)] px-2.5 py-2 [&_pre]:max-h-72 [&_pre]:overflow-auto"),
} as const;

export default styles;
