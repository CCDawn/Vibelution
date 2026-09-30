export const memoryGraphCatalogStyles = {
  card: "col-span-full min-h-0 content-start !justify-items-stretch !text-left",
  content: "grid w-full min-w-0 gap-3",
  canvas: "h-[30rem] min-h-0 w-full min-w-0 overflow-hidden",
  selection: "flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-3 text-vui-xs leading-5 text-[var(--fg-secondary)]",
  sampleLabel: "text-vui-2xs leading-4 text-[var(--fg-tertiary)]",
} as const;
