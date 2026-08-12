import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

export function createLauncherWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: instanceWindowTitle("launcher"),
    icon: resolveWorkspaceIconPath(paths),
    backgroundColor: "#f7fafc",
    titleBarStyle: "default",
    skipTaskbar: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
