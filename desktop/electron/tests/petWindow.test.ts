import { describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  options: {} as Record<string, unknown>,
  navigate: null as ((event: unknown, url: string) => void) | null,
  bounds: { x: 1602, y: 692, width: 300, height: 330 },
  setBounds: vi.fn(),
}));
vi.mock("electron", () => ({
  BrowserWindow: class {
    constructor(options: Record<string, unknown>) { fake.options = options; }
    webContents = { on: (_event: string, listener: typeof fake.navigate) => { fake.navigate = listener; } };
    setVisibleOnAllWorkspaces() {}
    on() {}
    getBounds() { return fake.bounds; }
    isDestroyed() { return false; }
    setBounds = fake.setBounds;
  },
  screen: {
    getPrimaryDisplay: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1040 } }),
    getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1040 } }),
  },
}));
vi.mock("node:fs", () => ({ mkdirSync: vi.fn(), readFileSync: () => { throw new Error("missing"); }, renameSync: vi.fn(), writeFileSync: vi.fn() }));
vi.mock("../src/paths.js", () => ({ resolvePreloadPath: () => "preload.js" }));

import { createPetWindow } from "../src/windows/petWindow.js";
import type { DesktopPaths } from "../src/paths.js";

const LAUNCHER_ASSISTANT_URL = "vibelution-launcher://launcher/launcher-assistant";
const paths = { userDataRoot: "test" } as DesktopPaths;

describe("desktop companion window", () => {
  it("keeps the native role and collapsed defaults, ignoring foreign navigations", () => {
    createPetWindow("http://127.0.0.1:8001/", paths);
    expect(fake.options).toMatchObject({ width: 300, height: 330, resizable: false, skipTaskbar: true,
      webPreferences: { additionalArguments: ["--vibelution-window-role=desktop-pet"] } });
    fake.bounds = { x: 1100, y: 440, width: 760, height: 600 };
    fake.navigate?.({}, "http://127.0.0.1:8001/chat");
    expect(fake.setBounds).not.toHaveBeenCalled();
  });
  it("resets expanded dimensions when the Launcher assistant surface reloads collapsed", () => {
    createPetWindow(LAUNCHER_ASSISTANT_URL, paths, undefined, "launcher-assistant");
    expect(fake.options).toMatchObject({ webPreferences: { additionalArguments: ["--vibelution-window-role=launcher-assistant"] } });
    fake.bounds = { x: 1100, y: 440, width: 760, height: 600 };
    fake.navigate?.({}, LAUNCHER_ASSISTANT_URL);
    expect(fake.setBounds).toHaveBeenLastCalledWith({ x: 1100, y: 440, width: 300, height: 330 }, false);
  });
});
