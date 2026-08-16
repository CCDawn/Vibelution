import { Menu, Tray, nativeImage, type MenuItemConstructorOptions } from "electron";
import { resolveWorkspaceIconPath, type DesktopPaths } from "../paths.js";

export type TrayBranchInstance = {
  id: string;
  label: string;
  startable: boolean;
  stoppable: boolean;
};

export type DesktopTrayActions = {
  openLauncher: () => void;
  restartAll: () => void;
  quitAll: () => void;
};

export const DESKTOP_TRAY_MENU_LABELS = {
  restartAll: "全部重启",
  quitAll: "全部退出"
} as const;

export function buildDesktopTrayTemplate(actions: DesktopTrayActions): MenuItemConstructorOptions[] {
  return [
    { label: DESKTOP_TRAY_MENU_LABELS.restartAll, click: actions.restartAll },
    { label: DESKTOP_TRAY_MENU_LABELS.quitAll, click: actions.quitAll }
  ];
}

export function createDesktopTray(paths: DesktopPaths, actions: DesktopTrayActions): Tray {
  const tray = new Tray(nativeImage.createFromPath(resolveWorkspaceIconPath(paths)));
  tray.setToolTip("Vibelution");
  const menu = Menu.buildFromTemplate(buildDesktopTrayTemplate(actions));
  tray.setContextMenu(menu);

  const openLauncher = (): void => {
    actions.openLauncher();
  };

  tray.on("click", () => {
    openLauncher();
  });
  tray.on("double-click", () => {
    openLauncher();
  });
  tray.on("right-click", () => {
    tray.popUpContextMenu(menu);
  });

  return tray;
}
