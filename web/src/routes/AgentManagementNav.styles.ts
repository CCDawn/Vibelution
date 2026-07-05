const navClass = [
  "mx-3 mt-1.5 inline-flex min-w-0 items-center gap-[3px] rounded-[8px] border border-vui-border-subtle",
  "bg-[color-mix(in_srgb,var(--vui-surface-panel)_58%,transparent)] p-[3px]",
  "max-[720px]:w-[calc(100%-24px)] max-[720px]:justify-start max-[720px]:overflow-x-auto",
].join(" ");
const linkClass = [
  "inline-flex min-h-6 min-w-[84px] items-center justify-center whitespace-nowrap rounded-[var(--radius-control)] px-[9px]",
  "text-[var(--vui-font-xs)] font-bold text-vui-fg-secondary no-underline transition-[background,color,box-shadow] duration-150",
  "hover:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_84%,transparent)] hover:text-vui-fg-primary max-[720px]:min-w-max",
].join(" ");
const linkActiveClass = [
  "bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] text-vui-accent-cool",
].join(" ");

const styles = {
  navClass,
  linkClass,
  linkActiveClass,
} as const;

export default styles;
