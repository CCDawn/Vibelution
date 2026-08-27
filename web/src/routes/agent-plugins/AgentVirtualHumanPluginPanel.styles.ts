const panel = "grid min-w-0 gap-2 rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle bg-vui-surface-panel p-2.5";
const header = "flex min-w-0 items-start justify-between gap-3";
const title = "flex min-w-0 items-start gap-2 [&>svg]:mt-0.5 [&>svg]:shrink-0 [&>svg]:text-[var(--accent-cool)]";
const titleCopy = "min-w-0 [&>p]:m-0 [&>p]:[font-size:var(--vui-font-xs)] [&>p]:font-extrabold [&>p]:uppercase [&>p]:tracking-[0.07em] [&>p]:text-vui-fg-tertiary [&>h3]:m-0 [&>h3]:mt-0.5 [&>h3]:text-sm [&>h3]:font-[820]";
const description = "m-0 [font-size:var(--vui-font-xs)] leading-[1.55] text-vui-fg-tertiary";
const badges = "flex min-w-0 flex-wrap gap-1.5";
const badge = "inline-flex min-h-6 min-w-0 items-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 [font-size:0.62rem] text-vui-fg-secondary";
const grid = "grid min-w-0 grid-cols-2 gap-2 max-[760px]:grid-cols-1";
const field = "grid min-w-0 gap-1 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-bold [&>span]:text-vui-fg-secondary";
const fieldWide = `${field} col-span-2 max-[760px]:col-span-1`;
const quietHours = "grid min-w-0 grid-cols-2 gap-2";
const actions = "flex min-w-0 flex-wrap items-center justify-end gap-2 border-t border-vui-border-subtle pt-2";
const notice = "m-0 min-w-0 [font-size:var(--vui-font-xs)] leading-[1.45] text-vui-fg-secondary";
const state = "!rounded-[var(--radius-control)]";

export default {
  panel,
  header,
  title,
  titleCopy,
  description,
  badges,
  badge,
  grid,
  field,
  fieldWide,
  quietHours,
  actions,
  notice,
  state,
} as const;
