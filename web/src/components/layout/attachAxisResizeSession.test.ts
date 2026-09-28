/** @vitest-environment happy-dom */
import { describe, expect, it, vi } from "vitest";

import source from "./attachAxisResizeSession.ts?raw";
import { attachAxisResizeSession } from "./attachAxisResizeSession";

function fakePointerEvent(type: string, coordinate: number): PointerEvent {
  const event = new Event(type, { bubbles: true }) as PointerEvent;
  Object.defineProperty(event, "clientX", { value: coordinate });
  Object.defineProperty(event, "clientY", { value: coordinate });
  return event;
}

describe("attachAxisResizeSession", () => {
  it("owns window pointer listeners and body cursor for axis drag sessions", () => {
    expect(source).toContain('cursor: AxisResizeCursor');
    expect(source).toContain("document.body.style.cursor");
    expect(source).toContain("document.body.style.userSelect");
    expect(source).toContain('addEventListener("pointermove"');
    expect(source).toContain('addEventListener("pointerup"');
    expect(source).toContain('addEventListener("pointercancel"');
    expect(source).toContain("removeEventListener");
    // Wave 5B: optional rAF coalescing with an end-of-drag flush.
    expect(source).toContain("rafThrottle?: boolean");
    expect(source).toContain("requestAnimationFrame");
    expect(source).toContain("cancelAnimationFrame");
  });

  it("forwards every move immediately without rafThrottle", () => {
    const onMove = vi.fn();
    const onEnd = vi.fn();
    attachAxisResizeSession({ cursor: "col-resize", onMove, onEnd });

    window.dispatchEvent(fakePointerEvent("pointermove", 10));
    window.dispatchEvent(fakePointerEvent("pointermove", 20));
    expect(onMove).toHaveBeenCalledTimes(2);

    window.dispatchEvent(fakePointerEvent("pointerup", 30));
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(document.body.style.cursor).toBe("");
  });

  it("coalesces rAF moves to one call and flushes the last move before onEnd", () => {
    const onMove = vi.fn();
    const onEnd = vi.fn();
    attachAxisResizeSession({ cursor: "col-resize", onMove, onEnd, rafThrottle: true });

    // Moves only mark the pending event; the callback waits for a frame.
    window.dispatchEvent(fakePointerEvent("pointermove", 10));
    window.dispatchEvent(fakePointerEvent("pointermove", 20));
    window.dispatchEvent(fakePointerEvent("pointermove", 30));
    expect(onMove).not.toHaveBeenCalled();

    // pointerup flushes the final coalesced move before committing — and
    // pointercancel must behave exactly the same.
    window.dispatchEvent(fakePointerEvent("pointerup", 30));
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove.mock.calls[0][0].clientX).toBe(30);
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(onEnd.mock.invocationCallOrder[0]).toBeGreaterThan(onMove.mock.invocationCallOrder[0]);
  });

  it("flushes the pending move on pointercancel too", () => {
    const onMove = vi.fn();
    const onEnd = vi.fn();
    attachAxisResizeSession({ cursor: "row-resize", onMove, onEnd, rafThrottle: true });

    window.dispatchEvent(fakePointerEvent("pointermove", 42));
    window.dispatchEvent(fakePointerEvent("pointercancel", 42));
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove.mock.calls[0][0].clientX).toBe(42);
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(document.body.style.cursor).toBe("");
  });
});
