/**
 * Shared vertical resize handle for left/right workbench rails (Wave 4B contract).
 * Wide hit target (~12px) with a 1px visual rule that lights on hover/active.
 * Placement and responsive visibility stay with the owning layout. Hiding a
 * grid child here would move adjacent panes into the separator track.
 */
const styles = {
  handle:
    "relative z-20 h-full w-1 shrink-0 cursor-col-resize touch-none select-none border-0 bg-transparent p-0 outline-none "
    + "before:pointer-events-none before:absolute before:top-[var(--pane-resize-rule-top,0px)] before:bottom-[var(--pane-resize-rule-bottom,0px)] before:left-[calc(50%_+_var(--pane-resize-rule-offset,0px))] before:w-px before:-translate-x-1/2 "
    + "before:bg-transparent before:opacity-0 before:transition before:content-[''] "
    + "hover:before:bg-[color:var(--pane-resize-rule-color,color-mix(in_srgb,var(--accent-cool)_42%,transparent))] hover:before:opacity-100 "
    + "focus-visible:before:bg-[color:var(--pane-resize-rule-color,color-mix(in_srgb,var(--accent-cool)_42%,transparent))] focus-visible:before:opacity-100 "
    + "after:absolute after:inset-y-0 after:left-[calc(50%_+_var(--pane-resize-rule-offset,0px))] after:w-3 after:-translate-x-1/2 after:content-['']",
  handleActive:
    "before:bg-[color:var(--pane-resize-rule-color,color-mix(in_srgb,var(--accent-cool)_56%,transparent))] before:opacity-100",
  /** When the rail is collapsed, hide the lit rule and use default cursor. */
  handleCollapsed:
    "cursor-default before:opacity-0 hover:before:opacity-0",
} as const;

export default styles;
