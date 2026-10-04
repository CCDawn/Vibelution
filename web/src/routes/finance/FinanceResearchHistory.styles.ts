export default {
  list: "grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2",
  filters: "flex min-w-0 flex-wrap gap-3 mb-3 [&>input]:min-w-0 [&>input]:flex-1",
  statusSelect: "max-w-[210px]",
  recordContent: "flex min-w-0 w-full items-center justify-between gap-3",
  recordText: "grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-1",
  title: "text-xs font-medium truncate",
  preview: "text-xs text-[var(--fg-tertiary)] truncate",
  metadata: "shrink-0 text-right text-xs leading-5 text-[var(--fg-tertiary)]",
  record: "!h-auto !min-h-14 !w-full !max-w-full !justify-start !px-2.5 !py-2 text-left",
  selectedRecord: "!bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)]",
} as const;
