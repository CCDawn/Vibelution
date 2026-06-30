const navClass = [
  "mx-3 mt-1.5 inline-flex min-w-0 items-center gap-[3px] rounded-[8px] border border-vui-border-subtle",
  "bg-[image:var(--vui-gradient-route-soft)] p-[3px] shadow-[var(--vui-shadow-inset-accent)]",
  "max-[720px]:w-[calc(100%-24px)] max-[720px]:justify-start max-[720px]:overflow-x-auto",
].join(" ");
const linkClass = [
  "inline-flex min-h-6 min-w-[84px] items-center justify-center whitespace-nowrap rounded-[var(--radius-control)] px-[9px]",
  "text-[var(--vui-font-xs)] font-bold text-vui-fg-secondary no-underline transition-[background,color,box-shadow] duration-150",
  "hover:bg-vui-surface-row-hover hover:text-vui-fg-primary max-[720px]:min-w-max",
].join(" ");
const linkActiveClass = [
  "bg-vui-status-info-bg text-vui-accent-cool shadow-[var(--vui-shadow-inset-accent)]",
].join(" ");

const styles = {
  navClass,
  linkClass,
  linkActiveClass,
} as const;

export default styles;
