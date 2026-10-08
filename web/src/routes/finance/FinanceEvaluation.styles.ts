export default {
  page: "grid min-w-0 content-start gap-3 p-3 text-vui-fg-primary",
  row: "flex min-w-0 flex-wrap items-center gap-2 [&_button]:whitespace-nowrap",
  title: "m-0 min-w-0 truncate text-sm font-semibold",
  field: "flex min-w-0 items-center gap-2 whitespace-nowrap text-xs [&_input]:w-32",
  note: "m-0 text-[11px] leading-5 text-vui-fg-tertiary",
  panel: "grid min-w-0 gap-3",
  table: "min-w-0 overflow-x-auto",
  chart: "h-44 w-full text-vui-accent-cool",
  status: "text-xs font-medium",
  claim: "m-0 break-words text-xs",
} as const;
