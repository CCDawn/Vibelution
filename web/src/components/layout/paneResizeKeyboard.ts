/**
 * Shared keyboard contract for vertical workbench rail resize.
 * Arrow keys step; Home/End jump to min/max.
 */

export const PANE_KEYBOARD_STEP = 24;

export type PaneKeyboardDirection = 1 | -1;

export type PaneKeyboardResolveOptions = {
  /** +1 grows width when ArrowRight; -1 for right-side rails. */
  direction?: PaneKeyboardDirection;
  step?: number;
  minWidth: number;
  maxWidth: number;
  currentWidth: number;
};

/**
 * Resolve the next pane width from a keyboard event key.
 * Returns null when the key is not part of the resize contract.
 */
export function resolvePaneWidthFromKeyboardKey(
  key: string,
  options: PaneKeyboardResolveOptions,
): number | null {
  const direction = options.direction ?? 1;
  const step = options.step ?? PANE_KEYBOARD_STEP;
  const { minWidth, maxWidth, currentWidth } = options;

  if (key === "Home") {
    return Math.round(minWidth);
  }
  if (key === "End") {
    return Math.round(maxWidth);
  }
  if (key !== "ArrowLeft" && key !== "ArrowRight") {
    return null;
  }

  const arrowStep = (key === "ArrowRight" ? step : -step) * direction;
  const next = currentWidth + arrowStep;
  return Math.round(Math.min(maxWidth, Math.max(minWidth, next)));
}

export function isPaneResizeKeyboardKey(key: string): boolean {
  return key === "ArrowLeft" || key === "ArrowRight" || key === "Home" || key === "End";
}
