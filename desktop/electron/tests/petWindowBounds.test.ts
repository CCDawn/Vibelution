import { describe, expect, it } from "vitest";

import {
  clampPetWindowBounds,
  defaultPetWindowBounds,
  desktopPetWindowExpandedBounds,
  PET_WINDOW_HEIGHT,
  PET_WINDOW_WIDTH,
} from "../src/windows/petWindowBounds.js";

describe("desktop pet window bounds", () => {
  it("places a new pet near the bottom-right of the active work area", () => {
    expect(defaultPetWindowBounds({ x: 0, y: 0, width: 1920, height: 1040 })).toEqual({
      x: 1602,
      y: 692,
      width: PET_WINDOW_WIDTH,
      height: PET_WINDOW_HEIGHT,
    });
  });
  it("clamps the expanded preset and restores the collapsed size", () => {
    const area = { x: -1280, y: 0, width: 1280, height: 1024 };
    const expanded = desktopPetWindowExpandedBounds({ x: -300, y: 692 }, area, true);
    expect(expanded).toEqual({ x: -400, y: 494, width: 400, height: 530 });
    expect(desktopPetWindowExpandedBounds(expanded, area, false)).toEqual({ x: -400, y: 494, width: 300, height: 330 });
    expect(desktopPetWindowExpandedBounds({ x: 900, y: 900 }, { x: 20, y: 30, width: 400, height: 300 }, true))
      .toEqual({ x: 20, y: 30, width: 400, height: 300 });
  });

  it("clamps persisted coordinates back onto the selected display", () => {
    expect(clampPetWindowBounds({ x: 9999, y: -9999 }, { x: -1280, y: 0, width: 1280, height: 1024 }))
      .toEqual({ x: -300, y: 0, width: PET_WINDOW_WIDTH, height: PET_WINDOW_HEIGHT });
  });
});
