import { describe, expect, it } from "vitest";

import {
  clampPetWindowBounds,
  defaultPetWindowBounds,
  PET_WINDOW_HEIGHT,
  PET_WINDOW_WIDTH,
} from "../src/windows/petWindowBounds.js";

describe("desktop pet window bounds", () => {
  it("places a new pet near the bottom-right of the active work area", () => {
    expect(defaultPetWindowBounds({ x: 0, y: 0, width: 1920, height: 1040 })).toEqual({
      x: 1582,
      y: 612,
      width: PET_WINDOW_WIDTH,
      height: PET_WINDOW_HEIGHT,
    });
  });

  it("clamps persisted coordinates back onto the selected display", () => {
    expect(clampPetWindowBounds({ x: 9999, y: -9999 }, { x: -1280, y: 0, width: 1280, height: 1024 }))
      .toEqual({ x: -320, y: 0, width: PET_WINDOW_WIDTH, height: PET_WINDOW_HEIGHT });
  });
});
