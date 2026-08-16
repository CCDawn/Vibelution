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
    restartAll: vi.fn(),
    quitAll: vi.fn()
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

  it("uses only restart-all and quit-all tray labels", () => {
    expect(DESKTOP_TRAY_MENU_LABELS).toEqual({
      restartAll: "全部重启",
      quitAll: "全部退出"
    });
  });

  it("builds a two-item context menu and opens Launcher on left click", () => {
    const actions = createActions();
    const tray = createDesktopTray(desktopPaths, actions) as unknown as InstanceType<typeof FakeTray>;

    expect(topLabels(menuTemplates[0])).toEqual([
      DESKTOP_TRAY_MENU_LABELS.restartAll,
      DESKTOP_TRAY_MENU_LABELS.quitAll
    ]);

    tray.emit("click");
    tray.emit("double-click");
    tray.emit("right-click");

    expect(actions.openLauncher).toHaveBeenCalledTimes(2);
    expect(tray.poppedMenus).toHaveLength(1);

    (menuTemplates[0][0].click as () => void)();
    (menuTemplates[0][1].click as () => void)();
    expect(actions.restartAll).toHaveBeenCalledTimes(1);
    expect(actions.quitAll).toHaveBeenCalledTimes(1);
  });
});
