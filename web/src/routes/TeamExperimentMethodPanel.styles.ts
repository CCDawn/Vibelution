const styles = {
  panel:
    "min-w-0 grid gap-3 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_4%,var(--vui-surface-panel))] p-3",
  header:
    "min-w-0 flex flex-wrap items-start justify-between gap-2 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_strong]:text-[var(--vui-font-sm)] [&_span]:text-[var(--vui-font-xs)] [&_span]:leading-[var(--vui-line-readable)] [&_span]:text-[var(--fg-secondary)]",
  sourceBadge:
    "inline-flex min-h-6 w-fit shrink-0 items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  section:
    "min-w-0 grid gap-1.5 [&>span]:text-[var(--vui-font-xs)] [&>span]:font-semibold [&>span]:text-[var(--fg-secondary)]",
  segmented:
    "min-w-0 flex flex-wrap gap-1 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] p-1",
  segment:
    "min-h-8 w-fit rounded-[calc(var(--radius-control)-2px)] border border-transparent px-2.5 text-[var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] transition-colors hover:bg-[var(--vui-surface-panel)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent-cool)] disabled:cursor-not-allowed disabled:opacity-55",
  segmentActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_32%,var(--vui-border-subtle))] bg-[var(--vui-surface-panel)] text-[var(--accent-cool)] shadow-[var(--vui-shadow-inset-accent)]",
  methodGrid:
    "min-w-0 grid grid-cols-[repeat(3,minmax(0,1fr))] gap-1 max-[860px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[560px]:grid-cols-[minmax(0,1fr)]",
  methodButton:
    "min-h-10 min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-1.5 text-left text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[color-mix(in_srgb,var(--accent-cool)_34%,var(--vui-border-subtle))] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent-cool)] disabled:cursor-not-allowed disabled:opacity-55",
  methodButtonActive:
    "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--fg-primary)] shadow-[var(--vui-shadow-inset-accent)]",
  selectionRow:
    "min-w-0 grid grid-cols-[minmax(12rem,0.8fr)_minmax(0,1.2fr)] gap-2 max-[720px]:grid-cols-[minmax(0,1fr)]",
  field:
    "min-w-0 grid content-start gap-1 text-[var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  fieldWide:
    "min-w-0 grid content-start gap-1 text-[var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)] [&_input]:w-full [&_select]:w-full [&_textarea]:w-full md:col-span-2",
  adapterStatus:
    "min-w-0 flex flex-wrap items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-2 text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_strong]:text-[var(--fg-primary)]",
  adapterStatusReady:
    "border-[color-mix(in_srgb,var(--state-success)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_7%,var(--vui-surface-row))]",
  adapterStatusBlocked:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_7%,var(--vui-surface-row))]",
  recommendation:
    "min-w-0 grid gap-1 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-row))] px-2.5 py-2 text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_strong]:text-[var(--fg-primary)]",
  form:
    "min-w-0 grid min-h-[18rem] grid-cols-[repeat(2,minmax(0,1fr))] content-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2.5 max-[720px]:grid-cols-[minmax(0,1fr)] max-[720px]:[&>label]:col-span-1",
  criteria:
    "min-w-0 grid grid-cols-[repeat(3,minmax(0,1fr))] gap-2 max-[860px]:grid-cols-[minmax(0,1fr)]",
  actions:
    "min-w-0 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-2 [&>span]:min-w-0 [&>span]:text-[var(--vui-font-xs)] [&>span]:leading-[var(--vui-line-readable)] [&>span]:text-[var(--fg-tertiary)]",
  primaryAction:
    "min-h-9 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_36%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-panel))] px-3 text-[var(--vui-font-sm)] font-semibold text-[var(--fg-primary)] hover:bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-surface-panel))] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent-cool)] disabled:cursor-not-allowed disabled:opacity-55",
  loading:
    "min-h-[16rem] min-w-0 animate-pulse rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  error:
    "min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-2.5 py-2 text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--state-error)]",
} as const;

export default styles;
