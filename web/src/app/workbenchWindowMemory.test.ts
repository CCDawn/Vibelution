import { describe, expect, it } from "vitest";

import {
  isPersistableWorkbenchWindowPosition,
  isPersistableWorkbenchWindowSize,
  observeWorkbenchWindowMode,
  observeWorkbenchWindowPosition,
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

  it("quantizes window position for stable config writes", () => {
    expect(
      observeWorkbenchWindowPosition({
        screenX: 123,
        screenY: 87,
      }),
    ).toBe("120,88");
  });

  it("accepts multi-monitor negative positions", () => {
    expect(
      observeWorkbenchWindowPosition({
        screenX: -640,
        screenY: 120,
      }),
    ).toBe("-640,120");
    expect(isPersistableWorkbenchWindowPosition("-640,120")).toBe(true);
    expect(isPersistableWorkbenchWindowPosition("120,80")).toBe(true);
    expect(isPersistableWorkbenchWindowPosition("auto")).toBe(false);
    expect(isPersistableWorkbenchWindowPosition("bogus")).toBe(false);
  });

  it("rejects extreme off-screen positions that would hide the next start", () => {
    expect(isPersistableWorkbenchWindowPosition("-20000,-20000")).toBe(false);
    expect(isPersistableWorkbenchWindowPosition("20000,0")).toBe(false);
    expect(
      observeWorkbenchWindowPosition({
        screenX: -20000,
        screenY: -20000,
      }),
    ).toBe("-20000,-20000");
    // Observed extremes must not be written back.
    expect(isPersistableWorkbenchWindowPosition(
      observeWorkbenchWindowPosition({ screenX: -20000, screenY: -20000 }),
    )).toBe(false);
  });
});
