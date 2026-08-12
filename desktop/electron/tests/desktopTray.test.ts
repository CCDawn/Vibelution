import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopPaths } from "../src/paths.js";

const trayInstances: FakeTray[] = [];
const menuTemplates: Array<Array<Record<string, unknown>>> = [];
const iconPaths: string[] = [];

class FakeTray {
  readonly listeners = new Map<string, () => void>();
  tooltip = "";
  contextMenu: unknown = null;

  constructor(readonly icon: unknown) {
    trayInstances.push(this);
  }

  setToolTip(value: string): void {
    this.tooltip = value;
  }

  setContextMenu(value: unknown): void {
    this.contextMenu = value;
  }

  on(event: string, listener: () => void): void {
    this.listeners.set(event, listener);
  }

  emit(event: string): void {
    this.listeners.get(event)?.();
  }
}

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

describe("Electron desktop tray", () => {
  beforeEach(() => {
    trayInstances.length = 0;
    menuTemplates.length = 0;
    iconPaths.length = 0;
  });

  it("creates a persistent Vibelution tray icon with a tooltip", () => {
    const tray = createDesktopTray(desktopPaths, { openLauncher: vi.fn() });

    expect(trayInstances).toHaveLength(1);
    expect(tray).toBe(trayInstances[0]);
    expect(iconPaths).toEqual(["C:\\Users\\17533\\Desktop\\Vibelution\\assets\\icons\\vibelution.ico"]);
    expect(trayInstances[0].tooltip).toBe("Vibelution");
  });

  it("only opens Launcher from tray click or menu", () => {
    const openLauncher = vi.fn();
    const tray = createDesktopTray(desktopPaths, { openLauncher }) as unknown as FakeTray;

    tray.emit("click");
    const template = menuTemplates[0];
    (template[0].click as () => void)();

    expect(openLauncher).toHaveBeenCalledTimes(2);
    expect(template.map((item) => item.label ?? item.type)).toEqual(["打开 Vibelution Launcher"]);
  });
});
