import { afterEach, describe, expect, it, vi } from "vitest";

import {
  canResolveLocalFilePath,
  openExternalUrl,
  openPath,
  resolveLocalFilePath,
  showItemInFolder
} from "./desktopPlatform";

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

describe("desktop external open bridges", () => {
  it("degrades to false/empty without the desktop bridge", async () => {
    stubWindow();
    await expect(openExternalUrl("https://example.com/docs")).resolves.toBe(false);
    await expect(openPath("C:\\docs\\a.pdf")).resolves.toBe("");
    await expect(showItemInFolder("C:\\docs\\a.pdf")).resolves.toBe(false);
  });

  it("degrades to false/empty outside any window", async () => {
    await expect(openExternalUrl("https://example.com/docs")).resolves.toBe(false);
    await expect(openPath("C:\\docs\\a.pdf")).resolves.toBe("");
    await expect(showItemInFolder("C:\\docs\\a.pdf")).resolves.toBe(false);
  });

  it("forwards http/https/mailto URLs to the bridge", async () => {
    stubWindow();
    const openExternalUrlBridge = vi.fn(() => Promise.resolve(true));
    vi.stubGlobal("vibelutionLauncher", { openExternalUrl: openExternalUrlBridge });
    await expect(openExternalUrl("https://example.com/docs")).resolves.toBe(true);
    await expect(openExternalUrl("http://example.com/a?b=c")).resolves.toBe(true);
    await expect(openExternalUrl("mailto:support@example.com")).resolves.toBe(true);
    expect(openExternalUrlBridge).toHaveBeenCalledTimes(3);
    expect(openExternalUrlBridge).toHaveBeenLastCalledWith("mailto:support@example.com");
  });

  it("rejects file:// and javascript: schemes before reaching the bridge", async () => {
    stubWindow();
    const openExternalUrlBridge = vi.fn(() => Promise.resolve(true));
    vi.stubGlobal("vibelutionLauncher", { openExternalUrl: openExternalUrlBridge });
    await expect(openExternalUrl("file:///C:/Windows/System32/calc.exe")).resolves.toBe(false);
    await expect(openExternalUrl("javascript:alert(1)")).resolves.toBe(false);
    await expect(openExternalUrl("vibelncher://settings")).resolves.toBe(false);
    await expect(openExternalUrl("not a url")).resolves.toBe(false);
    expect(openExternalUrlBridge).not.toHaveBeenCalled();
  });

  it("returns false when the bridge rejects or answers non-true", async () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", {
      openExternalUrl: () => Promise.reject(new Error("shell failed"))
    });
    await expect(openExternalUrl("https://example.com/docs")).resolves.toBe(false);
    vi.stubGlobal("vibelutionLauncher", {
      openExternalUrl: () => Promise.resolve("ok")
    });
    await expect(openExternalUrl("https://example.com/docs")).resolves.toBe(false);
  });

  it("forwards absolute paths to openPath and showItemInFolder", async () => {
    stubWindow();
    const openPathBridge = vi.fn(() => Promise.resolve(""));
    const showItemBridge = vi.fn(() => Promise.resolve(true));
    vi.stubGlobal("vibelutionLauncher", { openPath: openPathBridge, showItemInFolder: showItemBridge });
    await expect(openPath("C:\\docs\\a.pdf")).resolves.toBe("");
    await expect(showItemInFolder("C:\\docs\\a.pdf")).resolves.toBe(true);
    await expect(openPath("/home/user/report.pdf")).resolves.toBe("");
    await expect(showItemInFolder("\\\\server\\share\\a.pdf")).resolves.toBe(true);
    expect(openPathBridge).toHaveBeenNthCalledWith(1, "C:\\docs\\a.pdf");
    expect(openPathBridge).toHaveBeenNthCalledWith(2, "/home/user/report.pdf");
  });

  it("rejects relative paths and file:// URLs before reaching the path bridge", async () => {
    stubWindow();
    const openPathBridge = vi.fn(() => Promise.resolve(""));
    const showItemBridge = vi.fn(() => Promise.resolve(true));
    vi.stubGlobal("vibelutionLauncher", { openPath: openPathBridge, showItemInFolder: showItemBridge });
    await expect(openPath("docs/a.pdf")).resolves.toBe("");
    await expect(openPath("a.pdf")).resolves.toBe("");
    await expect(openPath("")).resolves.toBe("");
    await expect(showItemInFolder("./docs/a.pdf")).resolves.toBe(false);
    await expect(showItemInFolder("file:///C:/docs/a.pdf")).resolves.toBe(false);
    expect(openPathBridge).not.toHaveBeenCalled();
    expect(showItemBridge).not.toHaveBeenCalled();
  });

  it("surfaces shell.openPath error strings and swallows bridge throws", async () => {
    stubWindow();
    vi.stubGlobal("vibelutionLauncher", {
      openPath: () => Promise.resolve("Failed to open path")
    });
    await expect(openPath("C:\\docs\\missing.pdf")).resolves.toBe("Failed to open path");
    vi.stubGlobal("vibelutionLauncher", {
      openPath: () => {
        throw new Error("sync failure");
      }
    });
    await expect(openPath("C:\\docs\\a.pdf")).resolves.toBe("");
    vi.stubGlobal("vibelutionLauncher", {
      showItemInFolder: () => Promise.reject(new Error("shell failed"))
    });
    await expect(showItemInFolder("C:\\docs\\a.pdf")).resolves.toBe(false);
  });
});
