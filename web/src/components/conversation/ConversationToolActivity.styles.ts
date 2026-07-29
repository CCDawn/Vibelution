const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  activity: cx("activity", "mb-3 min-w-0 py-0.5"),
  activitySummary: cx(
    "activitySummary",
    "inline-flex min-h-7 max-w-full cursor-pointer items-start gap-2 py-1 text-left [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden hover:text-[var(--fg-secondary)] focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  activitySummaryBody: cx(
    "activitySummaryBody",
    "inline-flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5",
  ),
  activityIcon: cx("activityIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  activityIconRunning: cx("activityIconRunning", "text-[var(--accent-cool)]"),
  activityIconAttention: cx("activityIconAttention", "text-[var(--state-warning)]"),
  activityTitle: cx("activityTitle", "shrink-0 font-medium text-[var(--fg-secondary)]"),
  activityAttention: cx("activityAttention", "shrink-0 text-[var(--state-warning)]"),
  activityMeta: cx(
    "activityMeta",
    "min-w-0 truncate text-[var(--fg-tertiary)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]",
  ),
  activityChevron: cx(
    "activityChevron",
    "shrink-0 self-center text-[var(--fg-tertiary)] transition-transform duration-150",
  ),
  activityDetails: cx("activityDetails", "ml-6 grid min-w-0 gap-0 pt-1"),
  activityDetailsInner: cx("activityDetailsInner", "grid min-w-0 gap-0"),
  activityRow: cx("activityRow", "min-w-0"),
  item: cx("item", "min-w-0"),
  itemDetails: cx("itemDetails", "min-w-0"),
  itemSummary: cx(
    "itemSummary",
    "grid min-w-0 cursor-pointer grid-cols-[17px_minmax(0,1fr)] items-start gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  itemStatic: cx(
    "itemStatic",
    "grid min-w-0 grid-cols-[17px_minmax(0,1fr)] items-start gap-x-2 py-1",
  ),
  batch: cx("batch", "min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "grid min-w-0 cursor-pointer grid-cols-[17px_minmax(0,1fr)] items-start gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  batchCount: cx("batchCount", "shrink-0 text-[var(--fg-tertiary)]"),
  batchDetails: cx(
    "batchDetails",
    "ml-6 min-w-0",
  ),
  batchDetailsInner: cx("batchDetailsInner", "grid min-w-0 gap-0"),
  batchRow: cx("batchRow", "min-w-0"),
  itemIcon: cx("itemIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--fg-tertiary)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx(
    "itemBody",
    "flex min-w-0 items-baseline gap-x-1.5 [font-size:var(--vui-font-sm)] leading-5",
  ),
  itemTitle: cx("itemTitle", "shrink-0 text-[var(--fg-secondary)]"),
  itemPreview: cx(
    "itemPreview",
    "min-w-0 truncate text-[var(--fg-tertiary)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]",
  ),
  itemChevron: cx(
    "itemChevron",
    "shrink-0 self-center text-[var(--fg-tertiary)] transition-transform duration-150",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "ml-6 min-w-0 max-h-56 overflow-auto py-1 [&_pre]:max-h-56 [&_pre]:overflow-auto",
  ),
} as const;

export default styles;
