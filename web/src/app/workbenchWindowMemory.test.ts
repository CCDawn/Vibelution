import { describe, expect, it } from "vitest";

import {
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
      }),
    ).toBe("1600x912");
  });
});
