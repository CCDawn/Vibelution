const panel = "grid min-w-0 gap-2 rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle bg-vui-surface-panel p-2.5";
const header = "flex min-w-0 items-start justify-between gap-3";
const title = "flex min-w-0 items-start gap-2 [&>svg]:mt-0.5 [&>svg]:shrink-0 [&>svg]:text-[var(--accent-cool)]";
const titleCopy = "min-w-0 [&>p]:m-0 [&>p]:[font-size:var(--vui-font-xs)] [&>p]:font-extrabold [&>p]:uppercase [&>p]:tracking-[0.07em] [&>p]:text-vui-fg-tertiary [&>h3]:m-0 [&>h3]:mt-0.5 [&>h3]:text-sm [&>h3]:font-[820]";
const description = "m-0 [font-size:var(--vui-font-xs)] leading-[1.55] text-vui-fg-tertiary";
const badges = "flex min-w-0 flex-wrap gap-1.5";
const badge = "inline-flex min-h-6 min-w-0 items-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 [font-size:0.62rem] text-vui-fg-secondary";
const setupSection = "grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-border-subtle))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-row)),var(--vui-surface-row))] p-2.5";
const setupHeader = "flex min-w-0 items-start justify-between gap-2 [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&_p]:m-0 [&_p]:[font-size:0.62rem] [&_p]:font-extrabold [&_p]:uppercase [&_p]:tracking-[0.07em] [&_p]:text-vui-fg-tertiary [&_strong]:text-xs [&_strong]:text-vui-fg-primary";
const setupGrid = "grid min-w-0 grid-cols-2 gap-2 max-[760px]:grid-cols-1";
const setupHint = "m-0 [font-size:0.62rem] leading-[1.5] text-vui-fg-tertiary";
const healthSection = "grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-2.5";
const healthHeader = "flex min-w-0 items-start justify-between gap-2";
const healthKicker = "m-0 [font-size:var(--vui-font-xs)] font-extrabold uppercase tracking-[0.07em] text-vui-fg-secondary";
const healthHint = "m-0 mt-0.5 [font-size:0.62rem] leading-[1.45] text-vui-fg-tertiary";
const healthGrid = "grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 max-[760px]:grid-cols-1";
const healthRow = "grid min-w-0 grid-cols-[minmax(0,0.7fr)_minmax(0,1fr)] items-start gap-2 border-t border-vui-border-subtle pt-1.5 first:border-t-0 first:pt-0 [&>dt]:min-w-0 [&>dt]:[font-size:0.62rem] [&>dt]:font-bold [&>dt]:leading-[1.35] [&>dt]:text-vui-fg-tertiary [&>dd]:m-0 [&>dd]:grid [&>dd]:min-w-0 [&>dd]:gap-0.5";
const healthMeta = "min-w-0 truncate [font-size:0.6rem] leading-[1.35] text-vui-fg-tertiary";
const healthError = "m-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-2 py-1.5 [font-size:0.62rem] leading-[1.45] text-[var(--state-error)]";
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
  setupSection,
  setupHeader,
  setupGrid,
  setupHint,
  healthSection,
  healthHeader,
  healthKicker,
  healthHint,
  healthGrid,
  healthRow,
  healthMeta,
  healthError,
  grid,
  field,
  fieldWide,
  quietHours,
  actions,
  notice,
  state,
} as const;
