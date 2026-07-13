const styles = {
  root: "relative flex min-w-0 items-center",
  fixedLabel: "inline-flex min-h-7 max-w-[220px] items-center truncate px-2 text-[var(--vui-font-xs)] font-medium text-[var(--fg-secondary)] max-[719px]:max-w-[132px]",
  trigger: "!min-h-7 !h-7 !w-auto !max-w-[260px] !rounded-full !border-0 !bg-transparent !px-2 !py-0 !text-[var(--vui-font-xs)] !font-medium !text-[var(--fg-secondary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)] max-[719px]:!max-w-[180px]",
  triggerModel: "min-w-0 truncate",
  triggerEffort: "shrink-0 text-[var(--fg-tertiary)]",
  menu: "absolute bottom-[calc(100%+8px)] right-0 z-[70] grid w-[min(320px,calc(100vw-24px))] gap-0.5 rounded-[14px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1.5 shadow-[var(--vui-shadow-soft)]",
  option: "!grid !min-h-11 !w-full !grid-cols-[minmax(0,1fr)_auto] !items-center !gap-3 !rounded-[10px] !border-0 !bg-transparent !px-2.5 !py-2 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] [&_[data-slot=vui-button-content]]:contents",
  optionCopy: "grid min-w-0 gap-0.5",
  optionLabel: "text-[var(--vui-font-sm)] font-medium text-[var(--fg-primary)]",
  optionDescription: "truncate text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  check: "text-[var(--accent-cool)]",
};

export default styles;
