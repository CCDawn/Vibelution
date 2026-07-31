export const selfEvolutionAutonomousLoopPanelStyles = {
  surface:
    "grid min-w-0 gap-3 rounded-[var(--radius-panel)] border-vui-border-subtle bg-vui-surface-panel p-3",
  header:
    "flex min-w-0 flex-wrap items-start justify-between gap-2 border-b border-vui-border-subtle pb-2",
  heading: "grid min-w-0 gap-0.5",
  eyebrow:
    "text-[0.66rem] font-[780] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  title: "text-[0.98rem] font-[820] leading-tight text-vui-fg-primary",
  summary: "max-w-[88ch] text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
  phaseGrid:
    "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-1.5",
  phase:
    "grid min-w-0 gap-0.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  phaseCurrent:
    "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))]",
  phaseDone:
    "border-[color-mix(in_srgb,var(--state-success)_34%,var(--vui-border-subtle))]",
  phaseLabel: "truncate text-[var(--vui-font-xs)] font-[780] text-vui-fg-primary",
  phaseStatus: "truncate text-[0.64rem] text-vui-fg-tertiary",
  cards: "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-2",
  card:
    "grid min-w-0 content-start gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-2.5",
  cardHeader: "flex min-w-0 items-start justify-between gap-2",
  cardTitle: "text-[var(--vui-font-sm)] font-[800] text-vui-fg-primary",
  cardBody:
    "min-w-0 whitespace-pre-wrap break-words text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
  list: "grid min-w-0 gap-1",
  row:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-vui-border-hairline bg-vui-surface-inset px-2 py-1.5 text-[var(--vui-font-xs)]",
  rowMain: "min-w-0 truncate font-medium text-vui-fg-primary",
  rowMeta: "shrink-0 text-vui-fg-tertiary",
  actions: "flex min-w-0 flex-wrap items-center gap-2",
  proof:
    "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-inset p-2",
  proofItem: "grid min-w-0 gap-0.5",
  proofLabel: "text-[0.62rem] uppercase text-vui-fg-tertiary",
  proofValue: "truncate font-mono text-[var(--vui-font-xs)] font-semibold text-vui-fg-primary",
  error: "text-[var(--vui-font-xs)] text-[var(--state-error)]",
};
