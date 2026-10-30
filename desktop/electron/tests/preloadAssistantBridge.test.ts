import { afterEach, describe, expect, it, vi } from "vitest";
import { IPC_CHANNELS } from "../src/ipc.js";

const originalArgv = process.argv;
afterEach(() => {
  process.argv = originalArgv;
  vi.doUnmock("electron");
  vi.resetModules();
});

/** Runs the real preload with an Electron stub; duplicate bridge names throw like the real contextBridge. */
async function loadPreload(role?: string) {
  const exposed = new Map<string, Record<string, unknown>>();
  const contextBridge = {
    exposeInMainWorld: (name: string, api: unknown) => {
      if (exposed.has(name)) throw new Error(`DUPLICATE_CONTEXT_BRIDGE_${name}`);
      exposed.set(name, api as Record<string, unknown>);
    },
    executeInMainWorld: vi.fn()
  };
  const invoke = vi.fn(async () => ({}));
  process.argv = originalArgv.filter(arg => !arg.startsWith("--vibelution-window-role="));
  if (role) process.argv.push(`--vibelution-window-role=${role}`);
  vi.doMock("electron", () => ({
    contextBridge,
    ipcRenderer: { invoke, on: vi.fn(), removeListener: vi.fn(), send: vi.fn() },
    webUtils: { getPathForFile: vi.fn() }
  }));
  await import("../src/preload.js");
  return { exposed, invoke };
}

type BridgeApi = Record<string, (payload?: unknown) => Promise<unknown>>;

describe("preload assistant bridge injection by window role", () => {
  it("grants the workbench main window the assistant and theme bridges exactly once", async () => {
    const { exposed, invoke } = await loadPreload("workbench-main");
    expect([...exposed.keys()].sort()).toEqual(
      ["vibelutionLauncher", "vibelutionLauncherAssistant", "vibelutionLauncherTheme"]);
    await (exposed.get("vibelutionLauncherAssistant") as BridgeApi).invoke({ operation: "status" });
    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.assistantInvoke, { operation: "status" });
    await (exposed.get("vibelutionLauncherTheme") as BridgeApi).respond({ deliveryId: "d" });
    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.assistantThemeResult, { deliveryId: "d" });
    expect(typeof exposed.get("vibelutionLauncherTheme")!.readThemeAuthority).toBe("function");
  });

  it("keeps the full workbench bridge on the same window without the pet drag subset", async () => {
    const { exposed } = await loadPreload("workbench-main");
    const bridge = exposed.get("vibelutionLauncher")!;
    expect(bridge.requestWindowClose).toBeTypeOf("function");
    expect(bridge.controlDesktopPet).toBeTypeOf("function");
    expect(bridge.setDesktopPetExpanded).toBeUndefined();
    expect(bridge.beginDesktopPetWindowDrag).toBeUndefined();
  });

  it("keeps the launcher-assistant float on the pet-subset bridge", async () => {
    const { exposed } = await loadPreload("launcher-assistant");
    expect([...exposed.keys()].sort()).toEqual(
      ["vibelutionLauncher", "vibelutionLauncherAssistant", "vibelutionLauncherTheme"]);
    const bridge = exposed.get("vibelutionLauncher")!;
    expect(bridge.setDesktopPetExpanded).toBeTypeOf("function");
    expect(bridge.beginDesktopPetWindowDrag).toBeTypeOf("function");
    expect(bridge.requestWindowClose).toBeUndefined();
  });

  it("grants the launcher control window the assistant and theme bridges beside its control bridge", async () => {
    const { exposed, invoke } = await loadPreload("launcher-control");
    expect([...exposed.keys()].sort()).toEqual(
      ["vibelutionLauncher", "vibelutionLauncherAssistant", "vibelutionLauncherTheme"]);
    await (exposed.get("vibelutionLauncherAssistant") as BridgeApi).invoke({ operation: "status" });
    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.assistantInvoke, { operation: "status" });
    expect(typeof exposed.get("vibelutionLauncherTheme")!.readThemeAuthority).toBe("function");
    const bridge = exposed.get("vibelutionLauncher")!;
    expect(bridge.launcherInvoke).toBeTypeOf("function");
    expect(bridge.refreshLauncherState).toBeTypeOf("function");
    expect(bridge.requestWindowClose).toBeUndefined();
  });

  it.each(["desktop-pet", undefined])("grants no assistant bridge to role %s", async role => {
    const { exposed } = await loadPreload(role);
    expect(exposed.has("vibelutionLauncherAssistant")).toBe(false);
    expect(exposed.has("vibelutionLauncherTheme")).toBe(false);
    expect(exposed.has("vibelutionLauncher")).toBe(true);
  });
});
