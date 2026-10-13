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
  return window;
}
