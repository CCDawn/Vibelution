export default {
  panel: "grid min-w-0 content-start gap-3 p-1 text-vui-xs leading-6",
  identity: "flex min-w-0 flex-wrap items-start justify-between gap-2 [&>h3]:m-0 [&>h3]:min-w-0 [&>h3]:font-medium [&>h3]:text-vui-sm [&>h3]:[overflow-wrap:anywhere]",
  notice: "flex min-w-0 items-start gap-2 text-vui-2xs leading-5 text-[var(--fg-secondary)] [&>svg]:mt-0.5 [&>svg]:shrink-0 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-1 [&_strong]:font-medium [&_span]:block",
  fields: "grid min-w-0 grid-cols-1 gap-3 [&>div]:grid [&>div]:min-w-0 [&>div]:grid-cols-[52px_minmax(0,1fr)] [&>div]:items-start [&>div]:gap-3 [&_span]:text-vui-2xs [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:font-medium [&_strong]:[overflow-wrap:anywhere]",
  issues: "grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] pt-3 text-vui-2xs text-[var(--fg-tertiary)]",
} as const;
