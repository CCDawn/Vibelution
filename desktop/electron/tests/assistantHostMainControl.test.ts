import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost, type AssistantHostOptions, type AssistantHostRequest } from "../src/assistant/assistantHost.js";
import type { WorkbenchJobHandle, WorkbenchJobSpawnInput } from "../src/process/workbenchJob.js";

const roots: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
function fixture(mainControl?: AssistantHostOptions["mainControl"], capability = true) {
  const root = mkdtempSync(join(tmpdir(), "assistant-control-host-")); roots.push(root);
  const python = join(root, "pythonw.exe"); writeFileSync(python, "never executed");
  const jobs = new Map<WorkbenchJobHandle, number>();
  let currentJob: WorkbenchJobHandle;
  const native = {
    spawn: vi.fn((input: WorkbenchJobSpawnInput) => {
      currentJob = {}; jobs.set(currentJob, 1);
      const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
      const instanceId = input.arguments[input.arguments.indexOf("--instance-id") + 1];
      writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant", instanceId, pid: 1234, port: 12345 }));
      return { pid: 1234, job: currentJob };
    }),
    terminate: vi.fn((job: WorkbenchJobHandle) => { jobs.set(job, 0); return true; }),
    activeCount: (job: WorkbenchJobHandle) => jobs.get(job) ?? 0,
    drainStatus: () => ({ complete: true, channels: [] }), close: vi.fn((job: WorkbenchJobHandle) => jobs.delete(job)),
  };
  let claimed = false;
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/health")) return Response.json({ status: "ok", role: "launcher_assistant", protocolVersion: 1, ...(capability ? { mainControlVersion: 1 } : {}) });
    if (path.endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "synthetic-agent", directSessionId: "synthetic-session" } });
    if (path.endsWith("/next")) {
      if (!claimed) { claimed = true; return Response.json({ schemaVersion: 1, request: { deliveryId: "a".repeat(32), action: "project_lifecycle", projectId: "synthetic-project", operation: "start", requestId: "synthetic-request" } }); }
      return await new Promise<Response>((_resolve, reject) => {
        const abort = () => reject(new Error("aborted"));
        if (init?.signal?.aborted) abort(); else init?.signal?.addEventListener("abort", abort, { once: true });
      });
    }
    if (path.endsWith("/settle")) return Response.json({ schemaVersion: 1, accepted: true });
    if (path.endsWith("/shutdown")) { jobs.set(currentJob, 0); return Response.json({ stopping: true }); }
    return Response.json({ accepted: true });
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"), sourceRoot: root,
    pythonPath: python, projects: { "synthetic-project": root }, native, fetch, mainControl });
  return { host, native, fetch };
}

describe("AssistantHost private main control pump", () => {
  it("keeps the host alive when the control pump fails during a migration fence", async () => {
    const f = fixture(vi.fn(async () => ({})));
    const original = f.fetch.getMockImplementation()!;
    let fail!: (error: Error) => void;
    f.fetch.mockImplementation(async (url, init) => String(url).endsWith("/main-control/next")
      ? await new Promise<Response>((_done, reject) => { fail = reject; }) : await original(url, init));
    await f.host.start();
    await vi.waitFor(() => expect(fail).toBeTypeOf("function"));
    const fence = f.host.beginMigrationAdmission();
    await fence.seal();
    fail(new Error("lost control channel"));
    await vi.waitFor(async () => await expect(f.host.migrationBarrier("prepare")).rejects.toThrow("ASSISTANT_NOT_READY"));
    expect(f.native.terminate).not.toHaveBeenCalled();
    expect(f.native.close).not.toHaveBeenCalled();
    fence.release();
    expect(() => f.host.beginMigrationAdmission()).toThrow("ASSISTANT_MIGRATION_BUSY");
    await f.host.stop();
  });

  it("waits for the actual admitted delivery before migration admission drains", async () => {
    let finish!: () => void;
    const mainControl = vi.fn(async () => { await new Promise<void>(done => { finish = done; }); return {}; });
    const f = fixture(mainControl);
    await f.host.start();
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    const fence = f.host.beginMigrationAdmission();
    let drained = false;
    void fence.drained.then(() => { drained = true; });
    await Promise.resolve();
    expect(drained).toBe(false);
    finish();
    await fence.drained;
    expect(drained).toBe(true);
    fence.release();
    await f.host.stop();
  });

  it("starts only a negotiated private capability and never exposes it to renderer requests", async () => {
    const mainControl = vi.fn(async () => ({ schemaVersion: 1, projectId: "synthetic-project", operation: "start", requestId: "synthetic-request", state: "unknown", code: "receipt_unavailable" }));
    const f = fixture(mainControl);
    try {
      await f.host.start();
      await vi.waitFor(() => expect(f.fetch.mock.calls.some(([url]) => String(url).endsWith("/settle"))).toBe(true));
      expect(mainControl).toHaveBeenCalledTimes(1);
      expect(f.native.spawn.mock.calls[0][0].env.VIBELUTION_ASSISTANT_MAIN_CONTROL).toBe("1");
      const settle = f.fetch.mock.calls.find(([url]) => String(url).endsWith("/settle"))!;
      const headers = settle[1]!.headers as Record<string, string>;
      expect(typeof headers.Authorization === "string" && headers.Authorization.startsWith("Bearer ")).toBe(true);
      await expect(f.host.request({ operation: "project_lifecycle", projectId: "synthetic-project" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    } finally { await f.host.stop(); }
  });

  it("does not inherit a control flag when no main owner exists", async () => {
    vi.stubEnv("VIBELUTION_ASSISTANT_MAIN_CONTROL", "1");
    const f = fixture();
    try {
      await f.host.start();
      expect(f.native.spawn.mock.calls[0][0].env.VIBELUTION_ASSISTANT_MAIN_CONTROL).toBeUndefined();
      expect(f.fetch.mock.calls.some(([url]) => String(url).includes("main-control"))).toBe(false);
    } finally { await f.host.stop(); }
  });

  it("refuses an incompatible child capability before delivering a main operation", async () => {
    const mainControl = vi.fn();
    const f = fixture(mainControl, false);
    await expect(f.host.start()).rejects.toThrow("ASSISTANT_MAIN_CONTROL_UNAVAILABLE");
    expect(mainControl).not.toHaveBeenCalled();
    expect(f.native.close).toHaveBeenCalledTimes(1);
  });

  it("does not cancel an admitted project command or send its late result into a restarted host", async () => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let completed = false;
    const mainControl = vi.fn(async () => { await gate; completed = true; return {}; });
    const f = fixture(mainControl);
    await f.host.start();
    await vi.waitFor(() => expect(mainControl).toHaveBeenCalledTimes(1));
    await f.host.stop(); await f.host.start();
    release(); await vi.waitFor(() => expect(completed).toBe(true));
    expect(f.fetch.mock.calls.some(([url]) => String(url).endsWith("/settle"))).toBe(false);
    await f.host.stop();
  });
});
