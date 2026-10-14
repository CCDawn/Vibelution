export default {
  panel: "grid min-w-0 content-start gap-4 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 text-sm leading-6",
  notice: "flex min-w-0 items-start gap-2 text-xs leading-5 text-[var(--fg-secondary)] [&>svg]:mt-0.5 [&>svg]:shrink-0 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-1 [&_strong]:font-medium [&_span]:block",
  fields: "grid min-w-0 grid-cols-1 gap-3 [&>div]:grid [&>div]:min-w-0 [&>div]:grid-cols-[52px_minmax(0,1fr)] [&>div]:items-start [&>div]:gap-3 [&_span]:text-xs [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:font-medium [&_strong]:[overflow-wrap:anywhere]",
  issues: "grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] pt-3 text-xs text-[var(--fg-tertiary)]",
} as const;
