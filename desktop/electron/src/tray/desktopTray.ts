import { Menu, Tray, nativeImage } from "electron";
import { resolveWorkspaceIconPath, type DesktopPaths } from "../paths.js";

export type DesktopTrayActions = {
  openLauncher: () => void;
  startProject: () => void;
  stopProject: () => void;
  restartProject: () => void;
  rebuildAndStart: () => void;
  showStatus: () => void;
  quit: () => void;
  stopAll: () => void;
};

export const DESKTOP_TRAY_MENU_LABELS = {
  openLauncher: "打开 Vibelution Launcher",
  startProject: "启动项目",
  stopProject: "停止项目",
  restartProject: "重启项目",
  rebuildAndStart: "重建并启动（最新）",
  showStatus: "状态",
  quit: "退出 Vibelution",
  stopAll: "停止全部"
} as const;

export function createDesktopTray(paths: DesktopPaths, actions: DesktopTrayActions): Tray {
  const tray = new Tray(nativeImage.createFromPath(resolveWorkspaceIconPath(paths)));
  tray.setToolTip("Vibelution");
  tray.on("click", actions.openLauncher);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: DESKTOP_TRAY_MENU_LABELS.openLauncher, click: actions.openLauncher },
      { type: "separator" },
      { label: DESKTOP_TRAY_MENU_LABELS.startProject, click: actions.startProject },
      { label: DESKTOP_TRAY_MENU_LABELS.stopProject, click: actions.stopProject },
      { label: DESKTOP_TRAY_MENU_LABELS.restartProject, click: actions.restartProject },
      { label: DESKTOP_TRAY_MENU_LABELS.rebuildAndStart, click: actions.rebuildAndStart },
      { label: DESKTOP_TRAY_MENU_LABELS.showStatus, click: actions.showStatus },
      { type: "separator" },
      { label: DESKTOP_TRAY_MENU_LABELS.quit, click: actions.quit },
      { label: DESKTOP_TRAY_MENU_LABELS.stopAll, click: actions.stopAll }
    ])
  );
  return tray;
}
