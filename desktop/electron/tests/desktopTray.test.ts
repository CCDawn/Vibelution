import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopPaths } from "../src/paths.js";
import { DESKTOP_TRAY_MENU_LABELS } from "../src/tray/desktopTray.js";

const { FakeTray, trayInstances, menuTemplates, iconPaths } = vi.hoisted(() => {
  const trayInstances: FakeTray[] = [];
  const menuTemplates: Array<Array<Record<string, unknown>>> = [];
  const iconPaths: string[] = [];

  class FakeTray {
    readonly listeners = new Map<string, () => void>();
    tooltip = "";
    contextMenu: unknown = null;
    poppedMenus: unknown[] = [];

    constructor(readonly icon: unknown) {
      trayInstances.push(this);
    }

    setToolTip(value: string): void {
      this.tooltip = value;
    }

    setContextMenu(value: unknown): void {
      this.contextMenu = value;
    }

    popUpContextMenu(value?: unknown): void {
      this.poppedMenus.push(value ?? this.contextMenu);
    }

    on(event: string, listener: () => void): void {
      this.listeners.set(event, listener);
    }

    emit(event: string): void {
      this.listeners.get(event)?.();
    }
  }

  return { FakeTray, trayInstances, menuTemplates, iconPaths };
});

vi.mock("electron", () => ({
  Menu: {
    buildFromTemplate: vi.fn((template: Array<Record<string, unknown>>) => {
      menuTemplates.push(template);
      return { template };
    })
  },
  Tray: FakeTray,
  nativeImage: {
    createFromPath: vi.fn((path: string) => {
      iconPaths.push(path);
      return { path };
    })
  }
}));

const { createDesktopTray } = await import("../src/tray/desktopTray.js");

const desktopPaths: DesktopPaths = {
  schemaVersion: 1,
  desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
  resourcesRoot: "C:/Program Files/Vibelution/resources",
  workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
  userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
};

function createActions() {
  return {
    openLauncher: vi.fn(),
    listInstances: vi.fn().mockResolvedValue([
      { id: "main", label: "主", startable: false, stoppable: true },
      { id: "worktree:task", label: "task", startable: true, stoppable: false }
    ]),
    getFreshness: vi.fn().mockResolvedValue({ current: false, label: "Launcher 落后本地 main · aaa111 → bbb222" }),
    startInstance: vi.fn(),
    stopInstance: vi.fn(),
    restartLauncher: vi.fn(),
    stopAll: vi.fn()
  };
}

function topLabels(template: Array<Record<string, unknown>>): string[] {
  return template.map((item) => String(item.label ?? item.type));
}

describe("Electron desktop tray", () => {
  beforeEach(() => {
    trayInstances.length = 0;
    menuTemplates.length = 0;
    iconPaths.length = 0;
  });

  it("creates a persistent Vibelution tray icon with a tooltip", () => {
    const tray = createDesktopTray(desktopPaths, createActions());

    expect(trayInstances).toHaveLength(1);
    expect(tray).toBe(trayInstances[0]);
    expect(iconPaths).toEqual(["C:\\Users\\17533\\Desktop\\Vibelution\\assets\\icons\\vibelution.ico"]);
    expect(trayInstances[0].tooltip).toBe("Vibelution");
  });

  it("uses launcher-centric tray labels without direct main-workbench restart actions", () => {
    expect(DESKTOP_TRAY_MENU_LABELS).toEqual({
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
    });
  });

  it("exposes start/stop submenus and launcher lifecycle actions only", async () => {
    const actions = createActions();
    const tray = createDesktopTray(desktopPaths, actions) as unknown as InstanceType<typeof FakeTray>;

    expect(topLabels(menuTemplates[0])).toEqual([
      DESKTOP_TRAY_MENU_LABELS.openLauncher,
      DESKTOP_TRAY_MENU_LABELS.freshnessLoading,
      "separator",
      DESKTOP_TRAY_MENU_LABELS.startProject,
      DESKTOP_TRAY_MENU_LABELS.stopProject,
      "separator",
      DESKTOP_TRAY_MENU_LABELS.stopAll,
      DESKTOP_TRAY_MENU_LABELS.restartLauncher
    ]);

    await vi.waitFor(() => {
      expect(menuTemplates.length).toBeGreaterThan(1);
    });
    tray.emit("click");
    await vi.waitFor(() => {
      expect(menuTemplates.length).toBeGreaterThan(2);
    });

    const refreshed = menuTemplates[menuTemplates.length - 1];
    expect(refreshed[1]?.label).toBe("Launcher 落后本地 main · aaa111 → bbb222");
    expect(refreshed[1]?.enabled).toBe(false);
    const startMenu = refreshed[3]?.submenu as Array<Record<string, unknown>>;
    const stopMenu = refreshed[4]?.submenu as Array<Record<string, unknown>>;
    expect(startMenu.map((item) => item.label)).toEqual(["启动「task」工作区"]);
    expect(stopMenu.map((item) => item.label)).toEqual(["停止「主」工作区"]);

    (startMenu[0].click as () => void)();
    (stopMenu[0].click as () => void)();
    (refreshed[0].click as () => void)();
    (refreshed[6].click as () => void)();
    (refreshed[7].click as () => void)();

    expect(actions.startInstance).toHaveBeenCalledWith("worktree:task", "task");
    expect(actions.stopInstance).toHaveBeenCalledWith("main", "主");
    expect(actions.openLauncher).toHaveBeenCalledTimes(1);
    expect(actions.stopAll).toHaveBeenCalledTimes(1);
    expect(actions.restartLauncher).toHaveBeenCalledTimes(1);
  });

  it("keeps the last readable list and marks a fetch failure instead of an empty menu", async () => {
    const actions = createActions();
    actions.listInstances
      .mockResolvedValueOnce([
        { id: "main", label: "main", startable: false, stoppable: true }
      ])
      .mockRejectedValueOnce(new Error("launcher backend is not available"));
    actions.getFreshness
      .mockResolvedValueOnce({ current: true, label: "Launcher 已是最新 · abc123" })
      .mockRejectedValueOnce(new Error("launcher backend is not available"));

    createDesktopTray(desktopPaths, actions);
    await vi.waitFor(() => {
      expect(menuTemplates.length).toBeGreaterThan(1);
    });
    const firstLive = menuTemplates[menuTemplates.length - 1];
    expect((firstLive[4]?.submenu as Array<Record<string, unknown>>).map((item) => item.label)).toEqual([
      "停止「main」工作区"
    ]);

    const tray = trayInstances[0];
    tray.emit("right-click");
    await vi.waitFor(() => {
      expect(menuTemplates.length).toBeGreaterThan(2);
    });
    const failed = menuTemplates[menuTemplates.length - 1];
    expect(failed[1]?.label).toBe("Launcher 已是最新 · abc123");
    expect((failed[4]?.submenu as Array<Record<string, unknown>>).map((item) => item.label)).toEqual([
      "停止「main」工作区"
    ]);
  });
});
