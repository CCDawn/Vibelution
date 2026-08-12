import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

export function createWorkbenchWindow(_url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    show: false,
    title: instanceWindowTitle("workbench"),
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
