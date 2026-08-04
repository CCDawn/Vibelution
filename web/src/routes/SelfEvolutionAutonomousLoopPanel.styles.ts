export const selfEvolutionAutonomousLoopPanelStyles = {
  surface:
    "grid min-w-0 gap-3 rounded-[var(--radius-panel)] border-vui-border-subtle bg-vui-surface-panel p-3",
  header:
    "flex min-w-0 flex-wrap items-start justify-between gap-2 border-b border-vui-border-subtle pb-2",
  heading: "grid min-w-0 flex-1 gap-0.5",
  eyebrow:
    "[font-size:var(--vui-font-xs)] font-[780] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  title:
    "min-w-0 break-words text-[0.98rem] font-[820] leading-tight text-vui-fg-primary [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]",
  summary:
    "max-w-[88ch] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
  statusPill:
    "inline-flex shrink-0 items-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted px-2 py-1 [font-size:var(--vui-font-xs)] font-[780] text-vui-fg-secondary data-[tone=error]:border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] data-[tone=error]:bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] data-[tone=error]:text-[var(--state-error)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] data-[tone=warning]:bg-[color-mix(in_srgb,var(--state-warning)_9%,transparent)] data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] data-[tone=success]:bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)]",
  /** Compact horizontal stepper — never stretch a phase into a full-width empty bar. */
  phaseGrid:
    "flex min-w-0 flex-wrap items-stretch gap-1.5",
  phase:
    "grid min-w-[6.5rem] max-w-[9.5rem] shrink-0 grow-0 gap-0.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5",
  phaseCurrent:
    "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))]",
  phaseDone:
    "border-[color-mix(in_srgb,var(--state-success)_34%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_6%,var(--vui-surface-row))]",
  phaseInterrupted:
    "border-[color-mix(in_srgb,var(--state-error)_40%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))]",
  phasePending: "opacity-60",
  phaseLabel: "truncate [font-size:var(--vui-font-xs)] font-[780] text-vui-fg-primary",
  phaseStatus: "truncate [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  cards: "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2",
  card:
    "grid min-w-0 content-start gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-2.5",
  cardMuted: "opacity-70",
  cardHeader: "flex min-w-0 items-start justify-between gap-2",
  cardTitle: "[font-size:var(--vui-font-sm)] font-[800] text-vui-fg-primary",
  cardBody:
    "min-w-0 whitespace-pre-wrap break-words [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
  cardEmpty: "text-vui-fg-tertiary",
  list: "grid min-w-0 gap-1",
  row:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-vui-border-hairline bg-vui-surface-inset px-2 py-1.5 [font-size:var(--vui-font-xs)]",
  rowMain: "min-w-0 truncate font-medium text-vui-fg-primary",
  rowMeta: "shrink-0 text-vui-fg-tertiary",
  actions: "flex min-w-0 flex-wrap items-center gap-2",
  proof:
    "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-inset p-2",
  proofItem: "grid min-w-0 gap-0.5",
  proofLabel: "[font-size:var(--vui-font-xs)] uppercase text-vui-fg-tertiary",
  proofValue: "truncate font-mono [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-primary",
  error: "[font-size:var(--vui-font-xs)] text-[var(--state-error)]",
};
