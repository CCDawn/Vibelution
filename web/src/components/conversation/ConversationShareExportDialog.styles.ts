/**
 * Share/export dialog (local self-contained HTML export, intentional deviation
 * from ZCode's cloud share). Visual utilities live in this styles module:
 * product TSX must stay free of inline Tailwind strings (vuiImportBoundary).
 */
export default {
  dialog: "!w-[min(96vw,44rem)]",
  body: "grid min-w-0 gap-2",
  controls: "flex min-w-0 flex-wrap items-center gap-4",
  list: "m-0 grid max-h-[46dvh] min-w-0 list-none gap-2 overflow-y-auto p-0",
  row: "flex min-w-0 items-start gap-2 rounded-xl border border-vui-border-soft p-2",
  rowBody: "grid min-w-0 flex-1 gap-0.5",
  rowHead: "flex min-w-0 flex-wrap items-center gap-2",
  turnLabel: "shrink-0 text-vui-sm font-medium text-vui-fg-primary",
  timestamp: "shrink-0 text-vui-xs text-vui-fg-tertiary",
  preview: "m-0 min-w-0 truncate text-vui-xs text-vui-fg-secondary",
  previewAssistant: "m-0 min-w-0 truncate text-vui-xs text-vui-fg-tertiary",
  status: "m-0 text-vui-sm text-vui-fg-secondary",
  error: "m-0 text-vui-sm text-[var(--state-error)]",
  result: "m-0 text-vui-sm text-vui-fg-secondary",
  empty: "m-0 text-vui-sm text-vui-fg-tertiary",
  footer: "flex flex-wrap items-center justify-end gap-2",
} as const;
