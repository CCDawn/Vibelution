/**
 * Shared VUI surface class recipes for route style maps.
 * Prefer these over re-stating border + bg + radius on every panel/row.
 */

/** Opaque product panel (section / card body). */
export const vuiOpaquePanelClass =
  "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-panel)] shadow-none";

/** Opaque inset row / tile. */
export const vuiOpaqueRowClass =
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row)]";

/** Hover wash for interactive rows. */
export const vuiOpaqueRowHoverClass =
  "hover:border-[var(--border-soft)] hover:bg-[var(--vui-surface-row-hover)]";

/** Panel + hover-capable row combo used by dense lists. */
export const vuiDenseRowClass = `${vuiOpaqueRowClass} ${vuiOpaqueRowHoverClass}`;
