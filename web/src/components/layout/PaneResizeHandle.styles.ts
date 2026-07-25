/**
 * Shared vertical resize handle for left/right workbench rails.
 * Wide hit target (~12px) with a 1px visual rule that lights on hover/active.
 */
const styles = {
  handle:
    "relative z-20 h-full w-1 shrink-0 cursor-col-resize touch-none select-none border-0 bg-transparent p-0 outline-none "
    + "max-[860px]:hidden "
    + "before:pointer-events-none before:absolute before:inset-y-0 before:left-1/2 before:w-px before:-translate-x-1/2 "
    + "before:bg-transparent before:opacity-0 before:transition before:content-[''] "
    + "hover:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] hover:before:opacity-100 "
    + "focus-visible:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:before:opacity-100 "
    + "after:absolute after:inset-y-0 after:left-1/2 after:w-3 after:-translate-x-1/2 after:content-['']",
  handleActive:
    "before:bg-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] before:opacity-100",
} as const;

export default styles;
