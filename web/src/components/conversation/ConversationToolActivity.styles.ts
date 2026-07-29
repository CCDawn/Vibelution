const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  activity: cx("activity", "grid w-fit max-w-full min-w-0 gap-0 py-0.5"),
  activityRow: cx("activityRow", "w-fit max-w-full min-w-0"),
  item: cx("item", "w-fit max-w-full min-w-0"),
  itemDetails: cx("itemDetails", "w-fit max-w-full min-w-0"),
  itemSummary: cx(
    "itemSummary",
    "inline-grid w-fit max-w-full min-w-0 cursor-pointer grid-cols-[17px_minmax(0,auto)] items-start gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  itemStatic: cx(
    "itemStatic",
    "inline-grid w-fit max-w-full min-w-0 grid-cols-[17px_minmax(0,auto)] items-start gap-x-2 py-1",
  ),
  batch: cx("batch", "w-fit max-w-full min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "inline-grid w-fit max-w-full min-w-0 cursor-pointer grid-cols-[17px_minmax(0,auto)] items-start gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  batchCount: cx("batchCount", "shrink-0 text-[var(--fg-tertiary)]"),
  batchDetails: cx(
    "batchDetails",
    "min-w-0",
  ),
  batchDetailsInner: cx("batchDetailsInner", "grid min-w-0 gap-0"),
  batchRow: cx("batchRow", "min-w-0"),
  itemIcon: cx("itemIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--fg-tertiary)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx(
    "itemBody",
    "inline-flex w-fit max-w-full min-w-0 items-baseline gap-x-1.5 [font-size:var(--vui-font-sm)] leading-5",
  ),
  itemTitle: cx("itemTitle", "shrink-0 text-[var(--fg-secondary)]"),
  itemPreview: cx(
    "itemPreview",
    "max-w-full min-w-0 truncate text-[var(--fg-tertiary)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "min-w-0 max-h-56 overflow-auto py-1 [&_pre]:max-h-56 [&_pre]:overflow-auto",
  ),
} as const;

export default styles;
