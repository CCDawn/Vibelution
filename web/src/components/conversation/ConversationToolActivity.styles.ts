const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  // Codex-aligned continuous tool rail: top/bottom frame + capped scroll height.
  activity: cx(
    "activity",
    "grid w-full max-w-full min-w-0 gap-0 border-y border-[color-mix(in_srgb,var(--fg-tertiary)_22%,var(--vui-border-subtle))] py-1.5 my-1 max-h-[min(18rem,42vh)] overflow-y-auto overflow-x-hidden [scrollbar-width:thin] [scrollbar-color:color-mix(in_srgb,var(--fg-tertiary)_35%,transparent)_transparent]",
  ),
  activityRow: cx("activityRow", "w-full max-w-full min-w-0"),
  approvalSlot: cx(
    "approvalSlot",
    "mt-1.5 w-full max-w-[min(42rem,100%)] min-w-[min(20rem,100%)]",
  ),
  item: cx("item", "w-full max-w-full min-w-0"),
  itemDetails: cx("itemDetails", "w-full max-w-full min-w-0"),
  itemSummary: cx(
    "itemSummary",
    "inline-grid w-full max-w-full min-w-0 cursor-pointer grid-cols-[15px_minmax(0,1fr)] items-start gap-x-2 py-[0.2rem] text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  itemStatic: cx(
    "itemStatic",
    "inline-grid w-full max-w-full min-w-0 grid-cols-[15px_minmax(0,1fr)] items-start gap-x-2 py-[0.2rem]",
  ),
  batch: cx("batch", "w-full max-w-full min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "inline-grid w-full max-w-full min-w-0 cursor-pointer grid-cols-[15px_minmax(0,1fr)] items-start gap-x-2 py-[0.2rem] text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  batchCount: cx(
    "batchCount",
    "shrink-0 [font-size:var(--vui-font-xs)] font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_88%,transparent)]",
  ),
  batchDetails: cx(
    "batchDetails",
    "min-w-0",
  ),
  batchDetailsInner: cx("batchDetailsInner", "grid min-w-0 gap-0 pl-[23px]"),
  batchRow: cx("batchRow", "min-w-0"),
  // Tool chrome stays quieter than narrative body (fg-primary).
  itemIcon: cx("itemIcon", "mt-[0.2rem] shrink-0 text-[color-mix(in_srgb,var(--fg-tertiary)_90%,transparent)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--fg-tertiary)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx(
    "itemBody",
    "inline-flex w-full max-w-full min-w-0 items-baseline gap-x-1.5 [font-size:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-tertiary)]",
  ),
  itemTitle: cx(
    "itemTitle",
    "min-w-0 max-w-full font-normal text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  ),
  itemPreview: cx(
    "itemPreview",
    "max-w-full min-w-0 truncate font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_82%,transparent)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "min-w-0 max-h-48 overflow-auto py-1 pl-[23px] text-[var(--fg-tertiary)] [font-size:var(--vui-font-xs)] leading-[1.45] [&_pre]:max-h-48 [&_pre]:overflow-auto [&_pre]:text-[var(--fg-tertiary)]",
  ),
} as const;

export default styles;
