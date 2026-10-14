import { afterEach, describe, expect, it, vi } from "vitest";
import type { IpcMainInvokeEvent } from "electron";
import { requestRendererWindowClose } from "../src/windows/rendererWindowClose.js";

const originalArgv = process.argv;
afterEach(() => {
  process.argv = originalArgv;
  vi.unstubAllGlobals();
  vi.doUnmock("electron");
  vi.resetModules();
});

async function loadPreload(role?: string) {
  const nativeClose = vi.fn();
  const page: Record<string, any> = { close: nativeClose };
  const invoke = vi.fn(async () => ({ requested: true }));
  process.argv = originalArgv.filter(arg => !arg.startsWith("--vibelution-window-role="));
  if (role) process.argv.push(`--vibelution-window-role=${role}`);
  vi.stubGlobal("window", page);
  vi.doMock("electron", () => ({
    contextBridge: {
      exposeInMainWorld: (name: string, api: unknown) => { page[name] = api; },
      executeInMainWorld: ({ func }: { func: () => void }) => func()
    },
    ipcRenderer: { invoke, on: vi.fn(), removeListener: vi.fn(), send: vi.fn() },
    webUtils: { getPathForFile: vi.fn() }
  }));
  await import("../src/preload.js");
  return { page, nativeClose, invoke };
}

describe("renderer managed close", () => {
  it("routes window.close through the managed native close request", async () => {
    const { page, nativeClose, invoke } = await loadPreload();
    page.close();
    expect(nativeClose).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith("workbench:request-window-close");
  });

  it.each(["launcher-control", "desktop-pet"])("does not grant a workbench close bridge to %s", async role => {
    const { page, nativeClose, invoke } = await loadPreload(role);
    page.close();
    expect(nativeClose).toHaveBeenCalledOnce();
    expect(page.vibelutionLauncher.requestWindowClose).toBeUndefined();
    expect(invoke).not.toHaveBeenCalled();
  });

  it("rejects subframes before resolving or closing a native window", () => {
    const close = vi.fn();
    const resolve = vi.fn();
    const event = { senderFrame: {}, sender: { mainFrame: {} } } as unknown as IpcMainInvokeEvent;
    expect(() => requestRendererWindowClose(event, resolve, close)).toThrow("main frame");
    expect(resolve).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });

  it("passes only the sender's native window identity and URL", () => {
    const frame = { url: "http://127.0.0.1:8004/chat" };
    const event = { senderFrame: frame, sender: { mainFrame: frame } } as unknown as IpcMainInvokeEvent;
    const close = vi.fn();
    expect(requestRendererWindowClose(event, () => ({ id: 42, isDestroyed: () => false }), close))
      .toEqual({ requested: true });
    expect(close).toHaveBeenCalledWith(42, frame.url);
    expect(() => requestRendererWindowClose(event, () => null, close)).toThrow("unavailable");
  });
});
