const flowTabsClass = [
  "inline-grid w-fit min-w-0 max-w-full grid-cols-[repeat(4,minmax(132px,168px))] gap-1 rounded-md border border-vui-border-soft",
  "bg-vui-surface-toolbar p-[2px]",
  "max-[1120px]:grid-cols-[repeat(4,minmax(112px,150px))]",
  "max-[760px]:w-full max-[760px]:grid-cols-[repeat(4,minmax(74px,1fr))]",
].join(" ");
const flowTabClass = [
  "!inline-grid h-[34px] min-h-[34px] max-h-[34px] min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1 overflow-hidden rounded-[6px] border border-transparent",
  "bg-transparent p-[4px_6px] text-left font-[inherit] text-vui-fg-secondary no-underline transition-[background,border-color,color] duration-150",
  "hover:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_84%,transparent)] hover:text-vui-fg-primary max-[760px]:p-[3px_4px]",
  "[&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
].join(" ");
const flowTabActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_13%,var(--vui-surface-row))] text-[var(--accent-warm-2)]";
const stepIndexClass = "inline-flex h-5 w-5 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft text-[10px] leading-none text-vui-fg-tertiary max-[760px]:hidden";
const stepIndexActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_38%,var(--border-soft))] text-[var(--accent-warm-2)]";
const stepBodyClass = "grid min-w-0 gap-0";
const stepLabelClass = "overflow-hidden text-ellipsis whitespace-nowrap text-[var(--vui-font-xs)] font-bold leading-tight text-vui-fg-primary";
const stepHintClass = "hidden overflow-hidden text-ellipsis whitespace-nowrap text-[var(--vui-font-xs)] leading-[1.2] text-vui-fg-tertiary";
const stepMetaClass = "sr-only";
const stepMetaItemClass = "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap";
const stepCountClass = "inline-flex h-5 min-w-6 items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft bg-vui-control-muted px-1.5 text-[10px] font-bold leading-none text-vui-fg-secondary";

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
