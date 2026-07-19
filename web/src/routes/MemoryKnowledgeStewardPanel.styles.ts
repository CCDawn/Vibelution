const styles = {
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  knowledgeStewardPanel:
    "knowledgeStewardPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  managementActions:
    "managementActions min-w-0 flex flex-wrap items-center gap-1.5",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPill:
    "statusPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  stewardActionGrid:
    "stewardActionGrid min-w-0 flex flex-wrap items-center gap-1.5 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  stewardActionRow:
    "stewardActionRow min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  stewardChecklist:
    "stewardChecklist min-w-0",
  stewardGrid:
    "stewardGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  stewardMetric:
    "stewardMetric min-w-0 [&_small]:hidden",
  stewardMission:
    "stewardMission min-w-0 [&_small]:hidden",
  stewardRecommendationHeader:
    "stewardRecommendationHeader min-w-0 flex flex-wrap items-center gap-1.5",
  stewardRecommendationRow:
    "stewardRecommendationRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  stewardRecommendations:
    "stewardRecommendations min-w-0 hidden",
  stewardStageCard:
    "stewardStageCard min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  stewardStageGrid:
    "stewardStageGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  stewardToolRows:
    "stewardToolRows min-w-0 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  stewardWorkbench:
    "stewardWorkbench min-w-0 hidden",
} as const;

export default styles;
