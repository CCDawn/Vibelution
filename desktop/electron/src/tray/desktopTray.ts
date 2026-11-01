import { Menu, Tray, nativeImage, type MenuItemConstructorOptions } from "electron";
import { resolveWorkspaceIconPath, type DesktopPaths } from "../paths.js";

export type TrayBranchInstance = {
  id: string;
  label: string;
  startable: boolean;
  stoppable: boolean;
};

export type TrayFreshness = {
  current: boolean | null;
  label: string;
};

export type DesktopTrayActions = {
  openAssistant?: () => void;
  openLauncher: () => void;
  listInstances: () => Promise<TrayBranchInstance[]>;
  getFreshness: () => Promise<TrayFreshness>;
  startInstance: (instanceId: string, label: string) => void;
  stopInstance: (instanceId: string, label: string) => void;
  restartLauncher: () => void;
  stopAll: () => void;
};

export const DESKTOP_TRAY_MENU_LABELS = {
  openAssistant: "打开个人助理",
  openLauncher: "打开 Launcher 控制窗口",
  stopAll: "退出"
} as const;

export function buildDesktopTrayTemplate(actions: DesktopTrayActions): MenuItemConstructorOptions[] {
  return [
    ...(actions.openAssistant ? [{ label: DESKTOP_TRAY_MENU_LABELS.openAssistant, click: actions.openAssistant }] : []),
    { label: DESKTOP_TRAY_MENU_LABELS.openLauncher, click: actions.openLauncher },
    { type: "separator" },
    { label: DESKTOP_TRAY_MENU_LABELS.stopAll, click: actions.stopAll }
  ];
}

export function createDesktopTray(paths: DesktopPaths, actions: DesktopTrayActions): Tray {
  const tray = new Tray(nativeImage.createFromPath(resolveWorkspaceIconPath(paths)));
  tray.setToolTip("Vibelution");
  const menu = Menu.buildFromTemplate(buildDesktopTrayTemplate(actions));
  tray.setContextMenu(menu);
  const showMenu = (event?: unknown): void => {
    if (event && typeof event === "object" && "preventDefault" in event && typeof event.preventDefault === "function") {
      event.preventDefault();
    }
    tray.popUpContextMenu(menu);
  };
  tray.on("click", showMenu);
  tray.on("right-click", showMenu);
  return tray;
}
