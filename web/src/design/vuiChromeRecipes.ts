/**
 * Shared VUI control-chrome class recipes for style maps (Wave 3 density).
 * Prefer these over re-stating height + muted control fill on every quiet button.
 *
 * Must stay string-literal complete: this file is a Tailwind @source.
 * Prefer VButton / VNativeButton in new TSX; style maps use these for legacy chrome.
 */

/** Quiet compact control (secondary/ghost toolbar button look). */
export const vuiControlQuietClass =
  "inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55";

/**
 * Same chrome without leading inline-flex — for maps that already set flex/grid
 * on the same node (e.g. AppShell actionButton with flex-wrap).
 */
export const vuiControlQuietChromeClass =
  "min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55";

/** Square compact icon control geometry (pair with border/bg as needed). */
export const vuiControlIconSmClass =
  "inline-flex h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] shrink-0 items-center justify-center rounded-[var(--radius-control)]";

/** Compact pill chip shell (status / meta chips). */
export const vuiControlPillClass =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]";
