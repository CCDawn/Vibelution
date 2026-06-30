const intakeControlClass = "inline-flex min-h-[34px] flex-none items-center gap-1 whitespace-nowrap rounded-full border border-vui-border-soft bg-vui-surface-panel p-[3px]";
const controlLabelClass = "py-0 pl-[7px] pr-[5px] text-[var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:hidden";
const intakeSegmentedClass = "inline-flex gap-1";
const intakeButtonClass = [
  "min-h-[26px] rounded-full border-0 bg-transparent px-2 text-[var(--vui-font-xs)] text-vui-fg-secondary",
  "transition-colors duration-150 hover:bg-vui-surface-row-hover hover:text-vui-fg-primary disabled:cursor-wait disabled:opacity-70",
].join(" ");
const intakeButtonActiveClass = "bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]";

const styles = {
  intakeControlClass,
  controlLabelClass,
  intakeSegmentedClass,
  intakeButtonClass,
  intakeButtonActiveClass,
} as const;

export default styles;
