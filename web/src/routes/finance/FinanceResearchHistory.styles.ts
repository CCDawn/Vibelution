export default {
  list: "grid min-w-0 gap-2",
  filters: "flex gap-3 mb-3",
  statusSelect: "max-w-[170px]",
  recordContent: "flex min-w-0 w-full items-center justify-between gap-3",
  recordText: "grid min-w-0 gap-1",
  title: "text-xs font-medium truncate",
  preview: "text-xs text-[var(--fg-tertiary)] truncate",
  metadata: "shrink-0 text-right text-xs leading-5 text-[var(--fg-tertiary)]",
  record: "!h-auto !min-h-14 !w-full !max-w-full !justify-start !px-2.5 !py-2 text-left",
  selectedRecord: "!bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)]",
} as const;
