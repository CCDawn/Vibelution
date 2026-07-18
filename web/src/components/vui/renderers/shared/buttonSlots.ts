/** Shared visual slots for VButton — renderer-agnostic Tailwind contracts. */

export const vuiButtonBaseClass =
  "border border-vui-border-subtle bg-vui-control-muted text-vui-fg-secondary shadow-none";

export const vuiButtonHoverClass =
  "transition-colors duration-150 hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] hover:shadow-[var(--vui-control-hover-shadow)]";

export const vuiButtonPrimaryClass =
  "border-vui-accent-cool bg-vui-surface-panel text-vui-fg-primary";

export const vuiButtonDangerClass =
  "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)]";

export const vuiButtonFocusClass =
  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]";

export const vuiButtonDisabledClass =
  "disabled:cursor-default disabled:opacity-55 disabled:pointer-events-none";
