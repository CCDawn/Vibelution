import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { closeOwnedWorkbenchFast, type FastWorkbenchCloseInput } from "../src/process/fastWorkbenchClose.js";
import type { GracefulWorkbenchShutdownResponse } from "../src/process/workbenchBackendRetire.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function fixture(overrides: Partial<FastWorkbenchCloseInput> = {}) {
  const retire = Object.assign(vi.fn(async () => true), { isCurrent: vi.fn(() => true) });
  const captureRetirement = vi.fn(() => retire);
  const connect = vi.fn(async () => false);
  const request = vi.fn<NonNullable<FastWorkbenchCloseInput["request"]>>(async (url) => {
    if (url.endsWith("/api/health")) return {
      status: 200, json: async () => ({ status: "ok", workspaceRoot: "C:\\repo\\" })
    };
    if (url.endsWith("/api/control-token")) return { status: 200, json: async () => ({ controlToken: "token" }) };
    return { status: 202 };
  });
  const input: FastWorkbenchCloseInput = {
    workspaceRoot: "C:/repo", spawnPid: 123, port: 8000,
    forceAt: 2_200, deadlineAt: 2_800,
    captureRetirement, connect, request, ...overrides
  };
  return { input, retire, captureRetirement, connect, request };
}

describe("fast owned workbench close", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1_000); });
  afterEach(() => { vi.useRealTimers(); });

  it("captures synchronously, verifies health, and posts explicit active-work close", async () => {
    const f = fixture();
    const closing = closeOwnedWorkbenchFast(f.input);
    expect(f.captureRetirement).toHaveBeenCalledWith("C:/repo", 123);
    await expect(closing).resolves.toBe(true);
    expect(f.request.mock.calls.map(([url]) => url.split("/").pop())).toEqual(["health", "control-token", "shutdown"]);
    const options = f.request.mock.calls[2][1];
    expect(options.headers).toEqual({ "X-Vibelution-Control-Token": "token", "Content-Type": "application/json" });
    expect(JSON.parse(options.body!)).toEqual({ source: "electron_user_close", reason: "user_close", interruptActiveWork: true });
    expect(f.retire).toHaveBeenCalledOnce();
    expect(f.connect).toHaveBeenCalledWith(8000, "127.0.0.1");
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["request", "json"])("forces on time when health %s never settles", async (wedged) => {
    const pending = deferred<GracefulWorkbenchShutdownResponse>();
    const f = fixture();
    f.request.mockImplementationOnce(() => wedged === "request" ? pending.promise : Promise.resolve({
      status: 200, json: () => new Promise(() => undefined)
    }));
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(1_199);
    expect(f.retire).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(closing).resolves.toBe(true);
    expect(f.request.mock.calls[0][1].signal.aborted).toBe(true);
    pending.resolve({ status: 200, json: async () => ({ status: "ok", workspaceRoot: "C:/repo" }) });
    await vi.advanceTimersByTimeAsync(0);
    expect(f.request).toHaveBeenCalledOnce();
  });

  it("uses the remaining absolute budget when invoked after forceAt", async () => {
    vi.setSystemTime(2_300);
    const f = fixture();
    const pending = deferred<boolean>();
    f.retire.mockImplementation(() => pending.promise);
    const closing = closeOwnedWorkbenchFast(f.input);
    expect(f.retire).toHaveBeenCalledOnce();
    expect(f.request).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(499);
    let settled = false;
    void closing.then(() => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(closing).resolves.toBe(false);
    pending.resolve(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.connect).not.toHaveBeenCalled();
  });

  it("does nothing without initial Job ownership or after an expired deadline", async () => {
    const f = fixture({ captureRetirement: () => null });
    await expect(closeOwnedWorkbenchFast(f.input)).resolves.toBe(false);
    expect(f.request).not.toHaveBeenCalled();
    expect(f.connect).not.toHaveBeenCalled();
    const expired = fixture({ deadlineAt: Date.now() });
    await expect(closeOwnedWorkbenchFast(expired.input)).resolves.toBe(false);
    expect(expired.captureRetirement).not.toHaveBeenCalled();
  });

  it("prevents late token completion from sending HTTP or killing after external abort", async () => {
    const controller = new AbortController();
    const token = deferred<unknown>();
    const f = fixture({ signal: controller.signal });
    f.request.mockImplementation(async (url) => url.endsWith("/api/health")
      ? { status: 200, json: async () => ({ status: "ok", workspaceRoot: "C:/repo" }) }
      : { status: 200, json: () => token.promise });
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.request).toHaveBeenCalledTimes(2);
    controller.abort();
    await expect(closing).resolves.toBe(false);
    token.resolve({ controlToken: "late" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(f.request).toHaveBeenCalledTimes(2);
    expect(f.retire).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("suppresses HTTP after the exact captured Job is replaced", async () => {
    const health = deferred<unknown>();
    const f = fixture();
    f.request.mockResolvedValueOnce({ status: 200, json: () => health.promise });
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(0);
    f.retire.isCurrent.mockReturnValue(false);
    health.resolve({ status: "ok", workspaceRoot: "C:/repo" });
    await vi.advanceTimersByTimeAsync(1_200);
    await expect(closing).resolves.toBe(true);
    // The captured retirement closure handles an already-released old Job;
    // replacement protection itself is exercised in workbenchJob.test.ts.
    expect(f.request).toHaveBeenCalledOnce();
    expect(f.captureRetirement).toHaveBeenCalledOnce();
  });

  it("does not send later HTTP after forceAt even before the force timer runs", async () => {
    const health = deferred<unknown>();
    const f = fixture();
    f.request.mockResolvedValueOnce({ status: 200, json: () => health.promise });
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(0);
    vi.setSystemTime(2_201);
    health.resolve({ status: "ok", workspaceRoot: "C:/repo" });
    await Promise.resolve();
    await Promise.resolve();
    expect(f.request).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1_800);
    await expect(closing).resolves.toBe(false);
    expect(f.retire).not.toHaveBeenCalled();
  });

  it("returns success when the accepted shutdown naturally released the captured Job", async () => {
    const f = fixture();
    f.request.mockImplementation(async (url) => {
      if (url.endsWith("/api/health")) return {
        status: 200, json: async () => ({ status: "ok", workspaceRoot: "C:/repo" })
      };
      if (url.endsWith("/api/control-token")) return { status: 200, json: async () => ({ controlToken: "token" }) };
      f.retire.isCurrent.mockReturnValue(false);
      return { status: 202 };
    });
    await expect(closeOwnedWorkbenchFast(f.input)).resolves.toBe(true);
    expect(f.retire).toHaveBeenCalledOnce();
    expect(Date.now()).toBe(1_000);
  });

  it("ignores retirement completion after external abort", async () => {
    const controller = new AbortController();
    const retired = deferred<boolean>();
    const f = fixture({ forceAt: 1_000, signal: controller.signal });
    f.retire.mockImplementation(() => retired.promise);
    const closing = closeOwnedWorkbenchFast(f.input);
    controller.abort();
    await expect(closing).resolves.toBe(false);
    retired.resolve(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(f.connect).not.toHaveBeenCalled();
    expect(f.retire).toHaveBeenCalledOnce();
  });

  it.each(["other-project", "unhealthy"])("never fetches a token or posts to %s health", async (kind) => {
    const f = fixture();
    f.request.mockResolvedValueOnce({ status: 200, json: async () => ({
      status: kind === "unhealthy" ? "starting" : "ok", workspaceRoot: "D:/other"
    }) });
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(1_200);
    await expect(closing).resolves.toBe(true);
    expect(f.request).toHaveBeenCalledOnce();
  });

  it.each(["false", "throws"])("fails closed when native retirement %s", async (failure) => {
    const f = fixture({ forceAt: 1_000 });
    f.retire.mockImplementation(async () => { if (failure === "throws") throw new Error("native failed"); return false; });
    await expect(closeOwnedWorkbenchFast(f.input)).resolves.toBe(false);
    expect(f.connect).not.toHaveBeenCalled();
  });

  it("requires a released TCP port after native success and keeps polling until then", async () => {
    const f = fixture({ forceAt: 1_000 });
    f.connect.mockResolvedValueOnce(true).mockResolvedValueOnce(true).mockResolvedValue(false);
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(50);
    await expect(closing).resolves.toBe(true);
    expect(f.connect).toHaveBeenCalledTimes(3);
  });

  it.each(["listening", "wedged", "throws"])("returns false by deadline with a %s TCP probe", async (failure) => {
    const f = fixture({ forceAt: 1_000 });
    f.connect.mockImplementation(async () => {
      if (failure === "wedged") return await new Promise(() => undefined);
      if (failure === "throws") throw new Error("probe failed");
      return true;
    });
    const closing = closeOwnedWorkbenchFast(f.input);
    await vi.advanceTimersByTimeAsync(1_800);
    await expect(closing).resolves.toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });
});
