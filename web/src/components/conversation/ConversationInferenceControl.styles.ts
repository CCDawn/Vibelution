const styles = {
  root: "relative flex min-w-0 items-center",
  fixedLabel: "inline-flex min-h-7 max-w-[220px] items-center truncate px-1.5 [font-size:var(--vui-font-xs)] font-medium tracking-[-0.01em] text-[var(--fg-tertiary)] max-[719px]:max-w-[132px]",
  trigger: "!inline-flex !min-h-7 !h-7 !w-auto !max-w-[260px] !items-center !gap-1 !rounded-full !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-xs)] !font-medium !tracking-[-0.01em] !text-[var(--fg-tertiary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] max-[719px]:!max-w-[180px]",
  triggerModel: "min-w-0 truncate",
  triggerSeparator: "shrink-0 opacity-55",
  triggerEffort: "shrink-0 text-[var(--fg-secondary)]",
  triggerChevron: "shrink-0 opacity-70",
  menu: "absolute bottom-[calc(100%+8px)] right-0 z-[70] grid w-[min(288px,calc(100vw-24px))] gap-0.5 rounded-[12px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-[var(--vui-shadow-soft)]",
  option: "!grid !h-auto !min-h-12 !w-full !grid-cols-[minmax(0,1fr)_auto] !items-center !gap-2 !rounded-[9px] !border-0 !bg-transparent !px-2.5 !py-1.5 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)]",
  optionCopy: "grid min-w-0 gap-0.5",
  optionLabel: "[font-size:var(--vui-font-sm)] font-medium text-[var(--fg-primary)]",
  optionDescription: "truncate [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  check: "text-[var(--accent-cool)]",
};

export default styles;
