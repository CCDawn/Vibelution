const worktreeReviewSurfaceClass = "grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-2 overflow-hidden rounded-lg border border-vui-border-soft bg-[var(--surface-panel-strong)] px-3 pb-3 pt-2.5 text-[0.9rem]";
const surfaceHeaderCompactClass = "flex min-w-0 items-center justify-between gap-2.5";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-0.5 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--accent-warm-2)]";
const sectionTitleClass = "m-0 text-base font-bold leading-[1.22] text-vui-fg-primary";
const secondaryPillClass = "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card-muted)] px-2 text-xs font-semibold text-vui-fg-secondary";
const statusPillClass = "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_13%,transparent)] px-2 text-xs font-semibold text-[var(--accent-warm-2)]";
const noticeTextClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-vui-fg-secondary";
const gateNoticeTextClass = "m-0 overflow-hidden break-words text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]";
const errorTextClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-[var(--state-error)]";
const controlFooterClass = "grid min-h-0 gap-[7px] overflow-auto pr-0.5";
const closedLoopStatusClass = "grid min-h-[30px] min-w-0 grid-cols-[auto_minmax(56px,auto)_minmax(0,1fr)] items-center gap-[7px] rounded-[7px] border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2 py-1 text-[var(--vui-font-xs)] max-[640px]:grid-cols-1";
const closedLoopStrongClass = "min-w-0 truncate";
const closedLoopMessageClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-secondary";
const worktreeRunPickerClass = "grid min-w-0 gap-[5px]";
const worktreeRunPickerHeaderClass = "flex min-h-5 items-center justify-between gap-2 text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const worktreeRunListClass = "grid max-h-[clamp(92px,16vh,148px)] gap-1 overflow-auto";
const worktreeRunItemClass = "grid min-h-8 min-w-0 grid-cols-[minmax(0,1.25fr)_minmax(78px,0.55fr)_minmax(0,1fr)] items-center gap-2 rounded-[7px] border border-[var(--border-hairline)] bg-[var(--surface-card-muted)] px-2 py-1 text-left text-[var(--vui-font-xs)] text-vui-fg-primary max-[640px]:grid-cols-1";
const worktreeRunItemActiveClass = "border-[color-mix(in_srgb,var(--accent-cool)_34%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--surface-card-muted))]";
const worktreeRunItemTopClass = "contents";
const worktreeRunIdClass = "min-w-0 truncate font-[var(--font-mono)] text-[var(--vui-font-xs)] font-semibold text-vui-fg-primary";
const worktreeRunStatusClass = "inline-flex min-h-5 max-w-full items-center justify-self-start truncate rounded-full border border-vui-border-soft bg-[var(--surface-card-subtle)] px-[7px] text-[var(--vui-font-xs)] leading-[1.25] text-vui-fg-secondary";
const worktreeRunMetaClass = "inline-flex min-w-0 items-center justify-self-end truncate text-right text-[var(--vui-font-xs)] leading-[1.25] text-vui-fg-tertiary max-[640px]:justify-self-start max-[640px]:text-left";
const worktreeReviewGateClass = "grid min-w-0 gap-1.5 rounded-[7px] border border-[color-mix(in_srgb,var(--accent-cool)_26%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--surface-card-subtle))] px-2.5 py-2";
const worktreeActionGateClass = "py-[7px]";
const gateActionGridClass = "grid grid-cols-2 gap-[7px]";
const controlActionsClass = "flex flex-wrap gap-2";
const inlineActionClass = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card-muted)] px-3.5 text-[var(--vui-font-xs)] font-semibold text-vui-fg-primary disabled:cursor-not-allowed disabled:opacity-55";
const gateInlineActionClass = "min-h-[34px] min-w-0 px-[9px]";
const dangerInlineActionClass = "border-[color-mix(in_srgb,var(--state-error)_38%,var(--border-soft))] text-[var(--state-error)] hover:bg-[color-mix(in_srgb,var(--state-error)_10%,var(--surface-card-muted))]";
const worktreeReviewHeaderClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2";
const truncateTextClass = "min-w-0 max-w-full truncate";
const metaRowClass = "grid min-w-0 grid-cols-[minmax(90px,auto)_minmax(0,1fr)] gap-2 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const metaValueClass = "min-w-0 truncate";
const spinClass = "animate-spin";

const styles = {
  worktreeReviewSurfaceClass,
  surfaceHeaderCompactClass,
  headerCopyClass,
  eyebrowClass,
  sectionTitleClass,
  secondaryPillClass,
  statusPillClass,
  noticeTextClass,
  gateNoticeTextClass,
  errorTextClass,
  controlFooterClass,
  closedLoopStatusClass,
  closedLoopStrongClass,
  closedLoopMessageClass,
  worktreeRunPickerClass,
  worktreeRunPickerHeaderClass,
  worktreeRunListClass,
  worktreeRunItemClass,
  worktreeRunItemActiveClass,
  worktreeRunItemTopClass,
  worktreeRunIdClass,
  worktreeRunStatusClass,
  worktreeRunMetaClass,
  worktreeReviewGateClass,
  worktreeActionGateClass,
  gateActionGridClass,
  controlActionsClass,
  inlineActionClass,
  gateInlineActionClass,
  dangerInlineActionClass,
  worktreeReviewHeaderClass,
  truncateTextClass,
  metaRowClass,
  metaValueClass,
  spinClass,
} as const;

export default styles;
