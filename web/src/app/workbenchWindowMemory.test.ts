import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../api/client";

import {
  isPersistableWorkbenchWindowPosition,
  isPersistableWorkbenchWindowSize,
  observeWorkbenchWindowMode,
  observeWorkbenchWindowPosition,
  observeWorkbenchWindowSize,
  resetWorkbenchWindowMemoryForTests,
  startWorkbenchWindowMemory,
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
  afterEach(() => {
    resetWorkbenchWindowMemoryForTests();
    resetControlTokenForTests();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

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

  it("reads the startup config hash before persisting the remembered window", async () => {
    vi.useFakeTimers();
    seedControlTokenForTests();
    vi.stubGlobal("window", {
      outerWidth: 1280,
      outerHeight: 720,
      screenX: 112,
      screenY: 88,
      screen: {
        width: 1920,
        height: 1080,
        availWidth: 1920,
        availHeight: 1080,
      },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      setTimeout,
      setInterval,
    });
    vi.stubGlobal("document", {
      visibilityState: "visible",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ configHash: "hash-current" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const dispose = startWorkbenchWindowMemory();
    await vi.advanceTimersByTimeAsync(700);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/settings/startup");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("GET");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/settings/startup");
    const putInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(putInit.method).toBe("PUT");
    expect(JSON.parse(String(putInit.body))).toEqual({
      workbench: {
        windowMode: "windowed",
        windowSize: "1280x720",
        windowPosition: "112,88",
      },
      baseHash: "hash-current",
    });

    dispose();
  });

  it("does not issue a soft write when the startup hash is unavailable", async () => {
    vi.useFakeTimers();
    seedControlTokenForTests();
    vi.stubGlobal("window", {
      outerWidth: 1280,
      outerHeight: 720,
      screenX: 112,
      screenY: 88,
      screen: {
        width: 1920,
        height: 1080,
        availWidth: 1920,
        availHeight: 1080,
      },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      setTimeout,
      setInterval,
    });
    vi.stubGlobal("document", {
      visibilityState: "visible",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    const dispose = startWorkbenchWindowMemory();
    await vi.advanceTimersByTimeAsync(700);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("GET");

    dispose();
  });
});
