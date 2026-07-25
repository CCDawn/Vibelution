/**
 * Shared pointer drag session for col-resize / row-resize workbench handles (Wave 5).
 * Routes supply axis-specific move math; body cursor and listeners stay centralized.
 */

export type AxisResizeCursor = "col-resize" | "row-resize";

export type AttachAxisResizeSessionOptions = {
  cursor: AxisResizeCursor;
  onMove: (event: PointerEvent) => void;
  onEnd?: () => void;
};

/**
 * Start a window-level pointer drag session. Call after preventDefault on pointerdown.
 */
export function attachAxisResizeSession(options: AttachAxisResizeSessionOptions): void {
  if (typeof window === "undefined") {
    return;
  }
  const previousCursor = document.body.style.cursor;
  const previousUserSelect = document.body.style.userSelect;
  document.body.style.cursor = options.cursor;
  document.body.style.userSelect = "none";

  const onMove = (event: PointerEvent) => {
    options.onMove(event);
  };
  const onEnd = () => {
    document.body.style.cursor = previousCursor;
    document.body.style.userSelect = previousUserSelect;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onEnd);
    window.removeEventListener("pointercancel", onEnd);
    options.onEnd?.();
  };

  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onEnd);
  window.addEventListener("pointercancel", onEnd);
}
