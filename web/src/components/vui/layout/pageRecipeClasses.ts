/**
 * Shared visual + geometry defaults for VUI page recipes.
 * Keep routes on these tokens so shells stay coordinated without per-page reinvention.
 */

/** Full-viewport workbench page: header auto + body fills remainder. */
export const VUI_PAGE_FILL_CLASS =
  "grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_minmax(0,1fr)] content-stretch gap-0 overflow-hidden";

/** Flex column fill when the parent is already a sized flex/grid cell. */
export const VUI_PAGE_STACK_FILL_CLASS =
  "flex h-full min-h-0 min-w-0 flex-col gap-0 overflow-hidden";

/** Scrollable main body inside a filled page. */
export const VUI_PAGE_BODY_SCROLL_CLASS =
  "min-h-0 min-w-0 flex-1 overflow-auto [scrollbar-gutter:stable]";

/** Non-scrolling filled body (split / board owns overflow). */
export const VUI_PAGE_BODY_FILL_CLASS =
  "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden";

/** Quiet page gap used between header/toolbar bands (not inside dense tables). */
export const VUI_PAGE_BAND_GAP_CLASS = "gap-2";

/** Standard workbench surface: panel fill, soft radius, subtle border. */
export const VUI_WORKBENCH_SURFACE_CLASS =
  "min-h-0 min-w-0 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]";

/** Rail / list column surface. */
export const VUI_RAIL_SURFACE_CLASS =
  "min-h-0 min-w-0 h-full overflow-hidden rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)]";

/** Canvas / board host surface (mesh-friendly base). */
export const VUI_CANVAS_SURFACE_CLASS =
  "min-h-0 min-w-0 h-full overflow-hidden rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-base)]";

/** Compact chrome strip under route headers (mode switch, filters). */
export const VUI_PAGE_TOOLBAR_STRIP_CLASS =
  "flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 py-2";

/** Primary scroll/content padding inside board main. */
export const VUI_BOARD_CONTENT_PAD_CLASS =
  "flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4 [scrollbar-gutter:stable]";
