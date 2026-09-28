const scope = "vui-components-conversation-tool-activity";

function cx(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}

const styles = {
  // Continuous tool rail: no horizontal frame lines; spacing + scroll only.
  activity: cx(
    "activity",
    "grid w-full max-w-full min-w-0 gap-0 border-0 py-1 my-0.5 max-h-[min(18rem,42vh)] overflow-y-auto overflow-x-hidden [scrollbar-width:thin] [scrollbar-color:color-mix(in_srgb,var(--fg-tertiary)_35%,transparent)_transparent]",
  ),
  activityRow: cx("activityRow", "w-full max-w-full min-w-0"),
  group: cx("group", "w-full max-w-full min-w-0 my-1"),
  groupSummary: cx(
    "groupSummary",
    // list-none + empty ::marker: kill native <details> disclosure (Edge shows a lone ">")
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-baseline gap-x-1.5 py-1 text-left text-vui-xs leading-[1.45] text-[var(--fg-tertiary)] [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none hover:text-[var(--fg-secondary)] focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
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
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-center gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  // Static (no-toggle) tool row: same single-line chrome as the expandable
  // summary, minus the pointer affordance. The flex row is load-bearing -
  // Tailwind preflight renders the leading lucide <svg> as display:block, so a
  // plain block wrapper drops the icon onto its own line above the subject.
  itemStatic: cx(
    "itemStatic",
    "flex w-full max-w-full min-w-0 items-center gap-x-2 py-1",
  ),
  itemChevron: cx(
    "itemChevron",
    "ml-auto shrink-0 text-[color-mix(in_srgb,var(--fg-tertiary)_70%,transparent)] transition-transform duration-150 group-open:rotate-90",
  ),
  itemDetailsEmpty: cx(
    "itemDetailsEmpty",
    "m-0 py-0.5 text-[color-mix(in_srgb,var(--fg-tertiary)_82%,transparent)]",
  ),
  batch: cx("batch", "w-full max-w-full min-w-0"),
  batchSummary: cx(
    "batchSummary",
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-center gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  batchCount: cx(
    "batchCount",
    "shrink-0 text-vui-xs font-normal text-[color-mix(in_srgb,var(--fg-tertiary)_88%,transparent)]",
  ),
  batchDetails: cx(
    "batchDetails",
    "min-w-0",
  ),
  batchDetailsInner: cx("batchDetailsInner", "grid min-w-0 gap-0 pl-1"),
  batchRow: cx("batchRow", "min-w-0"),
  // Category parent group (ZCode Explore/Execute-style stage container): same
  // quiet row chrome as batches; colors/state live in the shared tokens.
  categoryGroup: cx("categoryGroup", "w-full max-w-full min-w-0"),
  categoryGroupSummary: cx(
    "categoryGroupSummary",
    "flex w-full max-w-full min-w-0 list-none cursor-pointer items-center gap-x-2 py-1 text-left [&::-webkit-details-marker]:hidden [&::marker]:hidden [&::marker]:content-none focus-visible:rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
  ),
  categoryGroupDetails: cx("categoryGroupDetails", "min-w-0"),
  categoryGroupDetailsInner: cx("categoryGroupDetailsInner", "grid min-w-0 gap-0 pl-1"),
  categoryGroupRow: cx("categoryGroupRow", "min-w-0"),
  // Tool chrome stays quieter than narrative body (fg-primary).
  itemIcon: cx("itemIcon", "shrink-0 text-[color-mix(in_srgb,var(--fg-tertiary)_90%,transparent)]"),
  itemIconRunning: cx("itemIconRunning", "text-[var(--accent-cool)]"),
  itemIconFailed: cx("itemIconFailed", "text-[var(--fg-tertiary)]"),
  itemIconWarning: cx("itemIconWarning", "text-[var(--state-warning)]"),
  itemBody: cx(
    "itemBody",
    // Single-line Codex tool row: icon + plain action + muted subject + duration.
    "inline-flex w-full max-w-full min-w-0 items-center gap-x-1.5 text-vui-xs leading-[1.4] text-[var(--fg-tertiary)]",
  ),
  // Plain action label (no chip chrome). data-codex-tool-action-pill kept for tests/selectors.
  actionLabel: cx(
    "actionLabel",
    "shrink-0 font-medium text-[var(--fg-secondary)]",
  ),
  // Running rows keep the leading icon static; the action word carries the
  // live state via a text shimmer (gradient sweep, see ConversationToolActivity.css).
  // inline-block is required for background-clip:text on a span.
  actionLabelRunning: cx(
    "actionLabelRunning",
    "inline-block",
  ),
  // Legacy alias used by tests / external selectors that still reference actionPill.
  actionPill: cx(
    "actionPill",
    "shrink-0 font-medium text-[var(--fg-secondary)]",
  ),
  // Explicit status text only for failure / attention — never dual status chips.
  // ZCode-aligned failure language: the colored word + a dashed underline carries
  // the failure semantics (hover reveals the error summary); no red icon blast.
  statusLabel: cx(
    "statusLabel",
    "shrink-0 font-normal text-[var(--fg-tertiary)] underline decoration-dashed underline-offset-2",
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
  // ZCode subagent-name chip: layout only here — the tinted colors derive from
  // the inline `--subagent-accent` custom property (see ConversationToolActivity.css).
  agentNameChip: cx(
    "agentNameChip",
    "inline-flex max-w-full min-w-0 shrink items-center overflow-hidden whitespace-nowrap align-baseline",
  ),
  itemDuration: cx(
    "itemDuration",
    "ml-auto shrink-0 font-normal tabular-nums text-[color-mix(in_srgb,var(--fg-tertiary)_72%,transparent)]",
  ),
  diffStatLabel: cx(
    "diffStatLabel",
    "shrink-0 font-normal tabular-nums text-[color-mix(in_srgb,var(--fg-tertiary)_78%,transparent)]",
  ),
  itemDetailsBody: cx(
    "itemDetailsBody",
    "min-w-0 max-h-48 overflow-auto py-1 pl-1 text-[var(--fg-tertiary)] text-vui-xs leading-[1.45] [&_pre]:max-h-48 [&_pre]:overflow-auto [&_pre]:text-[var(--fg-tertiary)]",
  ),
  // Failure rows keep the full error in the expanded body and add a copy
  // affordance (ZCode: failure = word + dashed underline + tooltip + copyable
  // details, not a red card). Mirrors the markdown code block header button.
  itemDetailsActions: cx(
    "itemDetailsActions",
    "flex w-full items-center justify-end py-0.5",
  ),
  itemDetailsCopyButton: cx(
    "itemDetailsCopyButton",
    "inline-flex h-5 w-5 place-items-center p-0 text-[var(--fg-tertiary)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)]",
  ),
} as const;

export default styles;
