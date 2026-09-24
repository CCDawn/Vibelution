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
  restartLauncher: () => void;
  stopAll: () => void;
};

export const DESKTOP_TRAY_MENU_LABELS = {
  openLauncher: "打开 Launcher 控制窗口",
  startProject: "启动工作区…",
  stopProject: "停止工作区…",
  restartLauncher: "全部停止并启动最新 Launcher",
  freshnessUnknown: "Launcher 代码版本：未知",
  freshnessLoading: "正在读取 Launcher 代码版本…",
  stopAll: "退出壳并停止全部任务",
  noStartable: "没有可启动的工作区",
  noRunning: "没有正在运行的工作区",
  listFailed: "无法读取工作区列表",
  listLoading: "正在读取工作区列表…"
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
    { type: "separator" },
    {
      label: DESKTOP_TRAY_MENU_LABELS.startProject,
      submenu: startable.length
        ? startable.map((item) => ({
            label: `启动「${item.label}」工作区`,
            click: () => actions.startInstance(item.id, item.label)
          }))
        : [{ label: emptyStartLabel, enabled: false }]
    },
    {
      label: DESKTOP_TRAY_MENU_LABELS.stopProject,
      submenu: stoppable.length
        ? stoppable.map((item) => ({
            label: `停止「${item.label}」工作区`,
            click: () => actions.stopInstance(item.id, item.label)
          }))
        : [{ label: emptyStopLabel, enabled: false }]
    },
    { type: "separator" },
    { label: DESKTOP_TRAY_MENU_LABELS.stopAll, click: actions.stopAll },
    { label: DESKTOP_TRAY_MENU_LABELS.restartLauncher, click: actions.restartLauncher }
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
