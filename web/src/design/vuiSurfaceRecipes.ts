/**
 * Shared VUI surface class recipes for route style maps.
 * Prefer these over re-stating border + bg + radius on every panel/row.
 */

/** Opaque product panel (section / card body) without elevation opinion. */
export const vuiOpaquePanelClass =
  "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)]";

/** Dense ops / flat boards — no elevation wash. */
export const vuiFlatPanelClass = `${vuiOpaquePanelClass} shadow-none`;

/** Elevated product panel (settings workbench, overview cards). */
export const vuiElevatedPanelClass =
  `${vuiOpaquePanelClass} shadow-[var(--vui-elevation-1)]`;

/** Opaque inset row / tile. */
export const vuiOpaqueRowClass =
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row)]";

/** Hover wash for interactive rows. */
export const vuiOpaqueRowHoverClass =
  "hover:border-[var(--border-soft)] hover:bg-[var(--vui-surface-row-hover)]";

/** Panel + hover-capable row combo used by dense lists. */
export const vuiDenseRowClass = `${vuiOpaqueRowClass} ${vuiOpaqueRowHoverClass}`;

/**
 * Glass / overlay panel — only for temporary layers (dialogs, popovers, notices).
 * Structural product boards should use flat/elevated opaque panels instead.
 */
export const vuiGlassPanelClass =
  "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)]";
