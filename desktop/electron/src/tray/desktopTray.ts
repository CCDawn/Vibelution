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
  openLauncher: () => void;
  listInstances: () => Promise<TrayBranchInstance[]>;
  getFreshness: () => Promise<TrayFreshness>;
  startInstance: (instanceId: string, label: string) => void;
  stopInstance: (instanceId: string, label: string) => void;
  restartProject: () => void;
  rebuildAndStart: () => void;
  restartLauncher: () => void;
  showStatus: () => void;
  quit: () => void;
  stopAll: () => void;
};

export const DESKTOP_TRAY_MENU_LABELS = {
  openLauncher: "打开 Vibelution Launcher",
  startProject: "启动",
  stopProject: "停止",
  restartProject: "重启当前 main",
  rebuildAndStart: "重建并启动（最新）",
  restartLauncher: "重启 Launcher",
  freshnessUnknown: "Launcher 版本未知",
  showStatus: "状态",
  quit: "退出 Vibelution",
  stopAll: "停止全部",
  noStartable: "没有可启动的实例",
  noRunning: "没有正在运行的实例",
  listFailed: "无法读取分支列表"
} as const;

export function buildDesktopTrayTemplate(
  instances: TrayBranchInstance[],
  actions: DesktopTrayActions,
  freshness: TrayFreshness = { current: null, label: DESKTOP_TRAY_MENU_LABELS.freshnessUnknown }
): MenuItemConstructorOptions[] {
  const startable = instances.filter((item) => item.startable);
  const stoppable = instances.filter((item) => item.stoppable);
  return [
    { label: DESKTOP_TRAY_MENU_LABELS.openLauncher, click: actions.openLauncher },
    { label: freshness.label || DESKTOP_TRAY_MENU_LABELS.freshnessUnknown, enabled: false },
    { label: DESKTOP_TRAY_MENU_LABELS.restartLauncher, click: actions.restartLauncher },
    { type: "separator" },
    {
      label: DESKTOP_TRAY_MENU_LABELS.startProject,
      submenu: startable.length
        ? startable.map((item) => ({
            label: item.label,
            click: () => actions.startInstance(item.id, item.label)
          }))
        : [{ label: DESKTOP_TRAY_MENU_LABELS.noStartable, enabled: false }]
    },
    {
      label: DESKTOP_TRAY_MENU_LABELS.stopProject,
      submenu: stoppable.length
        ? stoppable.map((item) => ({
            label: item.label,
            click: () => actions.stopInstance(item.id, item.label)
          }))
        : [{ label: DESKTOP_TRAY_MENU_LABELS.noRunning, enabled: false }]
    },
    { label: DESKTOP_TRAY_MENU_LABELS.restartProject, click: actions.restartProject },
    { label: DESKTOP_TRAY_MENU_LABELS.rebuildAndStart, click: actions.rebuildAndStart },
    { label: DESKTOP_TRAY_MENU_LABELS.showStatus, click: actions.showStatus },
    { type: "separator" },
    { label: DESKTOP_TRAY_MENU_LABELS.quit, click: actions.quit },
    { label: DESKTOP_TRAY_MENU_LABELS.stopAll, click: actions.stopAll }
  ];
}

export function createDesktopTray(paths: DesktopPaths, actions: DesktopTrayActions): Tray {
  const tray = new Tray(nativeImage.createFromPath(resolveWorkspaceIconPath(paths)));
  tray.setToolTip("Vibelution");

  const applyMenu = (instances: TrayBranchInstance[], freshness: TrayFreshness): Menu => {
    const menu = Menu.buildFromTemplate(buildDesktopTrayTemplate(instances, actions, freshness));
    tray.setContextMenu(menu);
    return menu;
  };

  const refreshMenu = async (show = false): Promise<void> => {
    const [instances, freshness] = await Promise.all([
      actions.listInstances().catch(() => []),
      actions.getFreshness().catch(() => ({
        current: null,
        label: DESKTOP_TRAY_MENU_LABELS.freshnessUnknown
      }))
    ]);
    const menu = applyMenu(instances, freshness);
    if (show) {
      tray.popUpContextMenu(menu);
    }
  };

  applyMenu([], { current: null, label: DESKTOP_TRAY_MENU_LABELS.freshnessUnknown });
  tray.on("click", () => {
    void refreshMenu(true);
  });
  tray.on("right-click", () => {
    void refreshMenu(true);
  });
  return tray;
}
