import { type BrowserWindow, dialog, screen } from "electron";
import type { DesktopPaths } from "../paths.js";
import { createPetWindow } from "../windows/petWindow.js";
import { desktopPetWindowExpandedBounds } from "../windows/petWindowBounds.js";
import type { AssistantHost } from "./assistantHost.js";
import { assertAssistantSender, invokeAssistant, LAUNCHER_ASSISTANT_URL, type WorkbenchSenderGate } from "./assistantBridge.js";
import type { ThemeSnapshot } from "./themeAuthority.js";
import { AssistantThemeControl, type AssistantThemeInput, type AssistantThemeResult } from "./assistantThemeControl.js";

/** Window visibility never owns the resident native runtime or remote tasks. */
export class AssistantWindow {
  private window: BrowserWindow | null = null;
  private opening: Promise<void> | null = null;
  private themeControl = new AssistantThemeControl();
  constructor(private paths: Pick<DesktopPaths, "desktopBundleRoot" | "userDataRoot">, private host: AssistantHost,
    private isQuitting: () => boolean = () => false,
    private openLauncher?: () => Promise<{ opened: boolean }>) {}

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
    // Hold the contents reference: once the window is destroyed, the
    // `webContents` getter itself throws, so the destroyed handler must not
    // reach back through the window.
    const contents = window.webContents;
    contents.on("did-start-navigation", (_event, _url, _isInPlace, isMainFrame) => {
      if (isMainFrame) this.themeControl.invalidate(contents);
    });
    contents.on("destroyed", () => this.themeControl.invalidate(contents));
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

  requestTheme(input: AssistantThemeInput, signal?: AbortSignal): Promise<AssistantThemeResult> {
    const window = this.window;
    if (!window || window.isDestroyed()) return Promise.resolve({ schemaVersion: 1, operation: input.operation, code: "unavailable" });
    return this.themeControl.request(window.webContents, input, signal);
  }

  isThemeSender(event: Parameters<typeof invokeAssistant>[0]): boolean {
    try { if (!this.window || this.window.isDestroyed()) return false; assertAssistantSender(event, this.window.webContents); return true; }
    catch { return false; }
  }

  publishTheme(snapshot: ThemeSnapshot, explicit = false): boolean {
    const window = this.window;
    if (!window || window.isDestroyed() || window.webContents.getURL() !== LAUNCHER_ASSISTANT_URL) return false;
    try { window.webContents.send("workbench:assistant-theme-changed", { snapshot, explicit }); return true; } catch { return false; }
  }

  /** Show a native fallback on the resident assistant, including when hidden. */
  async showReminder(notice: { title: string; body: string }): Promise<{ response: number }> {
    await this.open({ show: true });
    const window = this.window;
    if (this.isQuitting() || !window || window.isDestroyed()) throw new Error("ASSISTANT_WINDOW_UNAVAILABLE");
    return await dialog.showMessageBox(window, {
      type: "info", title: notice.title, message: notice.body || "已到期",
      buttons: ["打开助理", "稍后"], defaultId: 0, cancelId: 1, noLink: true,
    });
  }

  acceptThemeResult(event: Parameters<typeof invokeAssistant>[0], payload: unknown): boolean {
    return this.themeControl.acceptResult(event, payload);
  }

  /** Native user selection stays in main; paths never become renderer/model data. */
  async chooseOperatorImage(kind: "avatar" | "background", signal?: AbortSignal): Promise<string | null> {
    const window = this.window;
    if (!window || window.isDestroyed() || signal?.aborted || !["avatar", "background"].includes(kind)) return null;
    try {
      const result = await dialog.showOpenDialog(window, {
        title: kind === "avatar" ? "选择头像" : "选择背景图片",
        properties: ["openFile"], filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
      });
      if (signal?.aborted || window.isDestroyed() || this.window !== window || result.canceled || result.filePaths.length !== 1) return null;
      return result.filePaths[0] || null;
    } catch { return null; }
  }

  /** Geometry verbs stay float-bound: a full-size surface hides the float, never itself. */
  hideFloat(): void {
    if (this.window && !this.window.isDestroyed()) this.window.hide();
  }

  setFloatExpanded(expanded: boolean): { expanded: boolean; width: number; height: number } {
    const window = this.window;
    if (!window || window.isDestroyed()) return { expanded, width: 0, height: 0 };
    const current = window.getBounds();
    const bounds = desktopPetWindowExpandedBounds(current, screen.getDisplayMatching(current).workArea, expanded);
    window.setBounds(bounds, false);
    return { expanded, width: bounds.width, height: bounds.height };
  }

  /** isWorkbenchSender is the main-held identity gate for workbench main window callers. */
  invoke(event: Parameters<typeof invokeAssistant>[0], payload: unknown,
    isWorkbenchSender?: WorkbenchSenderGate): Promise<unknown> {
    const window = this.window;
    if (!window || window.isDestroyed()) return Promise.reject(new Error("ASSISTANT_WINDOW_UNAVAILABLE"));
    return invokeAssistant(event, payload, {
      contents: window.webContents, host: this.host,
      openLauncher: this.openLauncher,
      isWorkbenchSender,
      hide: () => this.hideFloat(),
      setExpanded: expanded => this.setFloatExpanded(expanded),
    });
  }
}
