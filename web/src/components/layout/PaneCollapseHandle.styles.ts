// surface-role: glass-overlay — intentional translucent collapse toggle (alpha policy glass)
const paneToggleButtonClass = [
  "absolute left-1/2 top-1/2 z-[2] !h-7 !w-7 !max-w-none !min-w-0 !aspect-auto -translate-x-1/2 -translate-y-1/2 px-0",
  "rounded-full border border-[color-mix(in_srgb,var(--vui-border-subtle)_36%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-glass)_58%,transparent)] text-vui-fg-secondary shadow-[var(--vui-shadow-hairline)] backdrop-blur-[2px]",
  "transition-[border-color,background-color,color,box-shadow,opacity] duration-150 opacity-70",
  "hover:opacity-100 hover:border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_76%,transparent)] hover:text-[var(--accent-cool)] hover:shadow-[var(--vui-shadow-soft)]",
  "focus-visible:opacity-100 focus-visible:border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] focus-visible:bg-[color-mix(in_srgb,var(--vui-control-muted)_76%,transparent)] focus-visible:text-[var(--accent-cool)] focus-visible:shadow-[var(--vui-shadow-soft)]",
  "[&_svg]:h-3 [&_svg]:w-3 [&_svg]:shrink-0",
].join(" ");

const styles = {
  paneToggleButtonClass,
  /** Keep toggle visible while the rail is being dragged. */
  paneToggleButtonActive: "opacity-100",
} as const;

export default styles;
