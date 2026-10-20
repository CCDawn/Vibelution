export default {
  strip: "flex min-w-0 flex-wrap items-center gap-2 px-3 py-2",
  root: "flex min-w-0 flex-col gap-4",
  section: "flex min-w-0 flex-col gap-2",
  actions: "flex flex-wrap items-center gap-2",
  caption: "break-words text-sm text-vui-fg-tertiary",
  summary: "min-w-0 break-words text-sm",
  list: "list-inside list-disc space-y-1 text-sm",
  rows: "grid grid-cols-1 gap-2 sm:grid-cols-2",
  row: "flex min-w-0 flex-col gap-1 rounded-md bg-vui-surface px-3 py-2 text-sm",
  heading: "text-sm font-medium",
  difference: "text-sm text-vui-fg-tertiary",
  conversation: "[&_.markdownCodeBlock:has(code.language-investment-proposal)]:hidden",
} as const;
