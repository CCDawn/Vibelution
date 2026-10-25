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

import { createPetWindow, desktopPetWindowUrl, isDesktopPetWindowUrl } from "../src/windows/petWindow.js";
import type { DesktopPaths } from "../src/paths.js";

describe("desktop companion window", () => {
  it("converges every mode request on the unified assistant path and still recognizes the legacy pet path", () => {
    expect(desktopPetWindowUrl("http://127.0.0.1:8001/desktop-assistant?session=private#x")).toBe("http://127.0.0.1:8001/desktop-assistant");
    expect(desktopPetWindowUrl("http://127.0.0.1:8001/desktop-pet")).toBe("http://127.0.0.1:8001/desktop-assistant");
    expect(desktopPetWindowUrl("http://127.0.0.1:8001/chat?session=x")).toBe("http://127.0.0.1:8001/desktop-assistant");
    for (const path of ["/desktop-pet", "/desktop-assistant"]) expect(isDesktopPetWindowUrl(`http://127.0.0.1:8001${path}`)).toBe(true);
    for (const path of ["/desktop-assistant/nested", "/desktop-assistant/", "/chat", "/desktop-pet-evil"]) expect(isDesktopPetWindowUrl(`http://127.0.0.1:8001${path}`)).toBe(false);
    expect(isDesktopPetWindowUrl("broken")).toBe(false);
  });
  it("keeps the native role and resets expanded dimensions on a mode navigation", () => {
    createPetWindow("http://127.0.0.1:8001/desktop-assistant", { userDataRoot: "test" } as DesktopPaths);
    expect(fake.options).toMatchObject({ width: 300, height: 330, resizable: false, skipTaskbar: true,
      webPreferences: { additionalArguments: ["--vibelution-window-role=desktop-pet"] } });
    fake.bounds = { x: 1100, y: 440, width: 760, height: 600 };
    fake.navigate?.({}, "http://127.0.0.1:8001/desktop-pet");
    expect(fake.setBounds).toHaveBeenLastCalledWith({ x: 1100, y: 440, width: 300, height: 330 }, false);
  });
  it("reuses native geometry with a separate Launcher assistant preload role", () => {
    createPetWindow("vibelution-launcher://launcher/launcher-assistant", { userDataRoot: "test" } as DesktopPaths,
      undefined, "launcher-assistant");
    expect(fake.options).toMatchObject({ webPreferences: { additionalArguments: ["--vibelution-window-role=launcher-assistant"] } });
  });
});
