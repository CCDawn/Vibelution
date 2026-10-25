import { type BrowserWindow, screen } from "electron";
import type { DesktopPaths } from "../paths.js";
import { createPetWindow } from "../windows/petWindow.js";
import { desktopPetWindowExpandedBounds } from "../windows/petWindowBounds.js";
import type { AssistantHost } from "./assistantHost.js";
import { invokeAssistant, LAUNCHER_ASSISTANT_URL } from "./assistantBridge.js";

/** Window visibility never owns the resident native runtime or remote tasks. */
export class AssistantWindow {
  private window: BrowserWindow | null = null;
  private opening: Promise<void> | null = null;
  constructor(private paths: Pick<DesktopPaths, "desktopBundleRoot" | "userDataRoot">, private host: AssistantHost,
    private isQuitting: () => boolean = () => false) {}

  async open({ show = true }: { show?: boolean } = {}): Promise<void> {
    if (this.opening) {
      await this.opening;
      if (show && this.window && !this.window.isDestroyed()) this.window.showInactive();
      return;
    }
    if (this.window && !this.window.isDestroyed()) {
      if (show) this.window.showInactive();
      return;
    }
    const operation = this.create(show);
    this.opening = operation;
    try { await operation; }
    finally { if (this.opening === operation) this.opening = null; }
  }

  private async create(show: boolean): Promise<void> {
    const window = createPetWindow(LAUNCHER_ASSISTANT_URL, this.paths, undefined, "launcher-assistant");
    this.window = window;
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event, url) => {
      if (url !== LAUNCHER_ASSISTANT_URL) event.preventDefault();
    });
    window.on("close", event => { if (!this.isQuitting()) { event.preventDefault(); window.hide(); } });
    window.on("closed", () => { if (this.window === window) this.window = null; });
    try {
      await window.loadURL(LAUNCHER_ASSISTANT_URL);
      if (show && !window.isDestroyed()) window.showInactive();
    } catch {
      if (this.window === window) this.window = null;
      if (!window.isDestroyed()) window.destroy();
      throw new Error("ASSISTANT_WINDOW_FAILED");
    }
  }

  invoke(event: Parameters<typeof invokeAssistant>[0], payload: unknown): Promise<unknown> {
    const window = this.window;
    if (!window || window.isDestroyed()) return Promise.reject(new Error("ASSISTANT_WINDOW_UNAVAILABLE"));
    return invokeAssistant(event, payload, {
      contents: window.webContents, host: this.host,
      hide: () => window.hide(),
      setExpanded: expanded => {
        const current = window.getBounds();
        const bounds = desktopPetWindowExpandedBounds(current, screen.getDisplayMatching(current).workArea, expanded);
        window.setBounds(bounds, false);
        return { expanded, width: bounds.width, height: bounds.height };
      },
    });
  }
}
