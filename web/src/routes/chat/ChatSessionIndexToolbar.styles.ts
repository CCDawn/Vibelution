const styles = {
  root: "flex min-w-0 shrink-0 items-center gap-1 px-3 pt-2 pb-2",
  title: "min-w-0 flex-1 truncate [font-size:var(--vui-type-control-size)] font-medium text-[var(--fg-primary)]",
  icon: "!size-8 !min-h-8 !min-w-8 !border-0 !bg-transparent !bg-none text-[var(--fg-secondary)] shadow-none hover:!bg-[var(--vui-control-muted-hover)] [@media(pointer:coarse)]:!size-11 [@media(pointer:coarse)]:!min-h-11 [@media(pointer:coarse)]:!min-w-11",
  create: "shrink-0 !h-8 !min-h-8 !gap-1 !px-2 !bg-none !bg-[var(--fg-primary)] !text-[var(--vui-surface-panel)] [@media(pointer:coarse)]:!h-11 [@media(pointer:coarse)]:!min-h-11",
  back: "shrink-0 !h-8 !min-h-8 !gap-1 !px-1 !border-0 !bg-transparent !bg-none shadow-none",
  collapse: "ml-1 shrink-0",
  options: "grid w-60 gap-1 p-2",
  archive: "w-full justify-start !border-0 !bg-transparent !bg-none shadow-none",
  divider: "my-1 border-t border-[var(--vui-border-subtle)]",
  optionLabel: "px-2 pt-1 [font-size:var(--vui-type-caption-size)] text-[var(--fg-secondary)]",
  radio: "flex min-h-9 items-center gap-2 rounded-[var(--radius-control)] px-2 [font-size:var(--vui-type-control-size)] hover:bg-[var(--vui-control-muted-hover)] [@media(pointer:coarse)]:min-h-11",
  grouping: "px-2 py-1",
} as const;
export default styles;
