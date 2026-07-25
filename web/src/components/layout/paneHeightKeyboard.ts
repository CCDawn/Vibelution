/**
 * Shared keyboard contract for horizontal workbench splitters (row-resize).
 * ArrowUp/Down step; Home/End jump to min/max.
 */

import { PANE_KEYBOARD_STEP } from "./paneResizeKeyboard";

export type PaneHeightKeyboardResolveOptions = {
  /** +1 grows height when ArrowDown; -1 if the handle is above the pane. */
  direction?: 1 | -1;
  step?: number;
  minHeight: number;
  maxHeight: number;
  currentHeight: number;
};

export function resolvePaneHeightFromKeyboardKey(
  key: string,
  options: PaneHeightKeyboardResolveOptions,
): number | null {
  const direction = options.direction ?? 1;
  const step = options.step ?? PANE_KEYBOARD_STEP;
  const { minHeight, maxHeight, currentHeight } = options;

  if (key === "Home") {
    return Math.round(minHeight);
  }
  if (key === "End") {
    return Math.round(maxHeight);
  }
  if (key !== "ArrowUp" && key !== "ArrowDown") {
    return null;
  }

  const arrowStep = (key === "ArrowDown" ? step : -step) * direction;
  const next = currentHeight + arrowStep;
  return Math.round(Math.min(maxHeight, Math.max(minHeight, next)));
}

export function isPaneHeightResizeKeyboardKey(key: string): boolean {
  return key === "ArrowUp" || key === "ArrowDown" || key === "Home" || key === "End";
}
