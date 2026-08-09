export default {
  question: "h-full min-h-0 overflow-auto",
  fill: "h-full min-h-0",
  errorSurface: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  error: "rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs text-[var(--state-error)]",
  centered: "flex h-full min-h-0 flex-col items-stretch justify-center p-3",
  empty: "h-auto w-full border-0 bg-transparent",
} as const;
