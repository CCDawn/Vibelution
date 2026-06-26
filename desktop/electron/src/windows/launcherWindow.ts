import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";

export function createLauncherWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    icon: resolveWorkspaceIconPath(paths),
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
