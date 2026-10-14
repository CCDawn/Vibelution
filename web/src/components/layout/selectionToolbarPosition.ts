export type SelectionToolbarAnchorRect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export type SelectionToolbarPosition = {
  left: number;
  top: number;
  above: boolean;
};

export const SELECTION_TOOLBAR_WIDTH_PX = 208;
export const SELECTION_TOOLBAR_HEIGHT_PX = 40;
export const SELECTION_TOOLBAR_GAP_PX = 8;
export const SELECTION_TOOLBAR_VIEWPORT_MARGIN_PX = 12;

/** Center a viewport-fixed toolbar on its selection, flipping and clamping it. */
export function resolveSelectionToolbarPosition(
  anchorRect: SelectionToolbarAnchorRect,
  viewport: { width: number; height: number },
  toolbarSize: { width: number; height: number } = {
    width: SELECTION_TOOLBAR_WIDTH_PX,
    height: SELECTION_TOOLBAR_HEIGHT_PX,
  },
): SelectionToolbarPosition {
  const toolbarWidth = Math.max(0, toolbarSize.width);
  const toolbarHeight = Math.max(0, toolbarSize.height);
  const margin = SELECTION_TOOLBAR_VIEWPORT_MARGIN_PX;
  const viewportWidth = Math.max(viewport.width, toolbarWidth + margin * 2);
  const viewportHeight = Math.max(viewport.height, toolbarHeight + margin * 2);
  const center = anchorRect.left + anchorRect.width / 2;
  const maxLeft = Math.max(margin, viewportWidth - toolbarWidth - margin);
  const left = Math.min(Math.max(margin, center - toolbarWidth / 2), maxLeft);
  const above = anchorRect.top >= toolbarHeight + margin + SELECTION_TOOLBAR_GAP_PX;
  const rawTop = above
    ? anchorRect.top - SELECTION_TOOLBAR_GAP_PX
    : anchorRect.bottom + SELECTION_TOOLBAR_GAP_PX;
  const visualTop = above ? rawTop - toolbarHeight : rawTop;
  const maxVisualTop = Math.max(margin, viewportHeight - toolbarHeight - margin);
  const clampedVisualTop = Math.min(Math.max(margin, visualTop), maxVisualTop);
  return {
    above,
    left,
    top: above ? clampedVisualTop + toolbarHeight : clampedVisualTop,
  };
}
