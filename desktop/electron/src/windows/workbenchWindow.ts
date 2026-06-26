import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath } from "../paths.js";

export function createWorkbenchWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    title: "Vibelution Workbench",
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
