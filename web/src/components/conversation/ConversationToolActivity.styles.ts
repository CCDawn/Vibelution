const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  activity: cx("activity", "grid min-w-0 gap-0"),
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
  itemIcon: cx("itemIcon", "mt-0.5 shrink-0 text-[var(--fg-tertiary)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--state-error)]"),
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
  itemDetailsBody: cx(
    "itemDetailsBody",
    "ml-6 min-w-0 border-l border-[var(--vui-border-subtle)] py-1 pl-2 [&_pre]:max-h-72 [&_pre]:overflow-auto",
  ),
} as const;

export default styles;
