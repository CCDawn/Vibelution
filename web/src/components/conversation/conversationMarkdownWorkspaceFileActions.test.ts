import { afterEach, describe, expect, it, vi } from "vitest";

import {
  openWorkspaceFile,
  revealWorkspaceFile,
} from "./conversationMarkdownWorkspaceFileActions";

const platform = vi.hoisted(() => ({
  openPath: vi.fn<(path: string) => Promise<string>>(),
  showItemInFolder: vi.fn<(path: string) => Promise<boolean>>(),
}));

vi.mock("../../api/desktopPlatform", () => ({
  openPath: platform.openPath,
  showItemInFolder: platform.showItemInFolder,
}));

type BridgeGlobal = { vibelutionLauncher?: unknown };
const bridgeGlobal = globalThis as BridgeGlobal;
const originalBridge = bridgeGlobal.vibelutionLauncher;

function setBridge(bridge: unknown) {
  bridgeGlobal.vibelutionLauncher = bridge;
}

describe("conversationMarkdownWorkspaceFileActions", () => {
  afterEach(() => {
    bridgeGlobal.vibelutionLauncher = originalBridge;
    platform.openPath.mockReset();
    platform.showItemInFolder.mockReset();
  });

  it("reports done when the desktop bridge opens the path", async () => {
    setBridge({ openPath: () => undefined });
    platform.openPath.mockResolvedValue("");
    await expect(openWorkspaceFile("C:\\r\\a.md")).resolves.toBe("done");
  });

  it("reports unavailable outside Electron even when openPath resolves empty", async () => {
    setBridge(undefined);
    platform.openPath.mockResolvedValue("");
    await expect(openWorkspaceFile("C:\\r\\a.md")).resolves.toBe("unavailable");
  });

  it("reports unavailable when the shell call returns an error text", async () => {
    setBridge({ openPath: () => undefined });
    platform.openPath.mockResolvedValue("无法打开该路径");
    await expect(openWorkspaceFile("C:\\r\\a.md")).resolves.toBe("unavailable");
  });

  it("reports reveal results from the bridge boolean", async () => {
    setBridge({ showItemInFolder: () => undefined });
    platform.showItemInFolder.mockResolvedValue(true);
    await expect(revealWorkspaceFile("C:\\r\\a.md")).resolves.toBe("done");
    platform.showItemInFolder.mockResolvedValue(false);
    await expect(revealWorkspaceFile("C:\\r\\a.md")).resolves.toBe("unavailable");
  });

  it("reports reveal unavailable outside Electron without calling the platform", async () => {
    setBridge(undefined);
    platform.showItemInFolder.mockResolvedValue(true);
    await expect(revealWorkspaceFile("C:\\r\\a.md")).resolves.toBe("unavailable");
    expect(platform.showItemInFolder).not.toHaveBeenCalled();
  });
});
