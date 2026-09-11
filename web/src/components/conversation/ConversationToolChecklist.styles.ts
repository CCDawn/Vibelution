const scope = "vui-components-conversation-tool-checklist";

const styles = {
  root:
    `${scope} root grid min-w-0 max-w-full gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2`,
  header:
    `${scope} header flex min-w-0 max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5`,
  title:
    `${scope} title min-w-0 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]`,
  progress:
    `${scope} progress shrink-0 tabular-nums [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]`,
  explanation:
    `${scope} explanation min-w-0 w-full [overflow-wrap:anywhere] [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]`,
  items:
    `${scope} items m-0 grid list-none gap-1 p-0`,
  item:
    `${scope} item grid min-w-0 grid-cols-[0.875rem_minmax(0,1fr)] items-start gap-x-1.5 [font-size:var(--vui-font-xs)] leading-[1.5]`,
  marker:
    `${scope} marker mt-[0.12rem] inline-grid size-3.5 shrink-0 place-items-center`,
  label:
    `${scope} label min-w-0 [overflow-wrap:anywhere] text-[var(--fg-secondary)]`,
  marker_completed:
    `${scope} markerCompleted text-[var(--state-success)]`,
  marker_in_progress:
    `${scope} markerInProgress text-[var(--accent-cool)]`,
  marker_pending:
    `${scope} markerPending text-[color-mix(in_srgb,var(--fg-tertiary)_72%,transparent)]`,
  label_completed:
    `${scope} labelCompleted text-[color-mix(in_srgb,var(--fg-tertiary)_84%,transparent)]`,
  label_in_progress:
    `${scope} labelInProgress font-medium text-[var(--fg-primary)]`,
  label_pending:
    `${scope} labelPending text-[var(--fg-secondary)]`,
} as const;

export default styles;
