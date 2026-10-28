import { afterEach, describe, expect, it, vi } from "vitest";
import { launcherAssistantComputer as computer } from "./launcherAssistantComputer";

const idle = { available: true, status: "idle", message: "select", grantId: null, window: null, pending: null };
const target = { selectionId: "fake-selection", title: "Fake window", appName: "Fake app" };
afterEach(() => vi.unstubAllGlobals());

describe("Launcher computer operator transport", () => {
  it("uses only fixed IPC operations and preserves the selected window and explicit decisions", async () => {
    const invoke = vi.fn(async (request: { operation: string }) => request.operation === "computerWindows" ? { windows: [target] } : idle);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    expect(await computer.state()).toEqual(idle);
    expect(await computer.windows()).toEqual({ windows: [target] });
    await computer.grant({ selectionId: target.selectionId, allowVision: true });
    await computer.control({ grantId: "grant", action: "pause" });
    await computer.confirm({ grantId: "grant", pendingId: "pending", approved: false });
    expect(invoke.mock.calls.map(([request]) => request)).toEqual([
      { operation: "computerState" }, { operation: "computerWindows" },
      { operation: "computerGrant", selectionId: "fake-selection", allowVision: true },
      { operation: "computerControl", grantId: "grant", action: "pause" },
      { operation: "computerConfirm", grantId: "grant", pendingId: "pending", approved: false },
    ]);
  });
  it("fails closed for malformed responses and invalid operator inputs", async () => {
    const invoke = vi.fn().mockResolvedValue({ ...idle, pending: { id: "x", action: "click", targetLabel: "x", text: null } });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(computer.state()).rejects.toThrow();
    invoke.mockResolvedValue({ windows: [{ ...target, pid: 1 }] });
    await expect(computer.windows()).rejects.toThrow();
    await expect(computer.grant({ selectionId: "", allowVision: true })).rejects.toThrow();
    await expect(computer.control({ grantId: "g", action: "click" as never })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(2);
  });
  it("ignores late read results after a caller aborts", async () => {
    let resolve!: (value: unknown) => void;
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: () => new Promise(done => { resolve = done; }) });
    const abort = new AbortController();
    const pending = computer.state({ signal: abort.signal });
    abort.abort(); resolve(idle);
    await expect(pending).rejects.toBeDefined();
  });
});
