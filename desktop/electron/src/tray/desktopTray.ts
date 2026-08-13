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
  freshnessLoading: "正在读取 Launcher 状态…",
  showStatus: "状态",
  quit: "退出 Vibelution",
  stopAll: "停止全部",
  noStartable: "没有可启动的实例",
  noRunning: "没有正在运行的实例",
  listFailed: "无法读取分支列表",
  listLoading: "正在读取分支列表…"
} as const;

export type DesktopTrayTemplateOptions = {
  listError?: boolean;
  listLoading?: boolean;
};

export function buildDesktopTrayTemplate(
  instances: TrayBranchInstance[],
  actions: DesktopTrayActions,
  freshness: TrayFreshness = { current: null, label: DESKTOP_TRAY_MENU_LABELS.freshnessUnknown },
  options: DesktopTrayTemplateOptions = {}
): MenuItemConstructorOptions[] {
  const startable = instances.filter((item) => item.startable);
  const stoppable = instances.filter((item) => item.stoppable);
  const emptyStartLabel = options.listLoading
    ? DESKTOP_TRAY_MENU_LABELS.listLoading
    : options.listError
      ? DESKTOP_TRAY_MENU_LABELS.listFailed
      : DESKTOP_TRAY_MENU_LABELS.noStartable;
  const emptyStopLabel = options.listLoading
    ? DESKTOP_TRAY_MENU_LABELS.listLoading
    : options.listError
      ? DESKTOP_TRAY_MENU_LABELS.listFailed
      : DESKTOP_TRAY_MENU_LABELS.noRunning;
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
        : [{ label: emptyStartLabel, enabled: false }]
    },
    {
      label: DESKTOP_TRAY_MENU_LABELS.stopProject,
      submenu: stoppable.length
        ? stoppable.map((item) => ({
            label: item.label,
            click: () => actions.stopInstance(item.id, item.label)
          }))
        : [{ label: emptyStopLabel, enabled: false }]
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
  let lastInstances: TrayBranchInstance[] = [];
  let lastFreshness: TrayFreshness = { current: null, label: DESKTOP_TRAY_MENU_LABELS.freshnessLoading };
  let refreshInFlight: Promise<Menu> | null = null;

  const applyMenu = (
    instances: TrayBranchInstance[],
    freshness: TrayFreshness,
    options: DesktopTrayTemplateOptions = {}
  ): Menu => {
    const menu = Menu.buildFromTemplate(buildDesktopTrayTemplate(instances, actions, freshness, options));
    tray.setContextMenu(menu);
    return menu;
  };

  const refreshMenu = async (show = false): Promise<void> => {
    if (refreshInFlight === null) {
      refreshInFlight = (async () => {
        const listed = await Promise.allSettled([actions.listInstances(), actions.getFreshness()]);
        const listResult = listed[0];
        const freshnessResult = listed[1];
        const listError = listResult.status === "rejected";
        if (listResult.status === "fulfilled") {
          lastInstances = listResult.value;
        }
        if (freshnessResult.status === "fulfilled") {
          lastFreshness = freshnessResult.value;
        } else if (!lastFreshness.label || lastFreshness.label === DESKTOP_TRAY_MENU_LABELS.freshnessLoading) {
          lastFreshness = { current: null, label: DESKTOP_TRAY_MENU_LABELS.freshnessUnknown };
        }
        return applyMenu(lastInstances, lastFreshness, { listError });
      })().finally(() => {
        refreshInFlight = null;
      });
    }
    const menu = await refreshInFlight;
    if (show) {
      tray.popUpContextMenu(menu);
    }
  };

  applyMenu([], lastFreshness, { listLoading: true });
  void refreshMenu(false);
  const refreshTimer = setInterval(() => {
    void refreshMenu(false);
  }, 8000);
  const preventAndRefresh = (event?: unknown): void => {
    if (
      event &&
      typeof event === "object" &&
      "preventDefault" in event &&
      typeof event.preventDefault === "function"
    ) {
      event.preventDefault();
    }
    void refreshMenu(true);
  };
  tray.on("click", (event) => {
    preventAndRefresh(event);
  });
  tray.on("right-click", (event) => {
    preventAndRefresh(event);
  });
  void refreshTimer;
  return tray;
}
