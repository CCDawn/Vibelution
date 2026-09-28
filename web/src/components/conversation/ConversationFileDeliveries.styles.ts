export default {
  root: "my-3 grid min-w-0 gap-2",
  header: "m-0 flex min-w-0 flex-wrap items-center justify-between gap-2",
  caption: "m-0 text-vui-xs text-vui-fg-tertiary",
  diffStat: "shrink-0 font-mono text-vui-xs text-vui-fg-tertiary",
  card: "flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-vui-border-soft",
  path: "min-w-0 flex-1 break-all text-vui-sm text-vui-fg-primary",
  actions: "flex flex-wrap items-center gap-1",
  dialog: "!w-[min(96vw,72rem)]",
  dialogContent: "min-h-0 !overflow-hidden",
  preview: "h-[65dvh] min-h-0 min-w-0",
} as const;
