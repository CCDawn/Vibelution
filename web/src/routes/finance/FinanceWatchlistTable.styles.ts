export default {
  editor: "grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] items-end gap-3",
  field: "grid min-w-0 gap-1 text-xs text-vui-fg-tertiary",
  stockBadge: "shrink-0 font-mono text-[11px] font-normal leading-4 text-vui-fg-tertiary",
  quoteErrorIcon: "inline-flex shrink-0 items-center text-[var(--state-error)] align-middle",
  tags: "flex min-w-0 max-w-full items-center gap-1 overflow-hidden",
  tagChip: "inline-block max-w-[4.5rem] shrink-0 truncate rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-control-muted px-1.5 py-px text-[11px] leading-4 text-vui-fg-secondary",
  tagOverflow: "shrink-0 text-[11px] leading-4 text-vui-fg-tertiary",
  changePill: "inline-block rounded-[var(--radius-control)] px-1.5 py-0.5 font-mono text-xs font-semibold tabular-nums",
  changePillUp: "bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] text-[var(--state-error)]",
  changePillDown: "bg-[color-mix(in_srgb,var(--state-success)_10%,transparent)] text-[var(--state-success)]",
  tableFooter: "mt-2 text-right text-xs text-vui-fg-tertiary",
  buttons: "flex items-center gap-1",
} as const;
