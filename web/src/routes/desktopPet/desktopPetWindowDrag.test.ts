import { describe, expect, it } from "vitest";

import {
  beginDesktopPetDrag,
  desktopPetWindowDragBridge,
  updateDesktopPetDrag,
} from "./desktopPetWindowDrag";

describe("desktop pet window drag", () => {
  it("keeps a small pointer movement available for the character click", () => {
    const state = beginDesktopPetDrag(7, { screenX: 100, screenY: 200 });

    expect(updateDesktopPetDrag(state, 7, { screenX: 102, screenY: 202 })).toEqual({
      state,
      delta: null,
    });
  });

  it("moves by the full initial gesture and then by incremental pointer deltas", () => {
    const state = beginDesktopPetDrag(7, { screenX: 100, screenY: 200 });
    const first = updateDesktopPetDrag(state, 7, { screenX: 104, screenY: 203 });

    expect(first).toEqual({
      state: {
        pointerId: 7,
        start: { screenX: 100, screenY: 200 },
        last: { screenX: 104, screenY: 203 },
        moved: true,
      },
      delta: { screenX: 4, screenY: 3 },
    });
    expect(updateDesktopPetDrag(first!.state, 7, { screenX: 109, screenY: 201 })?.delta).toEqual({
      screenX: 5,
      screenY: -2,
    });
  });

  it("ignores updates from a different pointer", () => {
    const state = beginDesktopPetDrag(7, { screenX: 100, screenY: 200 });

    expect(updateDesktopPetDrag(state, 8, { screenX: 120, screenY: 220 })).toBeNull();
  });

  it("uses the Electron-owned fixed-bounds drag bridge when all operations are available", () => {
    const beginDesktopPetWindowDrag = () => undefined;
    const moveDesktopPetWindowDrag = () => undefined;
    const endDesktopPetWindowDrag = () => undefined;

    expect(desktopPetWindowDragBridge({
      vibelutionLauncher: {
        beginDesktopPetWindowDrag,
        moveDesktopPetWindowDrag,
        endDesktopPetWindowDrag,
      },
    })).toEqual({
      beginDesktopPetWindowDrag,
      moveDesktopPetWindowDrag,
      endDesktopPetWindowDrag,
    });
    expect(desktopPetWindowDragBridge({ vibelutionLauncher: { moveDesktopPetWindowDrag } })).toBeNull();
  });
});
