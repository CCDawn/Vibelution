export type ResizablePaneBounds = {
  min: number;
  max: number;
};

export const KEYBOARD_RESIZE_STEP = 24;

export function clampPaneWidth(value: number, bounds: ResizablePaneBounds) {
  const normalized = Number.isFinite(value) ? value : bounds.min;
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, normalized)));
}

export function storedPaneWidth(storageKey: string, fallback: number, bounds: ResizablePaneBounds) {
  if (typeof window === "undefined") {
    return clampPaneWidth(fallback, bounds);
  }
  const saved = Number(window.localStorage.getItem(storageKey) || "");
  return clampPaneWidth(Number.isFinite(saved) && saved > 0 ? saved : fallback, bounds);
}

export function keyboardPaneWidth(
  currentWidth: number,
  key: string,
  bounds: ResizablePaneBounds,
  inverted = false,
) {
  if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") {
    return null;
  }
  if (key === "Home") {
    return bounds.min;
  }
  if (key === "End") {
    return bounds.max;
  }
  const direction = key === "ArrowRight" ? 1 : -1;
  const signedDirection = inverted ? -direction : direction;
  return clampPaneWidth(currentWidth + signedDirection * KEYBOARD_RESIZE_STEP, bounds);
}
