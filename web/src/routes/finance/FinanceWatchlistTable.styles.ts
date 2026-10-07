export default {
  editor: "grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] items-end gap-3",
  field: "grid min-w-0 gap-1 text-xs text-vui-fg-tertiary",
  tags: "block max-w-full truncate text-[10px] text-vui-fg-tertiary",
  quoteTimestamp: "max-w-full break-all text-[10px] font-normal text-vui-fg-tertiary",
  quoteError: "max-w-full whitespace-normal break-words text-[10px] font-normal text-[var(--state-error)]",
  buttons: "flex items-center gap-1",
} as const;
