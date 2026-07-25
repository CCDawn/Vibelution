import { describe, expect, it } from "vitest";

import { PANE_KEYBOARD_STEP } from "./paneResizeKeyboard";
import {
  isPaneHeightResizeKeyboardKey,
  resolvePaneHeightFromKeyboardKey,
} from "./paneHeightKeyboard";

describe("paneHeightKeyboard", () => {
  const bounds = { minHeight: 200, maxHeight: 500, currentHeight: 340 };

  it("steps with ArrowUp/ArrowDown", () => {
    expect(resolvePaneHeightFromKeyboardKey("ArrowDown", bounds)).toBe(340 + PANE_KEYBOARD_STEP);
    expect(resolvePaneHeightFromKeyboardKey("ArrowUp", bounds)).toBe(340 - PANE_KEYBOARD_STEP);
  });

  it("jumps with Home/End and clamps", () => {
    expect(resolvePaneHeightFromKeyboardKey("Home", bounds)).toBe(200);
    expect(resolvePaneHeightFromKeyboardKey("End", bounds)).toBe(500);
    expect(
      resolvePaneHeightFromKeyboardKey("ArrowDown", {
        ...bounds,
        currentHeight: 490,
      }),
    ).toBe(500);
  });

  it("ignores horizontal keys", () => {
    expect(resolvePaneHeightFromKeyboardKey("ArrowLeft", bounds)).toBeNull();
    expect(isPaneHeightResizeKeyboardKey("ArrowDown")).toBe(true);
    expect(isPaneHeightResizeKeyboardKey("ArrowLeft")).toBe(false);
  });
});
