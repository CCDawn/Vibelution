const styles = {
  root: "relative flex min-w-0 items-center gap-1",
  trigger: "!min-h-7 !h-7 !w-auto !max-w-[220px] !rounded-full !border !border-[var(--vui-border-subtle)] !bg-transparent !px-2 !py-0 !text-[var(--vui-font-xs)] !font-medium !text-[var(--fg-secondary)] !shadow-none hover:!bg-[var(--vui-control-muted)] hover:!text-[var(--fg-primary)]",
  triggerLabel: "min-w-0 truncate",
  panel: "absolute bottom-[calc(100%+8px)] left-0 z-[70] grid w-[min(420px,calc(100vw-32px))] gap-1 rounded-[14px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1.5 shadow-[var(--vui-shadow-soft)]",
  panelHeader: "flex min-h-8 items-center justify-between gap-2 px-2 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  backButton: "!min-h-7 !h-7 !w-7 !min-w-7 !rounded-full !border-0 !bg-transparent !p-0 !text-[var(--fg-secondary)] !shadow-none hover:!bg-[var(--vui-control-muted)]",
  list: "grid max-h-[min(420px,60vh)] gap-0.5 overflow-y-auto",
  option: "!grid !min-h-12 !w-full !grid-cols-[minmax(0,1fr)_auto] !items-center !gap-3 !rounded-[10px] !border-0 !bg-transparent !px-2.5 !py-2 !text-left !shadow-none hover:!bg-[var(--vui-control-muted)] [&_[data-slot=vui-button-content]]:contents",
  optionCopy: "grid min-w-0 gap-0.5",
  optionTitle: "flex min-w-0 items-center gap-1.5 text-[var(--vui-font-sm)] font-medium text-[var(--fg-primary)]",
  optionMeta: "truncate text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  badge: "rounded-full border border-[var(--vui-border-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--fg-tertiary)]",
  check: "text-[var(--accent-cool)]",
  unavailable: "opacity-55",
  empty: "px-3 py-5 text-center text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
};

export default styles;
