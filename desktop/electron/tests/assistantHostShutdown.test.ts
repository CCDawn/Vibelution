/** Shutdown admission uses only fake Jobs and fetches; no host process is started. */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost } from "../src/assistant/assistantHost.js";
import type { WorkbenchJobHandle, WorkbenchJobSpawnInput } from "../src/process/workbenchJob.js";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
}

const fixtures: ReturnType<typeof fixture>[] = [];
function fixture(startupSignal?: AbortSignal, onShutdown?: () => Promise<void>,
  startupRead?: (url: string, init?: RequestInit) => Promise<Response | undefined>) {
  const root = mkdtempSync(join(tmpdir(), "assistant-shutdown-test-"));
  const pythonPath = join(root, "pythonw.exe");
  writeFileSync(pythonPath, "fake executable - never launched");
  const active = new Map<WorkbenchJobHandle, number>();
  let currentJob: WorkbenchJobHandle;
  let drained = true;
  const native = {
    spawn: vi.fn((input: WorkbenchJobSpawnInput) => {
      currentJob = {};
      active.set(currentJob, 1);
      const directory = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
      const instanceId = input.arguments[input.arguments.indexOf("--instance-id") + 1];
      writeFileSync(join(directory, "ready.json"), JSON.stringify({ protocolVersion: 1,
        role: "launcher_assistant", instanceId, pid: 900, port: 12_345 }));
      return { pid: 100, job: currentJob };
    }),
    terminate: vi.fn((job: WorkbenchJobHandle) => { active.set(job, 0); return true; }),
    activeCount: vi.fn((job: WorkbenchJobHandle) => active.get(job) ?? 0),
    drainStatus: vi.fn(() => ({ complete: drained, channels: [] })),
    exitCode: vi.fn((job: WorkbenchJobHandle) => active.get(job) === 0 ? 0 : null),
    close: vi.fn((job: WorkbenchJobHandle) => { active.delete(job); }),
  };
  const fetch = vi.fn(async (url: Parameters<typeof globalThis.fetch>[0], init?: RequestInit): Promise<Response> => {
    if (startupRead && (String(url).endsWith("/health") || String(url).endsWith("/api/assistant"))) {
      const response = await startupRead(String(url), init);
      if (response) return response;
    }
    if (String(url).endsWith("/health")) return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant" });
    if (String(url).endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "a", directSessionId: "s" } });
    if (String(url).endsWith("/shutdown")) {
      const job = currentJob;
      await onShutdown?.();
      active.set(job, 0);
      return Response.json({ stopping: true });
    }
    throw new Error("unexpected fake request");
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"),
    sourceRoot: root, pythonPath, projects: {}, native, fetch, startupSignal });
  const result = { root, host, native, active, fetch, setDrained: (value: boolean) => { drained = value; } };
  fixtures.push(result);
  return result;
}

afterEach(async () => {
  vi.useRealTimers();
  for (const { root, host, active, setDrained } of fixtures.splice(0)) {
    setDrained(true);
    for (const job of active.keys()) active.set(job, 0);
    await host.stop();
    if (!resolve(root).startsWith(resolve(tmpdir()) + sep)) throw new Error("test temp path escaped");
    rmSync(root, { recursive: true, force: true });
  }
});

describe("assistant owner shutdown admission", () => {
  it.each(["start", "startForMigration"] as const)("rejects %s before spawning when its owner already stopped", async operation => {
    const controller = new AbortController();
    controller.abort();
    const { host, native } = fixture(controller.signal);
    await expect(host[operation]()).rejects.toThrow("ASSISTANT_STOPPED");
    expect(native.spawn).not.toHaveBeenCalled();
  });

  it("does not restart a migration waiter when admission releases after owner shutdown", async () => {
    const controller = new AbortController();
    const { host, native } = fixture(controller.signal);
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    const outcome = host.start().then(() => "ready", error => error.message);
    controller.abort();
    const stopped = host.stop();
    admission.release();
    await stopped;
    expect(await outcome).toBe("ASSISTANT_STOPPED");
    expect(native.spawn).toHaveBeenCalledOnce();
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
  });

  it("rejects a start queued behind stop when its owner aborts before that start runs", async () => {
    const controller = new AbortController();
    const stopping = deferred(), allowStop = deferred();
    const { host, native } = fixture(controller.signal, async () => { stopping.resolve(); await allowStop.promise; });
    await host.start();
    const stopped = host.stop();
    await stopping.promise;
    const outcome = host.start().then(() => "ready", error => error.message);
    controller.abort();
    allowStop.resolve();
    await stopped;
    expect(await outcome).toBe("ASSISTANT_STOPPED");
    expect(native.spawn).toHaveBeenCalledOnce();
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
  });

  it("still gracefully stops and drains the captured active generation after owner abort", async () => {
    const controller = new AbortController();
    const { host, native, fetch, active } = fixture(controller.signal);
    await host.start();
    controller.abort();
    await expect(host.stop()).resolves.toEqual({ state: "stopped", errorCode: null });
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(1);
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
    expect(active.size).toBe(0);
  });

  it("waits for existing output retirement before rejecting a cancelled replacement", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const { host, native, active, setDrained } = fixture(controller.signal);
    await host.start();
    for (const job of active.keys()) active.set(job, 0);
    setDrained(false);
    let settled = false;
    const outcome = host.start().then(() => { settled = true; return "ready"; }, error => { settled = true; return error.message; });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await vi.advanceTimersByTimeAsync(50);
    expect(settled).toBe(false);
    expect(native.close).not.toHaveBeenCalled();
    setDrained(true);
    await vi.advanceTimersByTimeAsync(20);
    expect(await outcome).toBe("ASSISTANT_STOPPED");
    expect(native.spawn).toHaveBeenCalledOnce();
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
  });

  it.each(["/health", "/api/assistant"])("cancels a pending startup %s read without skipping the captured output drain", async path => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const reading = deferred();
    let readSignal: AbortSignal | null | undefined;
    const { host, native, active, setDrained } = fixture(controller.signal, undefined, async (url, init) => {
      if (!url.endsWith(path)) return undefined;
      readSignal = init?.signal;
      reading.resolve();
      return new Promise<Response>((_resolve, reject) => {
        const abort = () => reject(readSignal?.reason ?? new Error("fake read aborted"));
        readSignal?.addEventListener("abort", abort, { once: true });
        if (readSignal?.aborted) abort();
      });
    });
    let settled = false;
    const outcome = host.start().then(() => { settled = true; return "ready"; }, error => { settled = true; return error.message; });
    await reading.promise;
    // A naturally exited Job still owns its unread output. Cancelling the
    // startup read must not make that output drain look complete.
    for (const job of active.keys()) active.set(job, 0);
    setDrained(false);
    controller.abort();
    expect(readSignal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(50);
    expect(host.snapshot().state).not.toBe("ready");
    expect(native.drainStatus).toHaveBeenCalled();
    expect(settled).toBe(false);
    expect(native.close).not.toHaveBeenCalled();
    setDrained(true);
    await vi.advanceTimersByTimeAsync(20);
    expect(await outcome).toBe("ASSISTANT_STOPPED");
    expect(native.spawn).toHaveBeenCalledOnce();
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
  });

  it("preserves start-stop-start when no owner signal was supplied", async () => {
    const { host, native } = fixture();
    await host.start();
    const stopped = host.stop();
    const replacement = host.start();
    await stopped;
    await expect(replacement).resolves.toEqual({ state: "ready", errorCode: null });
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(native.close).toHaveBeenCalledOnce();
    expect(native.terminate).not.toHaveBeenCalled();
  });
});
