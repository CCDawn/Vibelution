const styles = {
  body: "grid min-w-0 gap-0 p-1",
  heading: "flex h-8 items-center gap-1 px-2 text-vui-xs font-medium text-[var(--fg-tertiary)]",
  row: "!flex !h-[38px] !min-h-[38px] !w-full !items-center !justify-start !gap-2.5 !rounded-md !border-0 !bg-transparent !px-2 !text-vui-xs !font-normal !shadow-none hover:!bg-[var(--bg-active)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:flex [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2.5",
  label: "min-w-0 flex-1 text-left",
  value: "text-vui-xs text-[var(--fg-tertiary)]",
  back: "!size-6 !min-h-6 !min-w-6 !p-0",
  divider: "mx-2 my-1.5 border-t border-[var(--vui-border-subtle)]",
  hint: "mx-2 mb-2 mt-1 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]",
} as const;
export default styles;
