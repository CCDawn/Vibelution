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
  return { openAssistant: vi.fn(), openLauncher: vi.fn(), stopAll: vi.fn(),
    listInstances: vi.fn(), getFreshness: vi.fn(), startInstance: vi.fn(), stopInstance: vi.fn(), restartLauncher: vi.fn() };
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

  it.skipIf(process.platform !== "win32")("creates a persistent Vibelution tray icon with a tooltip", () => {
    const tray = createDesktopTray(desktopPaths, createActions());
    expect(trayInstances).toHaveLength(1);
    expect(tray).toBe(trayInstances[0]);
    expect(iconPaths).toEqual(["C:\\Users\\17533\\Desktop\\Vibelution\\assets\\icons\\vibelution.ico"]);
    expect(trayInstances[0].tooltip).toBe("Vibelution");
  });

  it("offers exactly the two open actions and one exit action", () => {
    const actions = createActions();
    createDesktopTray(desktopPaths, actions);
    expect(topLabels(menuTemplates[0])).toEqual(["打开个人助理", "打开 Launcher 控制窗口", "separator", "退出"]);
    expect(DESKTOP_TRAY_MENU_LABELS.stopAll).toBe("退出");
    expect(menuTemplates[0].filter((item) => item.type !== "separator")).toHaveLength(3);
    expect(menuTemplates[0].some((item) => item.submenu)).toBe(false);
    (menuTemplates[0][0].click as () => void)();
    (menuTemplates[0][1].click as () => void)();
    expect(actions.openAssistant).toHaveBeenCalledOnce();
    expect(actions.openLauncher).toHaveBeenCalledOnce();
    expect(actions.stopAll).not.toHaveBeenCalled();
    (menuTemplates[0][3].click as () => void)();
    expect(actions.stopAll).toHaveBeenCalledOnce();
  });

  it("opens the same immediate menu on both mouse buttons without polling", () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    const actions = createActions();
    try {
      const tray = createDesktopTray(desktopPaths, actions) as unknown as InstanceType<typeof FakeTray>;
      tray.emit("click");
      tray.emit("right-click");
      expect(tray.poppedMenus).toEqual([tray.contextMenu, tray.contextMenu]);
      expect(menuTemplates).toHaveLength(1);
      expect(interval).not.toHaveBeenCalled();
      expect(actions.stopAll).not.toHaveBeenCalled();
      expect(actions.listInstances).not.toHaveBeenCalled();
      expect(actions.getFreshness).not.toHaveBeenCalled();
      expect(actions.restartLauncher).not.toHaveBeenCalled();
    } finally { interval.mockRestore(); }
  });

  it("can still open Launcher and exit when an assistant action is unavailable", () => {
    const actions = { ...createActions(), openAssistant: undefined };
    createDesktopTray(desktopPaths, actions);
    expect(topLabels(menuTemplates[0])).toEqual(["打开 Launcher 控制窗口", "separator", "退出"]);
  });
});
