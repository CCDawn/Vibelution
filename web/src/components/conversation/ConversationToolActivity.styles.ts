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
  group: cx("group", "w-full max-w-full min-w-0 my-1"),
  groupSummary: cx(
    "groupSummary",
    "flex w-full max-w-full min-w-0 cursor-pointer items-baseline gap-x-1.5 py-1 text-left [font-size:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden hover:text-[var(--fg-secondary)] focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  groupTitle: cx("groupTitle", "min-w-0 font-normal text-[var(--fg-tertiary)]"),
  groupMeta: cx("groupMeta", "shrink-0 text-[color-mix(in_srgb,var(--fg-tertiary)_82%,transparent)]"),
  groupDetails: cx("groupDetails", "min-w-0"),
  approvalSlot: cx(
    "approvalSlot",
    "mt-1.5 w-full max-w-[min(42rem,100%)] min-w-[min(20rem,100%)]",
  ),
  item: cx("item", "w-full max-w-full min-w-0"),
  itemDetails: cx("itemDetails", "w-full max-w-full min-w-0"),
  itemSummary: cx(
    "itemSummary",
    "flex w-full max-w-full min-w-0 cursor-pointer items-center gap-x-2 py-[0.28rem] text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  itemStatic: cx(
    "itemStatic",
    "flex w-full max-w-full min-w-0 items-center gap-x-2 py-[0.28rem]",
  ),
  batch: cx("batch", "w-full max-w-full min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "flex w-full max-w-full min-w-0 cursor-pointer items-center gap-x-2 py-[0.28rem] text-left [&::-webkit-details-marker]:hidden focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  batchCount: cx(
    "batchCount",
    "shrink-0 [font-size:var(--vui-font-xs)] font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_88%,transparent)]",
  ),
  batchDetails: cx(
    "batchDetails",
    "min-w-0",
  ),
  batchDetailsInner: cx("batchDetailsInner", "grid min-w-0 gap-0 pl-1"),
  batchRow: cx("batchRow", "min-w-0"),
  // Tool chrome stays quieter than narrative body (fg-primary).
  itemIcon: cx("itemIcon", "shrink-0 text-[color-mix(in_srgb,var(--fg-tertiary)_90%,transparent)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--fg-tertiary)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx(
    "itemBody",
    "inline-flex w-full max-w-full min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 [font-size:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-tertiary)]",
  ),
  // Codex-style pill pair: action | status
  actionPill: cx(
    "actionPill",
    "inline-flex shrink-0 items-center rounded-full border border-[color-mix(in_srgb,var(--fg-tertiary)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)] px-2 py-[0.12rem] [font-size:var(--vui-font-xs)] font-medium leading-[1.35] text-[var(--fg-secondary)]",
  ),
  statusPill: cx(
    "statusPill",
    "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-[0.12rem] [font-size:var(--vui-font-xs)] font-medium leading-[1.35]",
  ),
  statusPill_running: cx(
    "statusPill_running",
    "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-[var(--accent-cool)]",
  ),
  statusPill_completed: cx(
    "statusPill_completed",
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--vui-control-muted)_55%,transparent)] text-[var(--fg-tertiary)]",
  ),
  statusPill_failed: cx(
    "statusPill_failed",
    "border-[color-mix(in_srgb,var(--state-error)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]",
  ),
  statusPill_timeout: cx(
    "statusPill_timeout",
    "border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  ),
  statusPill_attention: cx(
    "statusPill_attention",
    "border-[color-mix(in_srgb,var(--state-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] text-[var(--state-warning)]",
  ),
  statusPill_idle: cx(
    "statusPill_idle",
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,var(--vui-border-subtle))] bg-transparent text-[var(--fg-tertiary)]",
  ),
  itemTitle: cx(
    "itemTitle",
    "min-w-0 max-w-full font-normal text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  ),
  itemPreview: cx(
    "itemPreview",
    "max-w-full min-w-0 truncate font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_82%,transparent)] max-[719px]:whitespace-normal max-[719px]:[overflow-wrap:anywhere]",
  ),
  itemDuration: cx(
    "itemDuration",
    "shrink-0 font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_78%,transparent)]",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "min-w-0 max-h-48 overflow-auto py-1 pl-1 text-[var(--fg-tertiary)] [font-size:var(--vui-font-xs)] leading-[1.45] [&_pre]:max-h-48 [&_pre]:overflow-auto [&_pre]:text-[var(--fg-tertiary)]",
  ),
} as const;

export default styles;
