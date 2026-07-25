/**
 * Shared horizontal (row-resize) handle for workbench height splitters (Wave 5).
 */
const styles = {
  handle:
    "relative z-20 block h-3 w-full shrink-0 cursor-row-resize touch-none select-none border-0 bg-transparent p-0 outline-none "
    + "before:pointer-events-none before:absolute before:inset-x-0 before:top-1/2 before:h-px before:-translate-y-1/2 "
    + "before:bg-transparent before:opacity-0 before:transition before:content-[''] "
    + "hover:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] hover:before:opacity-100 "
    + "focus-visible:before:bg-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] focus-visible:before:opacity-100 "
    + "after:absolute after:inset-x-0 after:top-1/2 after:h-3 after:-translate-y-1/2 after:content-['']",
  handleActive:
    "before:bg-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] before:opacity-100",
} as const;

export default styles;
