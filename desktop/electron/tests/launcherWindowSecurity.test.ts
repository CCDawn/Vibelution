import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ window: null as any }));
vi.mock("electron", () => ({ BrowserWindow: class {
  webContents: any;
  loadURL = vi.fn(async (url: string) => { this.webContents.url = url; });
  constructor() {
    const handlers = new Map<string, (...args: any[]) => void>();
    const frame = { url: "vibelution-launcher://launcher/launcher/assistant" };
    this.webContents = { mainFrame: frame, url: frame.url, isDestroyed: () => false,
      getURL() { return this.url; }, on: (name: string, cb: (...args: any[]) => void) => handlers.set(name, cb),
      setWindowOpenHandler: vi.fn(), handlers };
    state.window = this;
  }
} }));
import { createLauncherWindow, isTrustedLauncherControlFrame } from "../src/windows/launcherWindow.js";

const paths = { schemaVersion: 1 as const, workspaceRoot: "C:/repo", desktopBundleRoot: "C:/bundle", resourcesRoot: "C:/resources", userDataRoot: "C:/data" };

describe("Launcher window navigation and sender boundary", () => {
  it("blocks foreign top-level navigation and redirects, and keeps the trusted route", () => {
    createLauncherWindow("vibelution-launcher://launcher/launcher/assistant", paths);
    const contents = state.window.webContents;
    const navigate = contents.handlers.get("will-navigate");
    const redirect = contents.handlers.get("will-redirect");
    const denied = { preventDefault: vi.fn() };
    navigate(denied, "https://example.com/launcher/assistant");
    redirect(denied, "file:///C:/outside", false, true);
    redirect({ url: "https://example.com/redirect", isMainFrame: true, preventDefault: denied.preventDefault });
    navigate(denied, "vibelution-launcher://launcher/launcher-assistant");
    expect(denied.preventDefault).toHaveBeenCalledTimes(4);
    const allowed = { preventDefault: vi.fn() };
    navigate(allowed, "vibelution-launcher://launcher/launcher/settings");
    redirect(allowed, "https://example.com/frame", false, false);
    expect(allowed.preventDefault).not.toHaveBeenCalled();
    expect(contents.setWindowOpenHandler.mock.calls[0][0]()).toEqual({ action: "deny" });
  });
  it("requires exact owned main frame and its current pinned URL", () => {
    createLauncherWindow("vibelution-launcher://launcher/launcher/assistant", paths);
    const sender = state.window.webContents;
    const event = { sender, senderFrame: sender.mainFrame };
    expect(isTrustedLauncherControlFrame(event)).toBe(true);
    expect(isTrustedLauncherControlFrame({ sender, senderFrame: { url: sender.mainFrame.url } })).toBe(false);
    sender.mainFrame.url = "https://example.com/launcher/assistant";
    sender.url = sender.mainFrame.url;
    expect(isTrustedLauncherControlFrame(event)).toBe(false);
    sender.mainFrame.url = "vibelution-launcher://launcher/launcher/assistant";
    expect(isTrustedLauncherControlFrame(event)).toBe(false);
  });
});
