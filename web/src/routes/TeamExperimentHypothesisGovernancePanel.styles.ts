const styles = {
  panel:
    "grid gap-3 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3",
  header:
    "flex items-start justify-between gap-3",
  headingGroup:
    "grid gap-1",
  title:
    "[font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  subtitle:
    "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  guardBadge:
    "inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--vui-border-subtle)] px-2 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  draftGrid:
    "grid grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)] gap-3 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3 max-[900px]:grid-cols-[minmax(0,1fr)]",
  draftIntro:
    "grid content-start gap-2",
  sectionLabel:
    "[font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  helper:
    "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  draftFields:
    "grid gap-2",
  actionRow:
    "flex justify-end",
  candidateGrid:
    "grid grid-cols-2 gap-3 max-[900px]:grid-cols-[minmax(0,1fr)]",
  candidateCard:
    "grid content-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3",
  candidateHeader:
    "flex items-center justify-between gap-2",
  candidateTitle:
    "min-w-0 truncate [font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  statusBadge:
    "shrink-0 rounded-full border border-[var(--vui-border-subtle)] px-2 py-0.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  hypothesis:
    "m-0 [font-size:var(--vui-font-sm)] leading-6 text-[var(--fg-primary)]",
  claimBoundary:
    "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-panel))] px-2 py-1.5 [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]",
  metadata:
    "[font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  candidateActions:
    "mt-auto flex items-center justify-end gap-2 pt-1",
  selected:
    "inline-flex items-center gap-1 [font-size:var(--vui-font-xs)] text-[var(--state-success)]",
  approvalNote:
    "text-right [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  empty:
    "col-span-2 [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)] max-[900px]:col-span-1",
  alert:
    "m-0 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
} as const;

export default styles;
