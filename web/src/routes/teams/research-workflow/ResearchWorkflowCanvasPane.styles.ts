export default {
  root: "relative flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden",
  error: "shrink-0 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2 [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  stage: "relative min-h-0 min-w-0 flex-1 overflow-hidden",
  canvas: "relative h-full min-h-0 w-full !rounded-none !border-0",
  loading: "h-full min-h-0",
} as const;
