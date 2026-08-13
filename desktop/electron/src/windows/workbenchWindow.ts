import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

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
    titleBarStyle: "default",
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  return window;
}
