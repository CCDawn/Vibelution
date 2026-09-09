import { describe, expect, it } from "vitest";

import {
  beginDesktopPetWindowDrag,
  desktopPetWindowBoundsAt,
  isDesktopPetDragPoint,
} from "../src/windows/petWindowDrag.js";

describe("desktop pet main-process window drag", () => {
  it("anchors movement to the pointer start while preserving the original size", () => {
    const drag = beginDesktopPetWindowDrag(
      { screenX: 410.4, screenY: 270.2 },
      { x: 120, y: 90, width: 300, height: 330 },
    );

    expect(desktopPetWindowBoundsAt(drag, { screenX: 438.7, screenY: 251.8 })).toEqual({
      x: 148,
      y: 72,
      width: 300,
      height: 330,
    });
  });

  it("accepts only finite screen coordinates at the IPC boundary", () => {
    expect(isDesktopPetDragPoint({ screenX: 10, screenY: -20 })).toBe(true);
    expect(isDesktopPetDragPoint({ screenX: Number.NaN, screenY: 0 })).toBe(false);
    expect(isDesktopPetDragPoint({ screenX: 0 })).toBe(false);
  });

  it("does not accumulate fractional-DPI rounding into the window size", () => {
    const drag = beginDesktopPetWindowDrag(
      { screenX: 500.25, screenY: 300.25 },
      { x: 500, y: 300, width: 300, height: 330 },
    );

    const bounds = Array.from({ length: 24 }, (_, index) => desktopPetWindowBoundsAt(drag, {
      screenX: 500.25 + index * 1.25,
      screenY: 300.25 - index * 0.75,
    }));

    expect(new Set(bounds.map(({ width, height }) => `${width}x${height}`))).toEqual(new Set(["300x330"]));
    expect(bounds.at(-1)).toMatchObject({ x: 529, y: 283 });
  });
});
