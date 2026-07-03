const flowTabsClass = [
  "grid w-full min-w-0 flex-[1_1_auto] grid-cols-[repeat(4,minmax(118px,1fr))] gap-1 rounded-md border border-vui-border-soft",
  "max-w-none bg-[var(--surface-panel-muted)] p-[2px]",
  "max-[1120px]:grid-cols-[repeat(4,minmax(96px,1fr))]",
  "max-[760px]:min-w-0 max-[760px]:flex-[1_1_1px] max-[760px]:grid-cols-[repeat(4,minmax(74px,1fr))]",
].join(" ");
const flowTabClass = [
  "grid min-h-[36px] min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1 rounded-[6px] border border-transparent",
  "bg-transparent p-[4px_6px] text-left font-[inherit] text-vui-fg-secondary no-underline transition-[background,border-color,color] duration-150",
  "hover:bg-vui-surface-row-hover hover:text-vui-fg-primary max-[760px]:min-h-[34px] max-[760px]:p-[3px_4px]",
].join(" ");
const flowTabActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_28%,var(--border-hairline))] bg-[color-mix(in_srgb,var(--accent-warm)_13%,transparent)] text-[var(--accent-warm-2)]";
const stepIndexClass = "inline-flex h-5 w-5 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft text-[10px] leading-none text-vui-fg-tertiary max-[760px]:hidden";
const stepIndexActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_38%,var(--border-soft))] text-[var(--accent-warm-2)]";
const stepBodyClass = "grid min-w-0 gap-0.5";
const stepLabelClass = "overflow-hidden text-ellipsis whitespace-nowrap text-[var(--vui-font-xs)] font-bold leading-tight text-vui-fg-primary";
const stepHintClass = "hidden overflow-hidden text-ellipsis whitespace-nowrap text-[var(--vui-font-xs)] leading-[1.2] text-vui-fg-tertiary";
const stepMetaClass = "flex min-w-0 gap-1 text-[var(--vui-font-xs)] leading-[1.2] text-vui-fg-tertiary max-[760px]:hidden";
const stepMetaItemClass = "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const stepCountClass = "inline-flex h-5 min-w-6 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft bg-[var(--surface-card-muted)] px-1.5 text-[10px] font-bold leading-none text-vui-fg-secondary";

const styles = {
  flowTabsClass,
  flowTabClass,
  flowTabActiveClass,
  stepIndexClass,
  stepIndexActiveClass,
  stepBodyClass,
  stepLabelClass,
  stepHintClass,
  stepMetaClass,
  stepMetaItemClass,
  stepCountClass,
} as const;

export default styles;
