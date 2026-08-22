export default {
  fill: "h-full min-h-0",
  submissionReadiness: "grid gap-2 rounded border border-[color-mix(in_srgb,var(--state-warning)_35%,var(--vui-border-subtle))] bg-[var(--vui-surface-row)] p-3",
  submissionSummary: "mt-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  submissionGrid: "grid gap-1.5 sm:grid-cols-2",
  submissionItem: "flex items-center justify-between gap-2 rounded border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-raised)] px-2 py-1.5 [font-size:var(--vui-font-2xs)]",
  submissionItemLabel: "min-w-0 text-[var(--fg-primary)]",
  submissionActionRow: "flex flex-wrap items-center gap-2",
  submissionExportError: "rounded border border-[color-mix(in_srgb,var(--state-error)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-2 py-1.5 [font-size:var(--vui-font-2xs)] text-[var(--state-error)]",
  submissionDetails: "[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  submissionBlockers: "m-0 mt-1 grid gap-1 pl-4",
  sectionHeader: "flex flex-wrap items-center justify-between gap-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&>strong]:text-[var(--fg-primary)]",
} as const;
