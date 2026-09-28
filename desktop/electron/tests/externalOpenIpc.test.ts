import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { IPC_CHANNELS } from "../src/ipc.js";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const providerSource = readFileSync(
  fileURLToPath(new URL("../src/windows/electronWindowProvider.ts", import.meta.url)),
  "utf8",
);

function handlerSourceFor(channelKey: string): string {
  const start = mainSource.indexOf(`IPC_CHANNELS.${channelKey}`);
  expect(start, `expected a ${channelKey} handler in main.ts`).toBeGreaterThan(0);
  const end = mainSource.indexOf("});", start);
  return mainSource.slice(start, end);
}

describe("Electron main external-open IPC facade", () => {
  it("registers the three vui shell channels", () => {
    expect(IPC_CHANNELS.openExternalUrl).toBe("vui:open-external");
    expect(IPC_CHANNELS.openPath).toBe("vui:open-path");
    expect(IPC_CHANNELS.showItemInFolder).toBe("vui:show-item-in-folder");
  });

  it("validates the sender before touching the shell on every channel", () => {
    for (const channelKey of ["openExternalUrl", "openPath", "showItemInFolder"] as const) {
      const source = handlerSourceFor(channelKey);
      expect(source, channelKey).toContain("assertTrustedIpcSender(event, trustedIpcOrigins())");
    }
  });

  it("only hands whitelisted schemes to shell.openExternal", () => {
    const source = handlerSourceFor("openExternalUrl");
    expect(source).toContain("isExternalOpenableUrl(rawUrl)");
    expect(source).toContain("shell.openExternal(rawUrl)");
    expect(source).not.toContain("child_process");
    expect(source).not.toContain("exec");
    expect(source).not.toContain("spawn");
  });

  it("requires absolute paths for openPath and showItemInFolder", () => {
    const openPathSource = handlerSourceFor("openPath");
    expect(openPathSource).toContain("normalizeAbsoluteOpenPath(rawPath)");
    expect(openPathSource).toContain("shell.openPath(target)");
    const showItemSource = handlerSourceFor("showItemInFolder");
    expect(showItemSource).toContain("normalizeAbsoluteOpenPath(rawPath)");
    expect(showItemSource).toContain("shell.showItemInFolder(target)");
  });

  it("exposes the three bridges next to getPathForFile in the preload", () => {
    expect(preloadSource).toContain("getPathForFile");
    expect(preloadSource).toContain("openExternalUrl: (url: string) => ipcRenderer.invoke(IPC_CHANNELS.openExternalUrl, url)");
    expect(preloadSource).toContain("openPath: (path: string) => ipcRenderer.invoke(IPC_CHANNELS.openPath, path)");
    expect(preloadSource).toContain("showItemInFolder: (path: string) => ipcRenderer.invoke(IPC_CHANNELS.showItemInFolder, path)");
  });

  it("injects the real shell openExternal into the window provider", () => {
    expect(mainSource).toContain("openExternalUrl: (url) => shell.openExternal(url)");
    expect(providerSource).toContain("options.openExternalUrl ?? (() => undefined)");
    expect(providerSource).toContain("isExternalOpenableUrl(details.url)");
  });

  it("never routes file:// or javascript through openExternal", () => {
    const policySource = readFileSync(
      fileURLToPath(new URL("../src/security/externalOpenPolicy.ts", import.meta.url)),
      "utf8",
    );
    expect(policySource).toContain('"http:"');
    expect(policySource).toContain('"https:"');
    expect(policySource).toContain('"mailto:"');
    expect(policySource).not.toContain('"file:"');
  });
});
