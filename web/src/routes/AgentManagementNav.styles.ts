const navClass = [
  "inline-flex h-full min-w-0 items-stretch gap-6 overflow-x-auto",
  "max-[720px]:gap-4",
].join(" ");
const linkClass = [
  "inline-flex min-w-max items-center justify-center whitespace-nowrap border-b-2 border-transparent px-0.5",
  "[font-size:var(--vui-font-sm)] font-semibold text-vui-fg-secondary no-underline transition-[border-color,color] duration-150",
  "hover:border-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)] hover:text-vui-fg-primary",
].join(" ");
const linkActiveClass = [
  "!border-vui-accent-cool text-vui-accent-cool",
].join(" ");

const styles = {
  navClass,
  linkClass,
  linkActiveClass,
} as const;

export default styles;
