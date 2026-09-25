import { afterEach, describe, expect, it, vi } from "vitest";

import { canResolveLocalFilePath, resolveLocalFilePath } from "./desktopPlatform";

function imageFile(): File {
  return new File([new Uint8Array([1, 2, 3])], "a.png", { type: "image/png" });
}

function stubWindow() {
  vi.stubGlobal("window", {
    location: { href: "http://127.0.0.1:8765/", origin: "http://127.0.0.1:8765" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("desktop platform capability probes", () => {
  it("reports no local-path capability without the desktop bridge", () => {
    stubWindow();
    expect(canResolveLocalFilePath()).toBe(false);
    expect(resolveLocalFilePath(imageFile())).toBeNull();
  });

  it("resolves a trimmed local path through the desktop bridge", () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", {
      getPathForFile: (file: unknown) => (file instanceof File ? "  C:\\pics\\a.png  " : null),
    });
    expect(canResolveLocalFilePath()).toBe(true);
    expect(resolveLocalFilePath(imageFile())).toBe("C:\\pics\\a.png");
  });

  it("returns null for clipboard-style files without a local path", () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", {
      getPathForFile: () => "",
    });
    expect(canResolveLocalFilePath()).toBe(true);
    expect(resolveLocalFilePath(imageFile())).toBeNull();
  });

  it("returns null when the bridge call throws", () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", {
      getPathForFile: () => {
        throw new Error("not a File");
      },
    });
    expect(resolveLocalFilePath(imageFile())).toBeNull();
  });

  it("ignores a bridge without a usable getPathForFile member", () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", { launcherInvoke: () => undefined });
    expect(canResolveLocalFilePath()).toBe(false);
    expect(resolveLocalFilePath(imageFile())).toBeNull();
  });
});
