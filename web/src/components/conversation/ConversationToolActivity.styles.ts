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
    // list-none + empty ::marker: kill native <details> disclosure (Edge shows a lone ">")
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-baseline gap-x-1.5 py-1 text-left [font-size:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
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
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-center gap-x-2 py-[0.28rem] text-left [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  itemStatic: cx(
    "itemStatic",
    "flex w-full max-w-full min-w-0 items-center gap-x-2 py-[0.28rem]",
  ),
  batch: cx("batch", "w-full max-w-full min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-center gap-x-2 py-[0.28rem] text-left [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
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
    // Single-line Codex tool row: icon + plain action + muted subject + duration.
    "inline-flex w-full max-w-full min-w-0 items-center gap-x-1.5 [font-size:var(--vui-font-xs)] leading-[1.4] text-[var(--fg-tertiary)]",
  ),
  // Plain action label (no chip chrome). data-codex-tool-action-pill kept for tests/selectors.
  actionLabel: cx(
    "actionLabel",
    "shrink-0 font-medium text-[var(--fg-secondary)]",
  ),
  // Legacy alias used by tests / external selectors that still reference actionPill.
  actionPill: cx(
    "actionPill",
    "shrink-0 font-medium text-[var(--fg-secondary)]",
  ),
  // Explicit status text only for failure / attention — never dual status chips.
  statusLabel: cx(
    "statusLabel",
    "shrink-0 font-normal text-[var(--fg-tertiary)]",
  ),
  statusLabel_failed: cx("statusLabel_failed", "text-[var(--state-error)]"),
  statusLabel_timeout: cx("statusLabel_timeout", "text-[var(--state-warning)]"),
  statusLabel_attention: cx("statusLabel_attention", "text-[var(--state-warning)]"),
  // Keep old keys so existing style-map tests fail clearly if reintroduced as chips.
  statusPill: cx("statusPill", "shrink-0 font-normal text-[var(--fg-tertiary)]"),
  statusPill_running: cx("statusPill_running", "text-[var(--accent-cool)]"),
  statusPill_completed: cx("statusPill_completed", "text-[var(--fg-tertiary)]"),
  statusPill_failed: cx("statusPill_failed", "text-[var(--state-error)]"),
  statusPill_timeout: cx("statusPill_timeout", "text-[var(--state-warning)]"),
  statusPill_attention: cx("statusPill_attention", "text-[var(--state-warning)]"),
  statusPill_idle: cx("statusPill_idle", "text-[var(--fg-tertiary)]"),
  itemTitle: cx(
    "itemTitle",
    "min-w-0 max-w-full font-normal text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  ),
  itemPreview: cx(
    "itemPreview",
    "max-w-full min-w-0 flex-1 truncate font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_78%,transparent)]",
  ),
  itemDuration: cx(
    "itemDuration",
    "ml-auto shrink-0 font-normal tabular-nums text-[color-mix(in_srgb,var(--fg-tertiary)_72%,transparent)]",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "min-w-0 max-h-48 overflow-auto py-1 pl-1 text-[var(--fg-tertiary)] [font-size:var(--vui-font-xs)] leading-[1.45] [&_pre]:max-h-48 [&_pre]:overflow-auto [&_pre]:text-[var(--fg-tertiary)]",
  ),
} as const;

export default styles;
