import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

/**
 * Identity registry for workbench main windows. The assistant invoke handler
 * admits senders by this exact webContents identity — never by URL prefix —
 * so a dynamic backend origin cannot widen the assistant bridge. Membership
 * lives in a WeakSet: destroyed windows drop out with garbage collection and
 * a destroyed webContents can no longer originate IPC events.
 */
const workbenchMainSenders = new WeakSet<object>();

export function isWorkbenchMainSender(sender: unknown): boolean {
  return typeof sender === "object" && sender !== null && workbenchMainSenders.has(sender);
}

export function createWorkbenchWindow(
  _url: string,
  paths: DesktopPaths,
  options?: { title?: string }
): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    show: false,
    title: options?.title?.trim() || instanceWindowTitle("workbench"),
    icon: resolveWorkspaceIconPath(paths),
    backgroundColor: "#f7fafc",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#00000000",
      height: 40
    },
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // The workbench main window carries the assistant preload branch so the
      // resident assistant surface can also run here at full size.
      additionalArguments: ["--vibelution-window-role=workbench-main"]
    }
  });
  workbenchMainSenders.add(window.webContents);
  return window;
}
