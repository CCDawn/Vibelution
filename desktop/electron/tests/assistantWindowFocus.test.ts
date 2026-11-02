import { describe, expect, it, vi } from "vitest";

// The narrow focus verb never touches Electron at runtime: the float window
// handle is injected below, so a bare module stub keeps import-time surfaces
// (petWindow, launcherWindow) loadable without a real Electron.
vi.mock("electron", () => ({ BrowserWindow: class {}, dialog: {}, screen: {} }));
vi.mock("../src/paths.js", () => ({
  resolvePreloadPath: () => "preload.js",
  resolveWorkspaceIconPath: () => "icon.ico",
}));

import { AssistantWindow } from "../src/assistant/assistantWindow.js";
import type { AssistantHost } from "../src/assistant/assistantHost.js";
import type { DesktopPaths } from "../src/paths.js";

type FloatWindow = {
  show: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  isDestroyed: () => boolean;
};

function floatWindow(overrides: Partial<FloatWindow> = {}): FloatWindow {
  return { show: vi.fn(), focus: vi.fn(), isDestroyed: () => false, ...overrides };
}

function assistantWith(window: unknown, isQuitting: () => boolean = () => false): AssistantWindow {
  const assistant = new AssistantWindow({} as DesktopPaths, {} as AssistantHost, isQuitting);
  (assistant as unknown as { window: unknown }).window = window;
  return assistant;
}

describe("assistant float narrow focus verb", () => {
  it("shows and focuses the resident float and reports success", async () => {
    const window = floatWindow();
    const assistant = assistantWith(window);
    await expect(assistant.focus()).resolves.toBe(true);
    expect(window.show).toHaveBeenCalledTimes(1);
    expect(window.focus).toHaveBeenCalledTimes(1);
  });

  it("stays a no-op when the float does not exist, provisioning nothing", async () => {
    const assistant = assistantWith(null);
    await expect(assistant.focus()).resolves.toBe(false);
    // The verb must not create a window or a native host; provisioning stays
    // with open()/the assistant host.
    expect((assistant as unknown as { window: unknown }).window).toBeNull();
  });

  it("stays a no-op for a destroyed float", async () => {
    const window = floatWindow({ isDestroyed: () => true });
    const assistant = assistantWith(window);
    await expect(assistant.focus()).resolves.toBe(false);
    expect(window.show).not.toHaveBeenCalled();
    expect(window.focus).not.toHaveBeenCalled();
  });

  it("stays a no-op while quitting", async () => {
    const window = floatWindow();
    const assistant = assistantWith(window, () => true);
    await expect(assistant.focus()).resolves.toBe(false);
    expect(window.show).not.toHaveBeenCalled();
    expect(window.focus).not.toHaveBeenCalled();
  });
});
