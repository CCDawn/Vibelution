const paneHandleClass = "relative";
const paneToggleButtonClass = [
  "absolute left-1/2 top-1/2 z-[2] h-10 w-6 min-w-0 -translate-x-1/2 -translate-y-1/2 px-0",
  "rounded-[8px] border-vui-border-subtle bg-vui-surface-glass text-vui-fg-secondary shadow-[var(--vui-shadow-soft)]",
  "transition-[border-color,background-color,color,box-shadow] duration-150",
  "hover:border-vui-accent-warm hover:bg-vui-control-muted hover:text-[var(--accent-warm-2)] hover:shadow-[var(--vui-shadow-accent)]",
  "focus-visible:border-vui-accent-warm focus-visible:bg-vui-control-muted focus-visible:text-[var(--accent-warm-2)] focus-visible:shadow-[var(--vui-shadow-accent)]",
  "[&_svg]:shrink-0",
].join(" ");

const styles = {
  paneHandleClass,
  paneToggleButtonClass,
} as const;

export default styles;
