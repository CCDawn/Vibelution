// Keep controls content-sized in one horizontal band (tabs | intake). On narrow
// screens stack to two rows, but never stretch into a full-width empty shell.
const controlsShellClass =
  "grid w-fit max-w-full min-w-0 shrink-0 grid-cols-[max-content_auto] items-center gap-2 justify-self-end max-[900px]:grid-cols-1 max-[900px]:justify-items-end max-[900px]:w-fit";
const flowRegionClass = "min-w-0 w-fit max-w-full shrink-0";
const modeRegionClass = "min-w-0 w-fit shrink-0 justify-self-end max-[900px]:justify-self-end";
const intakeControlClass = "inline-flex min-h-[34px] max-w-full flex-none items-center gap-1 whitespace-nowrap rounded-full border border-vui-border-soft bg-vui-surface-panel p-[3px]";
const controlLabelClass = "py-0 pl-[7px] pr-[5px] [font-size:var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:hidden";
const intakeSegmentedClass = "inline-flex gap-1";
const intakeButtonClass = [
  "min-h-[26px] rounded-full border-0 bg-transparent px-2 [font-size:var(--vui-font-xs)] text-vui-fg-secondary",
  "transition-colors duration-150 hover:bg-[color-mix(in_srgb,var(--vui-surface-row-hover)_84%,transparent)] hover:text-vui-fg-primary disabled:cursor-wait disabled:opacity-70",
].join(" ");
const intakeButtonActiveClass = "bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]";

const styles = {
  controlsShellClass,
  flowRegionClass,
  modeRegionClass,
  intakeControlClass,
  controlLabelClass,
  intakeSegmentedClass,
  intakeButtonClass,
  intakeButtonActiveClass,
} as const;

export default styles;
