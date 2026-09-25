/**
 * Shared pointer drag session for col-resize / row-resize workbench handles (Wave 5).
 * Routes supply axis-specific move math; body cursor and listeners stay centralized.
 * Wave 5B adds optional rAF coalescing (borrowed from zai-org/ZCode
 * WorkbenchSplitDivider drag discipline, Apache-2.0): with `rafThrottle` the
 * move callback runs at most once per animation frame, and the final coalesced
 * move is flushed synchronously on pointerup AND pointercancel so end-of-drag
 * commits never miss the last pointer position.
 */

export type AxisResizeCursor = "col-resize" | "row-resize";

export type AttachAxisResizeSessionOptions = {
  cursor: AxisResizeCursor;
  onMove: (event: PointerEvent) => void;
  onEnd?: () => void;
  /**
   * Coalesce pointermove callbacks to one per animation frame. The last move
   * before pointerup/pointercancel is always flushed through onMove before
   * onEnd runs, keeping direct DOM writes and state commits in sync.
   */
  rafThrottle?: boolean;
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

  let frameId: number | null = null;
  let pendingEvent: PointerEvent | null = null;
  const runMove = (event: PointerEvent) => {
    options.onMove(event);
  };
  const onMove = options.rafThrottle
    ? (event: PointerEvent) => {
        pendingEvent = event;
        if (frameId != null) {
          return;
        }
        frameId = window.requestAnimationFrame(() => {
          frameId = null;
          if (pendingEvent) {
            const event = pendingEvent;
            pendingEvent = null;
            runMove(event);
          }
        });
      }
    : runMove;

  const flushPendingMove = () => {
    if (frameId != null) {
      window.cancelAnimationFrame(frameId);
      frameId = null;
    }
    if (pendingEvent) {
      const event = pendingEvent;
      pendingEvent = null;
      runMove(event);
    }
  };

  const onEnd = () => {
    // Flush the last coalesced move before commit so pointerup and
    // pointercancel land the same final direct DOM write.
    flushPendingMove();
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
