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
    startInstance: vi.fn(),
    stopInstance: vi.fn(),
    restartProject: vi.fn(),
    rebuildAndStart: vi.fn(),
    showStatus: vi.fn(),
    quit: vi.fn(),
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

  it("exposes start/stop as instance submenus and keeps the other tray actions", async () => {
    const actions = createActions();
    const tray = createDesktopTray(desktopPaths, actions) as unknown as InstanceType<typeof FakeTray>;

    expect(topLabels(menuTemplates[0])).toEqual([
      DESKTOP_TRAY_MENU_LABELS.openLauncher,
      "separator",
      DESKTOP_TRAY_MENU_LABELS.startProject,
      DESKTOP_TRAY_MENU_LABELS.stopProject,
      DESKTOP_TRAY_MENU_LABELS.restartProject,
      DESKTOP_TRAY_MENU_LABELS.rebuildAndStart,
      DESKTOP_TRAY_MENU_LABELS.showStatus,
      "separator",
      DESKTOP_TRAY_MENU_LABELS.quit,
      DESKTOP_TRAY_MENU_LABELS.stopAll
    ]);

    tray.emit("click");
    await vi.waitFor(() => {
      expect(menuTemplates.length).toBeGreaterThan(1);
    });

    const refreshed = menuTemplates[menuTemplates.length - 1];
    const startMenu = refreshed[2]?.submenu as Array<Record<string, unknown>>;
    const stopMenu = refreshed[3]?.submenu as Array<Record<string, unknown>>;
    expect(startMenu.map((item) => item.label)).toEqual(["task"]);
    expect(stopMenu.map((item) => item.label)).toEqual(["主"]);

    (startMenu[0].click as () => void)();
    (stopMenu[0].click as () => void)();
    (refreshed[0].click as () => void)();
    (refreshed[4].click as () => void)();
    (refreshed[5].click as () => void)();
    (refreshed[6].click as () => void)();
    (refreshed[8].click as () => void)();
    (refreshed[9].click as () => void)();

    expect(actions.startInstance).toHaveBeenCalledWith("worktree:task", "task");
    expect(actions.stopInstance).toHaveBeenCalledWith("main", "主");
    expect(actions.openLauncher).toHaveBeenCalledTimes(1);
    expect(actions.restartProject).toHaveBeenCalledTimes(1);
    expect(actions.rebuildAndStart).toHaveBeenCalledTimes(1);
    expect(actions.showStatus).toHaveBeenCalledTimes(1);
    expect(actions.quit).toHaveBeenCalledTimes(1);
    expect(actions.stopAll).toHaveBeenCalledTimes(1);
  });
});
