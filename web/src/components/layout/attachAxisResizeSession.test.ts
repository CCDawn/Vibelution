import { describe, expect, it, vi } from "vitest";

import { attachAxisResizeSession } from "./attachAxisResizeSession";

describe("attachAxisResizeSession", () => {
  it("sets body cursor and tears down on pointerup", () => {
    const moves: number[] = [];
    const onEnd = vi.fn();
    document.body.style.cursor = "default";
    document.body.style.userSelect = "auto";

    attachAxisResizeSession({
      cursor: "col-resize",
      onMove: (event) => {
        moves.push(event.clientX);
      },
      onEnd,
    });

    expect(document.body.style.cursor).toBe("col-resize");
    expect(document.body.style.userSelect).toBe("none");

    window.dispatchEvent(new PointerEvent("pointermove", { clientX: 120 }));
    window.dispatchEvent(new PointerEvent("pointerup"));

    expect(moves).toEqual([120]);
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(document.body.style.cursor).toBe("default");
    expect(document.body.style.userSelect).toBe("auto");
  });
});
