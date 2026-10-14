export default {
  list: "grid min-w-0 gap-2",
  record: "grid min-w-0 gap-1.5 border-b border-vui-border-subtle pb-3 last:border-b-0 last:pb-0",
  header: "flex min-w-0 items-baseline justify-between gap-2 text-vui-xs [&>strong]:font-medium [&>time]:shrink-0 [&>time]:text-vui-fg-tertiary",
  preview: "m-0 line-clamp-3 whitespace-pre-wrap break-words text-vui-xs leading-relaxed text-vui-fg-secondary [overflow-wrap:anywhere]",
  footer: "flex min-w-0 flex-wrap items-center justify-between gap-1.5",
  source: "min-w-0 break-words text-vui-micro-11 leading-relaxed text-vui-fg-tertiary [overflow-wrap:anywhere]",
  content: "grid min-w-0 gap-4",
  body: "m-0 whitespace-pre-wrap break-words text-vui-sm leading-relaxed text-vui-fg-primary [overflow-wrap:anywhere]",
  note: "m-0 text-vui-xs leading-relaxed text-vui-fg-tertiary",
  metadata: "grid min-w-0 gap-1 text-vui-xs leading-relaxed text-vui-fg-secondary [&>p]:m-0 [overflow-wrap:anywhere]",
  sources: "grid min-w-0 gap-2 border-t border-vui-border-subtle pt-3 [&>h3]:m-0 [&>h3]:text-vui-sm [&>h3]:font-medium",
  event: "grid min-w-0 gap-1 rounded-[var(--radius-control)] border border-vui-border-subtle p-2.5 [&>strong]:text-vui-xs [&>strong]:font-medium",
} as const;
