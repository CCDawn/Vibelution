/**
 * Shared VUI surface class recipes for route style maps.
 * Prefer these over re-stating border + bg + radius on every panel/row.
 *
 * IMPORTANT: This file is a Tailwind @source. Class strings here must stay as
 * complete string literals (not built only via non-scanned indirection) so
 * utilities are emitted. Prefer theme utilities (`bg-vui-surface-*`) for fills.
 */

/** Opaque product panel (section / card body) without elevation opinion. */
export const vuiOpaquePanelClass =
  "rounded-[var(--radius-panel)] border border-vui-border-subtle !bg-vui-surface-panel";

/** Dense ops / flat boards — no elevation wash. */
export const vuiFlatPanelClass = `${vuiOpaquePanelClass} shadow-none`;

/** Elevated product panel (settings workbench, overview cards). */
export const vuiElevatedPanelClass =
  `${vuiOpaquePanelClass} shadow-[var(--vui-elevation-1)]`;

/** Opaque inset row / tile. */
export const vuiOpaqueRowClass =
  "rounded-[var(--radius-control)] border border-vui-border-subtle !bg-vui-surface-row";

/** Hover wash for interactive rows. */
export const vuiOpaqueRowHoverClass =
  "hover:border-[var(--border-soft)] hover:bg-vui-surface-row-hover";

/** Panel + hover-capable row combo used by dense lists. */
export const vuiDenseRowClass = `${vuiOpaqueRowClass} ${vuiOpaqueRowHoverClass}`;

/**
 * Glass / overlay panel — only for temporary layers (dialogs, popovers, notices).
 * Structural product boards should use flat/elevated opaque panels instead.
 */
export const vuiGlassPanelClass =
  "rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass shadow-[var(--vui-shadow-hairline)]";

/** Workspace fill for page bodies, code panes, and shell canvases. */
export const vuiWorkspaceFillClass = "!bg-vui-surface-workspace";

/** Primary chrome rail fill (left/right shell columns). */
export const vuiRailFillClass = "!bg-vui-surface-rail";

/** Toolbar / module-bar strip fill. */
export const vuiToolbarFillClass = "!bg-vui-surface-toolbar";

/** Inset region fill (inspector wells, nested shell pockets). */
export const vuiInsetFillClass = "!bg-vui-surface-inset";

/** Chat center conversation board fill (opaque product surface). */
export const vuiChatFillClass = "!bg-vui-surface-chat";

// ─── State tints (fixed alpha; do not invent new % in route style maps) ───

/**
 * Selected / active list row or nav chip on an opaque product surface.
 * border cool 34% + row wash 10% + cool text.
 */
export const vuiStateSelectedRowClass =
  "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]";

/**
 * Fill-only cool selection wash (bulk multi-select, nested cells).
 * Prefer full selected-row when the element owns its own border.
 */
export const vuiStateSelectedRowFillClass =
  "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]";

/**
 * Warm selected / active row (Agents list active uses product warm accent).
 */
export const vuiStateSelectedWarmRowClass =
  "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))]";

/**
 * Soft cool chip / badge (transparent wash). Prefer selected-row when the
 * parent is an opaque product board; use this only for badges and transient chips.
 */
export const vuiStateCoolSoftClass =
  "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)]";

/**
 * Soft cool info pill (lighter than selected chip).
 */
export const vuiStateCoolInfoClass =
  "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]";

/**
 * Danger-zone panel substrate (fixed error wash on panel).
 */
export const vuiStateDangerPanelClass =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-error)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_4%,var(--vui-surface-panel))]";

/**
 * Warning / confirmation panel substrate.
 */
export const vuiStateWarningPanelClass =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-panel))]";

/**
 * Accent return / hint banner on panel surface (cool 6% wash).
 */
export const vuiStateAccentBannerClass =
  "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-panel))]";

/**
 * Soft danger chip (border + transparent wash + error text).
 */
export const vuiStateDangerSoftClass =
  "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]";

/**
 * Soft success chip.
 */
export const vuiStateSuccessSoftClass =
  "border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]";

/**
 * Soft warning / warm chip.
 */
export const vuiStateWarmSoftClass =
  "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,transparent)] text-[var(--accent-warm-2)]";

/**
 * Soft warning state chip (state-warning token).
 */
export const vuiStateWarningSoftClass =
  "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]";
