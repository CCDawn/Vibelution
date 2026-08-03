import { describe, expect, it } from "vitest";

import {
  isPersistableWorkbenchWindowSize,
  observeWorkbenchWindowMode,
  observeWorkbenchWindowSize,
} from "./workbenchWindowMemory";

function fakeWindow(options: {
  outerWidth: number;
  outerHeight: number;
  screenWidth: number;
  screenHeight: number;
}) {
  return {
    outerWidth: options.outerWidth,
    outerHeight: options.outerHeight,
    screen: {
      width: options.screenWidth,
      height: options.screenHeight,
    },
  } as Pick<Window, "outerWidth" | "outerHeight" | "screen">;
}

describe("workbenchWindowMemory", () => {
  it("treats near full-screen outer bounds as fullscreen (F11 / start-fullscreen)", () => {
    expect(
      observeWorkbenchWindowMode(
        fakeWindow({
          outerWidth: 1920,
          outerHeight: 1080,
          screenWidth: 1920,
          screenHeight: 1080,
        }),
      ),
    ).toBe("fullscreen");
  });

  it("treats smaller outer bounds as windowed", () => {
    expect(
      observeWorkbenchWindowMode(
        fakeWindow({
          outerWidth: 1440,
          outerHeight: 900,
          screenWidth: 1920,
          screenHeight: 1080,
        }),
      ),
    ).toBe("windowed");
  });

  it("quantizes window size for stable config writes", () => {
    expect(
      observeWorkbenchWindowSize({
        outerWidth: 1605,
        outerHeight: 904,
        screen: { availWidth: 1920, availHeight: 1080 } as Screen,
      }),
    ).toBe("1600x912");
  });

  it("clamps remembered window size to the available work area", () => {
    expect(
      observeWorkbenchWindowSize({
        outerWidth: 2400,
        outerHeight: 1400,
        screen: { availWidth: 1536, availHeight: 864 } as Screen,
      }),
    ).toBe("1536x864");
  });

  it("never reports Edge chrome-sized shells (320x240) as persistable sizes", () => {
    expect(
      observeWorkbenchWindowSize({
        outerWidth: 320,
        outerHeight: 240,
        screen: { availWidth: 1920, availHeight: 1080 } as Screen,
      }),
    ).toBe("960x600");
    expect(isPersistableWorkbenchWindowSize("320x240")).toBe(false);
    expect(isPersistableWorkbenchWindowSize("960x600")).toBe(true);
    expect(isPersistableWorkbenchWindowSize("1600x900")).toBe(true);
  });
});
