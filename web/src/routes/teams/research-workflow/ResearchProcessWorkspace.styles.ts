export default {
  detailNavigation: "flex shrink-0 flex-wrap gap-1 border-b border-[var(--vui-border-subtle)] p-2",
  host: "flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden",
  toolbar: "!flex-nowrap overflow-hidden",
  stageNavigator: "h-full min-h-0",
  canvas: "!border-0 !rounded-none !h-full min-h-0",
  archive: "h-full min-h-0 overflow-auto bg-[var(--surface-canvas)]",
  inspector: "!rounded-none !h-full min-h-0 !border-y-0 !border-r-0 border-l border-[var(--vui-border-subtle)]",
  page: "h-full min-h-0 w-full max-w-full flex-1 overflow-hidden",
} as const;
