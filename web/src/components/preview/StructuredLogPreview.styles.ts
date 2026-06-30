const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_1fr] bg-[var(--surface-panel)]";
const toolbarClass = "flex items-center justify-between gap-3 border-b border-vui-border-soft px-3 py-2.5";
const summaryClass = "inline-flex min-w-max items-center gap-2 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const summaryCountClass = "font-[var(--font-mono)] text-vui-fg-primary";
const filterGroupClass = "flex flex-wrap justify-end gap-1.5";
const filterButtonClass = "min-h-7 border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_88%,transparent)] px-2 py-1 text-[var(--vui-font-xs)] text-vui-fg-secondary";
const filterButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--border-soft))] bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--surface-raised))] text-vui-fg-primary";
const filterCountClass = "font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const listClass = "min-h-0 overflow-auto p-2.5";
const entryClass = "mt-2 grid gap-2 border-b border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_92%,var(--surface-raised))] px-[11px] py-2.5 first:mt-0";
const entryMetaClass = "flex flex-wrap items-center gap-1.5 font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const levelPillClass = "inline-flex items-center rounded-full border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_78%,transparent)] px-1.5 py-0.5 text-vui-fg-tertiary";
const levelErrorClass = "border-[color-mix(in_srgb,var(--state-error)_28%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)] text-[var(--state-error)]";
const levelWarningClass = "border-[color-mix(in_srgb,var(--state-warning)_28%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]";
const entryBodyClass = "grid min-w-0 gap-1";
const entryTitleClass = "break-words font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-primary";
const entryMessageClass = "m-0 break-words text-[var(--vui-font-xs)] leading-[1.45] text-vui-fg-secondary";
const fieldGridClass = "m-0 grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-1.5";
const fieldItemClass = "min-w-0 rounded-md border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-base)_62%,transparent)] px-[7px] py-1.5";
const fieldKeyClass = "font-[var(--font-mono)] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const fieldValueClass = "m-0 mt-[3px] whitespace-pre-wrap break-words font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.42] text-vui-fg-secondary";
const emptyClass = "grid min-h-[180px] place-items-center rounded-lg border border-dashed border-vui-border-soft text-vui-fg-tertiary";

const styles = {
  surfaceClass,
  toolbarClass,
  summaryClass,
  summaryCountClass,
  filterGroupClass,
  filterButtonClass,
  filterButtonActiveClass,
  filterCountClass,
  listClass,
  entryClass,
  entryMetaClass,
  levelPillClass,
  levelErrorClass,
  levelWarningClass,
  entryBodyClass,
  entryTitleClass,
  entryMessageClass,
  fieldGridClass,
  fieldItemClass,
  fieldKeyClass,
  fieldValueClass,
  emptyClass,
} as const;

export default styles;
