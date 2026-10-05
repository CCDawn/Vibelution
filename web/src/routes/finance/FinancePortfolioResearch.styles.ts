const border = "border-vui-border-hairline";
const muted = "text-vui-fg-tertiary";

export default {
  page: "grid min-h-0 min-w-0 content-start gap-3 overflow-y-auto overflow-x-hidden p-3 text-vui-fg-primary",
  header: `flex min-w-0 flex-wrap items-center justify-between gap-3 border-b ${border} pb-2`,
  titleGroup: "grid min-w-0 gap-0.5",
  title: "m-0 text-sm font-semibold",
  meta: `min-w-0 break-words text-[11px] ${muted}`,
  actions: "flex min-w-0 flex-wrap items-center gap-2",
  workspace: "grid min-w-0 grid-cols-[minmax(0,1.2fr)_minmax(21rem,0.8fr)] items-start gap-3",
  panel: "grid min-w-0 content-start gap-2 overflow-hidden",
  panelHeader: "flex min-w-0 flex-wrap items-center justify-between gap-2",
  panelTitle: "m-0 text-xs font-semibold",
  helper: `m-0 break-words text-[11px] leading-5 ${muted}`,
  stockButton: "!h-auto !min-h-0 !max-w-full !justify-start !px-0.5 !py-0.5 text-left",
  stockIdentity: "grid min-w-0 gap-0.5 text-left [&>strong]:truncate [&>strong]:text-xs [&>small]:font-mono [&>small]:text-[10px] [&>small]:text-vui-fg-tertiary",
  smallButton: "!h-7 !min-h-7 !px-2 !text-[11px]",
  seriesStatus: `block min-w-0 break-words text-[11px] ${muted}`,
  pairNames: "block min-w-0 break-words text-xs [&_small]:font-mono [&_small]:text-[10px] [&_small]:text-vui-fg-tertiary",
  coverage: `flex min-w-0 flex-wrap gap-x-3 gap-y-1 border-t ${border} pt-2 text-[11px] ${muted}`,
  provenance: `flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-t ${border} pt-2 text-[10px] ${muted} [&>a]:text-vui-accent-cool [&>a]:underline-offset-2 [&>a:hover]:underline`,
} as const;
