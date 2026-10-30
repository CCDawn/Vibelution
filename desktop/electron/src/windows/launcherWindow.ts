import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

/**
 * Identity registry for launcher control windows. The assistant invoke handler
 * admits these senders by exact webContents identity — never by URL prefix —
 * so a dynamic backend origin cannot widen the assistant bridge into the
 * launcher page. Membership lives in a WeakSet: destroyed windows drop out
 * with garbage collection and a destroyed webContents can no longer originate
 * IPC events.
 */
const launcherControlSenders = new WeakSet<object>();

export function isLauncherControlSender(sender: unknown): boolean {
  return typeof sender === "object" && sender !== null && launcherControlSenders.has(sender);
}

export function createLauncherWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: instanceWindowTitle("launcher"),
    icon: resolveWorkspaceIconPath(paths),
    backgroundColor: "#e9e9e9",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#00000000",
      height: 44
    },
    skipTaskbar: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: ["--vibelution-window-role=launcher-control"]
    }
  });
  void window.loadURL(url);
  launcherControlSenders.add(window.webContents);
  return window;
}
