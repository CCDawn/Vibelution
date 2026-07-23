const styles = {
  operationsGrid: "grid min-w-0 grid-cols-2 gap-2 max-[900px]:grid-cols-1",
  section: "min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-row)_54%,transparent)] p-2.5",
  panelHeader: "flex min-w-0 items-start justify-between gap-3",
  eyebrow: "m-0 [font-size:var(--vui-font-xs)] font-medium text-[var(--fg-tertiary)]",
  title: "m-0 text-sm font-semibold text-[var(--fg-primary)]",
  runtimeStatus: "mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1",
  runtimePill: "inline-flex shrink-0 items-center rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_44%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-2 py-0.5 text-[11px] font-semibold text-[var(--fg-primary)]",
  runtimeSummary: "m-0 mt-2 break-words text-sm leading-5 text-[var(--fg-primary)]",
  runtimeMeta: "mt-3 grid grid-cols-2 gap-2 max-[620px]:grid-cols-1 [&_span]:min-w-0 [&_span]:rounded-[var(--radius-control)] [&_span]:bg-[color-mix(in_srgb,var(--vui-surface-base)_58%,transparent)] [&_span]:px-2 [&_span]:py-1.5 [&_strong]:block [&_strong]:text-[11px] [&_strong]:font-medium [&_strong]:text-[var(--fg-tertiary)] [&_small]:block [&_small]:truncate [&_small]:text-xs [&_small]:text-[var(--fg-primary)]",
  nextStep: "mt-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_25%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-2.5 py-2 text-xs leading-5 text-[var(--fg-primary)] [&_strong]:mr-1 [&_strong]:font-semibold",
  actions: "mt-3 flex flex-wrap gap-2",
  activityBody: "mt-2 min-h-[132px]",
  activityList: "grid gap-1.5",
  activityItem: "grid min-w-0 grid-cols-[minmax(0,_1fr)_auto] gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_65%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_54%,transparent)] px-2.5 py-2",
  activityText: "min-w-0 [&_strong]:block [&_strong]:truncate [&_strong]:text-xs [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:mt-0.5 [&_p]:line-clamp-1 [&_p]:text-xs [&_p]:text-[var(--fg-secondary)] [&_small]:mt-1 [&_small]:block [&_small]:truncate [&_small]:text-[11px] [&_small]:text-[var(--fg-tertiary)]",
  activityAction: "self-center",
  state: "grid min-h-[132px] place-items-center rounded-[var(--radius-control)] border border-dashed border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_38%,transparent)] p-3 text-center",
  stateInner: "grid max-w-[360px] justify-items-center gap-2 [&_strong]:text-sm [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)] [&_p]:m-0 [&_p]:text-xs [&_p]:leading-5 [&_p]:text-[var(--fg-secondary)]",
  error: "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--status-danger)_48%,transparent)] bg-[color-mix(in_srgb,var(--status-danger)_10%,transparent)] px-2.5 py-2 text-xs leading-5 text-[var(--fg-primary)]",
} as const;

export default styles;
