export const memoryGraphCatalogStyles = {
  card: "col-span-full min-h-0 content-start !justify-items-stretch !text-left",
  content: "grid w-full min-w-0 gap-3",
  canvas: "h-[30rem] min-h-0 w-full min-w-0 overflow-hidden",
  selection: "flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-3 text-sm text-[var(--fg-secondary)]",
  sampleLabel: "text-xs text-[var(--fg-tertiary)]",
} as const;
