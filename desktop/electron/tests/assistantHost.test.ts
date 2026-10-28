/** Fake-Job coverage for the Launcher-owned assistant source-host lifecycle. */
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost, type AssistantHostRequest } from "../src/assistant/assistantHost.js";
import { affairsSyncMigrationId } from "../src/assistant/mainControlTransport.js";
import { applyDesktopLaunchSettingsToEnvironment } from "../src/launch/desktopLaunchSettings.js";
import type { WorkbenchJobHandle, WorkbenchJobSpawnInput } from "../src/process/workbenchJob.js";

const tempRoots: string[] = [];
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  for (const root of tempRoots.splice(0)) {
    if (!resolve(root).startsWith(resolve(tmpdir()))) throw new Error("test temp path escaped");
    rmSync(root, { recursive: true, force: true });
  }
});

function fixture(options: { stale?: boolean; noReadyFirst?: boolean; graceful?: boolean; pythonArguments?: string[]; env?: NodeJS.ProcessEnv; projectsSuspended?: boolean; initialMigrationControl?: boolean } = {}) {
  const root = mkdtempSync(join(tmpdir(), "assistant-host-test-"));
  tempRoots.push(root);
  const python = join(root, "pythonw.exe");
  writeFileSync(python, "fake executable - never launched");
  const inputs: WorkbenchJobSpawnInput[] = [];
  const active = new Map<WorkbenchJobHandle, number>();
  let currentJob: WorkbenchJobHandle;
  const native = {
    spawn: vi.fn((input: WorkbenchJobSpawnInput) => {
      inputs.push(input);
      currentJob = {};
      active.set(currentJob, 1);
      if (!(options.noReadyFirst && inputs.length === 1)) {
        const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
        const generation = input.arguments[input.arguments.indexOf("--instance-id") + 1];
        writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant",
          instanceId: options.stale ? "old-generation" : generation, pid: 900, port: 12_345 }));
      }
      return { pid: 100, job: currentJob };
    }),
    terminate: vi.fn((job: WorkbenchJobHandle) => { active.set(job, 0); return true; }),
    activeCount: vi.fn((job: WorkbenchJobHandle) => active.get(job) ?? 0),
    drainStatus: vi.fn(() => ({ complete: true, channels: [] })),
    close: vi.fn((job: WorkbenchJobHandle) => { active.delete(job); }),
  };
  const fetchImpl = vi.fn(async (...args: Parameters<typeof globalThis.fetch>): Promise<Response> => {
    const url = String(args[0]);
    if (url.endsWith("/health")) return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant",
      ...(options.initialMigrationControl ? { initialMigrationControlVersion: 1 } : {}) });
    if (url.endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" } });
    if (url.endsWith("/api/assistant/session")) return Response.json({ id: "s", messages: [] });
    if (url.endsWith("/shutdown")) {
      if (options.graceful) active.set(currentJob, 0);
      return Response.json({ stopping: true });
    }
    return Response.json({ accepted: true });
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"),
    sourceRoot: root, pythonPath: python, pythonArguments: options.pythonArguments, projects: { project: root }, projectsSuspended: options.projectsSuspended, initialMigrationControl: options.initialMigrationControl, native, fetch: fetchImpl,
    env: { VIBELUTION_CONFIG_PATH: join(root, "config.toml"), ...options.env, VIBELUTION_ASSISTANT_TOKEN: "must-not-override-token" } });
  return { host, native, fetchImpl, inputs, root, active };
}

describe("AssistantHost", () => {
  it("resolves a main-only source identity and rejects stale or forged responses", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const identity = { schemaVersion: 1, projectId: "project", revision: 0,
      sourceScope: { projectId: "source", instanceId: "instance", agentId: "agent" },
      sourceIdentityDigest: "a".repeat(64), authorityDigest: "b".repeat(64),
      projectDirectory: { device: "1", inode: "2", birthtimeNs: "3" } };
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/legacy-reminders\/source$/);
      expect(JSON.parse(String(options?.body))).toEqual({ projectId: "project", revision: 0 });
      expect(new Headers(options?.headers).get("authorization")).toMatch(/^Bearer /);
      return Response.json(identity);
    });
    await expect(host.resolveLegacyReminderIdentity("project", 0)).resolves.toEqual(identity);
    fetchImpl.mockResolvedValueOnce(Response.json({ ...identity, path: "forged" }));
    await expect(host.resolveLegacyReminderIdentity("project", 0)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    await expect(host.request({ operation: "legacy-reminders/source" } as never)).rejects.toThrow();
    let release!: (value: Response) => void;
    fetchImpl.mockImplementationOnce(async () => await new Promise<Response>(resolve => { release = resolve; }));
    const pending = host.resolveLegacyReminderIdentity("project", 0);
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 0, projectsSuspended: true }));
    const suspended = host.suspendProjects();
    release(Response.json(identity));
    await expect(pending).rejects.toThrow("ASSISTANT_NOT_READY");
    await suspended;
    await host.stop();
  });

  it("keeps legacy receipt attempts on the main-only private transport and validates replies", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const request = { sourceKey: "a".repeat(64), eventId: "affair-reminder:test:20261028" };
    const eventKey = "legacy:" + createHash("sha256").update(JSON.stringify([request.sourceKey, request.eventId]), "ascii").digest("hex");
    const token = "b".repeat(64);
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/legacy-reminders\/reserve$/);
      expect(JSON.parse(String(options?.body))).toEqual(request);
      return Response.json({ schemaVersion: 1, eventKey, state: "reserved", attemptToken: token });
    });
    expect(await host.reserveLegacyReminder(request)).toMatchObject({ eventKey, attemptToken: token });
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, eventKey, state: "submitted", channel: "system_notification" }));
    expect(await host.settleLegacyReminder({ ...request, attemptToken: token, channel: "system_notification" }))
      .toMatchObject({ state: "submitted" });
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/legacy-reminders\/abandon$/);
      expect(JSON.parse(String(options?.body))).toEqual({ ...request, attemptToken: token });
      return Response.json({ schemaVersion: 1, eventKey, state: "abandoned" });
    });
    expect(await host.abandonLegacyReminder({ ...request, attemptToken: token })).toMatchObject({ state: "abandoned" });
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, eventKey, state: "pending" }));
    await expect(host.abandonLegacyReminder({ ...request, attemptToken: token })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, eventKey: "wrong", state: "reserved", attemptToken: token }));
    await expect(host.reserveLegacyReminder(request)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    await expect(host.request({ operation: "legacy-reminders/reserve" } as never)).rejects.toThrow();
    await host.stop();
  });
  it("confirms a main-only initial migration binding and drains an aborted prepare", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true, initialMigrationControl: true });
    await host.start();
    const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue" as const, projectId: "project",
      previewId: "b".repeat(64), turnId: "turn-1", category: "personal" as const,
      operationId: "initial-" + "c".repeat(40), timeoutMs: 10000 };
    const directory = { device: "1", inode: "2", birthtimeNs: "3" };
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, registeredProjectId: row.projectId,
      sourceScope: { projectId: "source", instanceId: "instance", agentId: "agent" }, category: row.category,
      turnId: row.turnId, operationId: row.operationId, revision: 0, sourceIdentityDigest: "a".repeat(64),
      registryDigest: "b".repeat(64), targetIdentityDigest: "c".repeat(64), projectDirectory: directory,
      workspaceDirectory: directory, targetDirectory: directory, targetAgentId: "agent", targetSessionId: "session",
      authority: "native_policy_admitted", readyForCutover: false }));
    await expect(host.prepareInitialMigration(row, 0)).resolves.toBe(true);
    let started = false;
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      started = true;
      return await new Promise<Response>((_resolve, reject) => options?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    }).mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/initial-migration\/drain$/);
      expect(JSON.parse(String(options?.body))).toEqual({ deliveryId: row.deliveryId, operationId: row.operationId });
      return Response.json({ schemaVersion: 1, operationId: row.operationId, state: "unknown", drained: true });
    });
    const controller = new AbortController();
    const pending = host.prepareInitialMigration(row, 0, controller.signal);
    await vi.waitFor(() => expect(started).toBe(true));
    controller.abort();
    await expect(pending).resolves.toBe(false);
    expect(native.close).not.toHaveBeenCalled();
    await host.stop();
  });
  it("does not release a failed prepare until the root Job handle is signaled", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true, initialMigrationControl: true });
    await host.start();
    let exit: number | null = null;
    Object.assign(native, { exitCode: vi.fn(() => exit) });
    native.activeCount.mockReturnValue(0);
    fetchImpl.mockRejectedValue(new Error("connection unavailable"));
    const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue" as const, projectId: "project",
      previewId: "b".repeat(64), turnId: "turn-1", category: "personal" as const,
      operationId: "initial-" + "c".repeat(40), timeoutMs: 10000 };
    vi.useFakeTimers();
    let finished = false;
    const pending = host.prepareInitialMigration(row, 0).then(value => { finished = true; return value; });
    await vi.advanceTimersByTimeAsync(1100);
    expect(finished).toBe(false);
    exit = 0;
    await vi.advanceTimersByTimeAsync(1000);
    await expect(pending).resolves.toBe(false);
    vi.useRealTimers();
    await host.stop();
  });
  it("sends affairs sync through the current project revision and validates the response binding", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const previewId = "a".repeat(64), migrationId = affairsSyncMigrationId("project", previewId);
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/api\/assistant\/affairs-sync$/);
      const body = JSON.parse(String(options?.body));
      expect(body).toEqual({ projectId: "project", previewId, turnId: "turn-1", revision: 0, operationId: expect.stringMatching(/^[a-f0-9]{32}$/) });
      return Response.json({ schemaVersion: 1, projectId: "project", previewId, migrationId,
        state: "partial", code: "unresolved", appliedCount: 1, conflictCount: 2, readyForCutover: false });
    });
    await expect(host.syncAffairs({ projectId: "project", previewId, turnId: "turn-1", revision: 0 }))
      .resolves.toMatchObject({ migrationId, state: "partial", conflictCount: 2, readyForCutover: false });
    await expect(host.syncAffairs({ projectId: "project", previewId, turnId: "turn-1", revision: 1 })).rejects.toThrow("ASSISTANT_NOT_READY");
    await host.stop();
  });
  it("fences a cancelled in-flight affairs sync and never resends it", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true });
    await host.start();
    let started = false, operationId = "";
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/affairs-sync$/);
      operationId = JSON.parse(String(options?.body)).operationId; started = true;
      return await new Promise<Response>((_resolve, reject) => options?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    }).mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/affairs-sync\/cancel$/);
      expect(JSON.parse(String(options?.body))).toEqual({ operationId, previewId: "a".repeat(64) });
      return Response.json({ schemaVersion: 1, operationId, cancelled: true });
    });
    const controller = new AbortController();
    const pending = host.syncAffairs({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: controller.signal });
    await vi.waitFor(() => expect(started).toBe(true)); controller.abort();
    await expect(pending).resolves.toMatchObject({ state: "unknown", code: "unknown", readyForCutover: false });
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/affairs-sync"))).toHaveLength(1);
    expect(native.close).not.toHaveBeenCalled();
    await host.stop();
  });
  it("retires the host when an invalid affairs response cannot be fenced", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "complete", readyForCutover: true }))
      .mockRejectedValueOnce(new Error("cancel unavailable"));
    await expect(host.syncAffairs({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0 }))
      .resolves.toMatchObject({ state: "unknown", code: "unknown", readyForCutover: false });
    expect(native.close).toHaveBeenCalled();
  });
  it("fences pre-cancelled affairs sync without invoking publication", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/affairs-sync\/cancel$/);
      return Response.json({ schemaVersion: 1, operationId: JSON.parse(String(options?.body)).operationId, cancelled: true });
    });
    await expect(host.syncAffairs({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: AbortSignal.abort() }))
      .resolves.toMatchObject({ state: "rejected", code: "cancelled", readyForCutover: false });
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/affairs-sync"))).toHaveLength(0);
    await host.stop();
  });
  it("allows the backend up to ten seconds to drain a cancelled affairs sync", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true });
    await host.start();
    vi.useFakeTimers();
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      const operationId = JSON.parse(String(options?.body)).operationId;
      return await new Promise<Response>((resolve, reject) => {
        setTimeout(() => resolve(Response.json({ schemaVersion: 1, operationId, cancelled: true })), 10_000);
        options?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    });
    const pending = host.syncAffairs({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: AbortSignal.abort() });
    await vi.advanceTimersByTimeAsync(10_000);
    await expect(pending).resolves.toMatchObject({ state: "rejected", code: "cancelled" });
    expect(native.close).not.toHaveBeenCalled();
    vi.useRealTimers();
    await host.stop();
  });
  it("fences an aborted history import before returning unknown", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true });
    await host.start();
    let started = false, operationId = "";
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      operationId = JSON.parse(String(options?.body)).operationId;
      started = true;
      return await new Promise<Response>((_resolve, reject) => options?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    }).mockImplementationOnce(async (_url, options) => {
      expect(JSON.parse(String(options?.body)).operationId).toBe(operationId);
      return Response.json({ schemaVersion: 1, operationId, cancelled: true });
    });
    const controller = new AbortController();
    const pending = host.importHistory({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: controller.signal });
    await vi.waitFor(() => expect(started).toBe(true));
    controller.abort();
    await expect(pending).resolves.toMatchObject({ state: "unknown", code: "unknown", readyForCutover: false });
    expect(native.close).not.toHaveBeenCalled();
    await host.stop();
  });
  it("discards the preview when history is cancelled before sending", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/history-import\/cancel$/);
      const body = JSON.parse(String(options?.body));
      expect(body.previewId).toBe("a".repeat(64));
      return Response.json({ schemaVersion: 1, operationId: body.operationId, cancelled: true });
    });
    const controller = new AbortController(); controller.abort();
    await expect(host.importHistory({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: controller.signal }))
      .resolves.toMatchObject({ state: "rejected", code: "cancelled" });
    await host.stop();
  });
  it("keeps startup and retries gated until a complete project snapshot is acknowledged", async () => {
    const { host, inputs, fetchImpl, root } = fixture({ graceful: true, projectsSuspended: true });
    await host.start();
    expect(inputs[0].arguments).toContain("--projects-suspended");
    const runtime = inputs[0].arguments[inputs[0].arguments.indexOf("--runtime-dir") + 1];
    expect(JSON.parse(readFileSync(join(runtime, "projects.json"), "utf8")).projects).toEqual({ project: root });
    fetchImpl.mockRejectedValueOnce(new Error("unknown update"));
    await expect(host.updateProjects({ schemaVersion: 1, revision: 1, projects: {} })).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    await host.start();
    expect(inputs.at(-1)!.arguments).toContain("--projects-suspended");
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 1, projectCount: 0 }));
    await host.updateProjects({ schemaVersion: 1, revision: 1, projects: {} });
    await host.stop(); await host.start();
    expect(inputs.at(-1)!.arguments).not.toContain("--projects-suspended");
    await host.stop();
  });

  it("serializes suspension behind snapshot application and retains the local host after its exact ACK", async () => {
    const { host, fetchImpl, native, inputs } = fixture({ graceful: true });
    await host.start();
    let release!: (value: Response) => void;
    fetchImpl.mockImplementationOnce(async () => await new Promise<Response>(done => { release = done; }))
      .mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 3, projectsSuspended: true }));
    const update = host.updateProjects({ schemaVersion: 1, revision: 3, projects: {} });
    const suspension = host.suspendProjects();
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/suspend"))).toHaveLength(0);
    release(Response.json({ schemaVersion: 1, revision: 3, projectCount: 0 }));
    await update; await suspension;
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.method).toBe("POST");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe("{}");
    expect(String(fetchImpl.mock.calls.at(-1)?.[0])).toMatch(/\/project-registry\/suspend$/);
    expect(native.close).not.toHaveBeenCalled();
    await expect(host.request({ operation: "detail" })).resolves.toMatchObject({ id: "s" });
    await host.stop(); await host.start();
    expect(inputs.at(-1)!.arguments).toContain("--projects-suspended");
    await host.stop();
  });

  it.each([
    { schemaVersion: 1, revision: 0, projectsSuspended: false },
    { schemaVersion: 1, revision: 1, projectsSuspended: true },
    { schemaVersion: 1, revision: 0, projectsSuspended: true, extra: true },
    { schemaVersion: 1, revision: 0 },
  ])("retires unconfirmed suspension and retains its gate on retry: %j", async ack => {
    const { host, native, fetchImpl, inputs } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json(ack));
    await expect(host.suspendProjects()).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_REGISTRY_UNCONFIRMED" });
    expect(native.close).toHaveBeenCalledTimes(1);
    await host.start();
    expect(inputs.at(-1)!.arguments).toContain("--projects-suspended");
    await host.stop();
  });

  it("rejects a suspension ACK after stop has invalidated its generation", async () => {
    const { host, fetchImpl, inputs } = fixture({ graceful: true });
    await host.start();
    let release!: (value: Response) => void;
    fetchImpl.mockImplementationOnce(async () => await new Promise<Response>(done => { release = done; }));
    const suspension = expect(host.suspendProjects()).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    const stopped = host.stop();
    release(Response.json({ schemaVersion: 1, revision: 0, projectsSuspended: true }));
    await suspension; await stopped; await host.start();
    expect(inputs.at(-1)!.arguments).toContain("--projects-suspended");
    await host.stop();
  });

  it("keeps failed suspension locally failed and retains an unclosed Job for cleanup", async () => {
    const { host, fetchImpl, native } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockRejectedValueOnce(new Error("ack lost"));
    native.close.mockImplementationOnce(() => { throw new Error("close failed"); });
    await expect(host.suspendProjects()).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_REGISTRY_UNCONFIRMED" });
    await expect(host.request({ operation: "detail" })).rejects.toThrow("ASSISTANT_NOT_READY");
    await host.stop();
    expect(native.close).toHaveBeenCalledTimes(2);
  });

  it("never exposes suspension as a renderer request operation", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const before = fetchImpl.mock.calls.length;
    await expect(host.request({ operation: "suspendProjects" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    await host.stop();
  });

  it("keeps selected assets on a fixed UI operation with a dedicated response budget", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ image: null }), { headers: { "content-length": String(9 * 1024 * 1024) } }));
    expect(await host.request({ operation: "operatorAsset", kind: "background" })).toEqual({ image: null });
    expect(String(fetchImpl.mock.calls.at(-1)?.[0])).toBe("http://127.0.0.1:12345/api/assistant/operator-assets/background");
    for (const payload of [{ operation: "operatorAsset", kind: "file" }, { operation: "operatorAsset", kind: "avatar", path: "private" }]) {
      await expect(host.request(payload as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    fetchImpl.mockResolvedValueOnce(new Response("{}", { headers: { "content-length": String(9 * 1024 * 1024) } }));
    await expect(host.request({ operation: "config" })).rejects.toThrow("ASSISTANT_RESPONSE_TOO_LARGE");
    await host.stop();
  });
  it("does not acknowledge a queued revocation before its native apply completes", async () => {
    const { host, fetchImpl, root } = fixture({ graceful: true });
    await host.start();
    let resolveFirst!: (value: Response) => void;
    const firstResponse = new Promise<Response>(resolve => { resolveFirst = resolve; });
    fetchImpl.mockImplementationOnce(async () => await firstResponse)
      .mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 7, projectCount: 1 }));
    let confirmed = false;
    const first = host.updateProjects({ schemaVersion: 1, revision: 6, projects: {} }).then(() => { confirmed = true; });
    const second = host.updateProjects({ schemaVersion: 1, revision: 7, projects: { "new:epoch": root } });
    await Promise.resolve();
    await Promise.resolve();
    expect(confirmed).toBe(false);
    expect(JSON.parse(String(fetchImpl.mock.calls.at(-1)?.[1]?.body)).revision).toBe(6);
    resolveFirst(Response.json({ schemaVersion: 1, revision: 6, projectCount: 0 }));
    await first;
    await second;
    expect(confirmed).toBe(true);
    expect(JSON.parse(String(fetchImpl.mock.calls.at(-1)?.[1]?.body)).revision).toBe(7);
    await host.stop();
  });
  it("cannot resurrect revoked permissions through a delayed or conflicting snapshot after host restart", async () => {
    const { host, fetchImpl, native, inputs, root } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 5, projectCount: 0 }));
    await host.updateProjects({ schemaVersion: 1, revision: 5, projects: {} });
    const before = fetchImpl.mock.calls.length;
    await expect(host.updateProjects({ schemaVersion: 1, revision: 4, projects: { revoked: root } })).rejects.toThrow("ASSISTANT_REGISTRY_STALE");
    await expect(host.updateProjects({ schemaVersion: 1, revision: 5, projects: { revoked: root } })).rejects.toThrow("ASSISTANT_REGISTRY_CONFLICT");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    expect(native.close).not.toHaveBeenCalled();
    await host.stop();
    await host.start();
    const input = inputs.at(-1)!;
    const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
    expect(JSON.parse(readFileSync(join(runtime, "projects.json"), "utf8"))).toEqual({ schemaVersion: 1, revision: 5, projects: {} });
    await host.stop();
  });
  it("applies main project snapshots without restarting chat and retires only an unconfirmed owner", async () => {
    const { host, fetchImpl, native, root, inputs } = fixture({ graceful: true });
    await host.start();
    const snapshot = { schemaVersion: 1 as const, revision: 4, projects: { "project:new-epoch": root } };
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, revision: 4, projectCount: 1 }));
    await host.updateProjects(snapshot);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.method).toBe("PUT");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify(snapshot));
    await expect(host.request({ operation: "updateProjects", ...snapshot } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    fetchImpl.mockRejectedValueOnce(new Error("lost revocation acknowledgement"));
    await expect(host.updateProjects({ ...snapshot, revision: 5, projects: {} })).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    expect(native.close).toHaveBeenCalledTimes(1);
    await host.start();
    const input = inputs.at(-1)!;
    const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
    expect(JSON.parse(readFileSync(join(runtime, "projects.json"), "utf8"))).toEqual({ schemaVersion: 1, revision: 5, projects: {} });
    await host.stop();
  });
  it("forwards stop and snapshot continuation once and rejects extra authority", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const continuation = { turnId: "turn-old", headId: "head-native", ledgerSeq: 9, agentId: "a" };
    await host.request({ operation: "stop", turnId: "turn-running" } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ turnId: "turn-running" }));
    await host.request({ operation: "continue", requestId: "stable-continue", continuation } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ requestId: "stable-continue", continuation }));
    const before = fetchImpl.mock.calls.length;
    for (const value of [
      { operation: "stop", turnId: "turn-running", sessionId: "other" },
      { operation: "continue", requestId: "id", continuation: { ...continuation, ledgerSeq: 0 } },
      { operation: "continue", requestId: "id", continuation: { ...continuation, extra: true } },
      { operation: "continue", requestId: "id", continuation, message: "different task" },
    ]) await expect(host.request(value as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    fetchImpl.mockRejectedValueOnce(new Error("ack lost"));
    await expect(host.request({ operation: "continue", requestId: "stable-continue", continuation } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_TRANSPORT_FAILED");
    expect(fetchImpl).toHaveBeenCalledTimes(before + 1);
    await host.stop();
  });
  it("does not reintroduce inherited Python search paths for the isolated packaged runtime", async () => {
    vi.stubEnv("PYTHONPATH", "foreign-source");
    vi.stubEnv("PYTHONHOME", "foreign-runtime");
    const { host, inputs } = fixture({ graceful: true, pythonArguments: ["-I", "-B", "-X", "utf8"] });
    await host.start();
    expect(Object.keys(inputs[0].env).some(key => /^PYTHON(?:PATH|HOME)$/i.test(key))).toBe(false);
    expect(inputs[0].arguments.slice(0, 4)).toEqual(["-I", "-B", "-X", "utf8"]);
    await host.stop();
  });
  it("keeps explicit assistant project and Python bindings out of the final native spawn environment", async () => {
    const inherited = {
      VIBELUTION_WORKSPACE_ROOT: "foreign-project", VIBELUTION_PYTHON_PATH: "foreign-python.exe",
      PYTHON: "foreign.exe", PYTHONPATH: "foreign-source", PYTHONHOME: "foreign-runtime",
    };
    for (const [key, value] of Object.entries(inherited)) vi.stubEnv(key, value);
    const configured = applyDesktopLaunchSettingsToEnvironment({ ...inherited }, {
      schemaVersion: 1, assistant: true, workspaceRoot: "", pythonPath: "", configPath: "",
      profilePath: "", profileError: "", searchedProfilePaths: [],
    });
    const { host, inputs } = fixture({ graceful: true, pythonArguments: ["-I", "-B"],
      env: { ...configured, Vibelution_Workspace_Root: "mixed-case-project", Python: "mixed-case-python" } });
    await host.start();
    expect(Object.keys(inputs[0].env).filter(key =>
      /^(VIBELUTION_WORKSPACE_ROOT|VIBELUTION_PYTHON_PATH|PYTHON|PYTHONPATH|PYTHONHOME)$/i.test(key))).toEqual([]);
    expect(inputs[0].env.VIBELUTION_CONFIG_PATH).toBe(join(inputs[0].cwd, "..", "config.toml"));
    await host.stop();
  });
  it("deduplicates concurrent starts and keeps credentials out of argv, ready and snapshot", async () => {
    const { host, native, fetchImpl, inputs, root } = fixture({ graceful: true });
    const first = host.start();
    expect(host.start()).toBe(first);
    await expect(first).resolves.toEqual({ state: "ready", errorCode: null });
    await host.start();
    expect(native.spawn).toHaveBeenCalledTimes(1);
    const input = inputs[0];
    const token = input.env.VIBELUTION_ASSISTANT_TOKEN!;
    expect(token).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(input.arguments)).not.toContain(token);
    expect(JSON.stringify(host.snapshot())).not.toContain(token);
    expect(Object.keys(host.snapshot()).sort()).toEqual(["errorCode", "state"]);
    expect(input.cwd).toBe(join(root, "profile"));
    expect(input.env.VIBELUTION_CONFIG_PATH).toBe(join(root, "config.toml"));
    expect(token).not.toBe("must-not-override-token");
    expect(input.containDescendants).toBe(true);
    expect(input.maxLogBytes).toBe(4 * 1024 * 1024);
    const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
    expect(readFileSync(join(runtime, "ready.json"), "utf8")).not.toContain(token);
    expect(JSON.parse(readFileSync(join(runtime, "projects.json"), "utf8"))).toEqual({ schemaVersion: 1, revision: 0, projects: { project: root } });
    for (const [url, init] of fetchImpl.mock.calls) {
      expect(String(url)).not.toContain(token);
      expect(init?.redirect).toBe("error");
      expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${token}`);
    }
    // PID 900 in readiness may differ from the pythonw redirector's PID 100.
    await host.stop();
    expect(native.close).toHaveBeenCalledTimes(1);
  });

  it("rejects stale readiness and reclaims the exact Job before returning failure", async () => {
    const { host, native, fetchImpl } = fixture({ stale: true });
    await expect(host.start()).rejects.toThrow("ASSISTANT_READY_INVALID");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(native.terminate).toHaveBeenCalledWith(native.spawn.mock.results[0].value.job);
    expect(native.close).toHaveBeenCalledWith(native.spawn.mock.results[0].value.job);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_READY_INVALID" });
  });

  it("requires authenticated, correctly identified health before readiness", async () => {
    const { host, native, fetchImpl } = fixture();
    fetchImpl.mockResolvedValueOnce(Response.json({ role: "workbench", status: "ok", protocolVersion: 1 }));
    await expect(host.start()).rejects.toThrow("ASSISTANT_HEALTH_INVALID");
    expect(native.close).toHaveBeenCalledTimes(1);
  });

  it("stops idempotently and force-reclaims only its Job after the graceful deadline", async () => {
    vi.useFakeTimers();
    const { host, native, fetchImpl } = fixture();
    await host.start();
    const first = host.stop();
    expect(host.stop()).toBe(first);
    await vi.advanceTimersByTimeAsync(11_999);
    expect(native.terminate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(21);
    await expect(first).resolves.toEqual({ state: "stopped", errorCode: null });
    expect(native.terminate).toHaveBeenCalledTimes(1);
    expect(native.close).toHaveBeenCalledTimes(1);
    const writes = fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes.map(([url]) => String(url))).toEqual(["http://127.0.0.1:12345/api/assistant/shutdown"]);
    await host.stop();
    expect(native.close).toHaveBeenCalledTimes(1);
  });

  it("retains a failed close for a later explicit retirement attempt", async () => {
    const { host, native } = fixture({ graceful: true });
    await host.start();
    native.close.mockImplementationOnce(() => { throw new Error("native-close-failed"); });
    await expect(host.stop()).rejects.toThrow("ASSISTANT_CLOSE_FAILED");
    expect(host.snapshot().state).toBe("failed");
    await host.stop();
    expect(native.close).toHaveBeenCalledTimes(2);
  });

  it("does not replay a failed write and rejects foreign sessions and arbitrary routes", async () => {
    const { host, native, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockRejectedValueOnce(new Error("body could contain secrets - must not escape"));
    const before = fetchImpl.mock.calls.length;
    await expect(host.request({ operation: "send", message: "hello", requestId: "stable-id" })).rejects.toThrow("ASSISTANT_TRANSPORT_FAILED");
    expect(fetchImpl).toHaveBeenCalledTimes(before + 1);
    const last = fetchImpl.mock.calls.at(-1)!;
    expect(last[1]?.body).toBe(JSON.stringify({ message: "hello", requestId: "stable-id" }));
    await host.start();
    // Transport failure while the captured Job is alive must not create another owner.
    expect(host.snapshot().state).toBe("ready");
    expect(native.spawn).toHaveBeenCalledTimes(1);
    await expect(host.request({ operation: "curation", sessionId: "foreign" })).rejects.toThrow("ASSISTANT_SESSION_FORBIDDEN");
    await expect(host.request({ operation: "status", url: "http://outside" } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ operation: "outside" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before + 1);
    await host.stop();
  });

  it("reclaims a dead ready Job and restores the same profile with a fresh generation and secret", async () => {
    const { host, native, fetchImpl, inputs, active } = fixture({ graceful: true });
    await host.start();
    const previous = native.spawn.mock.results[0].value.job;
    active.set(previous, 0);
    const recovering = host.start();
    expect(host.start()).toBe(recovering);
    await expect(recovering).resolves.toEqual({ state: "ready", errorCode: null });
    expect(native.close).toHaveBeenCalledWith(previous);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(inputs[1].cwd).toBe(inputs[0].cwd);
    expect(inputs[1].arguments[inputs[1].arguments.indexOf("--profile-root") + 1])
      .toBe(inputs[0].arguments[inputs[0].arguments.indexOf("--profile-root") + 1]);
    expect(inputs[1].arguments[inputs[1].arguments.indexOf("--instance-id") + 1])
      .not.toBe(inputs[0].arguments[inputs[0].arguments.indexOf("--instance-id") + 1]);
    expect(inputs[1].env.VIBELUTION_ASSISTANT_TOKEN).not.toBe(inputs[0].env.VIBELUTION_ASSISTANT_TOKEN);
    await expect(host.request({ operation: "detail" })).resolves.toMatchObject({ id: "s" });
    expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    await host.start();
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await host.stop();
  });

  it("observes death after a failed write, then recovers without replaying the old request", async () => {
    const { host, native, fetchImpl, active } = fixture({ graceful: true });
    await host.start();
    const previous = native.spawn.mock.results[0].value.job;
    fetchImpl.mockImplementationOnce(async () => {
      active.set(previous, 0);
      throw new Error("connection lost");
    });
    await expect(host.request({ operation: "send", message: "hello", requestId: "unconfirmed-id" }))
      .rejects.toThrow("ASSISTANT_TRANSPORT_FAILED");
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    await host.start();
    expect(native.spawn).toHaveBeenCalledTimes(2);
    const writes = fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/messages"));
    expect(writes).toHaveLength(1);
    expect(writes[0][1]?.body).toBe(JSON.stringify({ message: "hello", requestId: "unconfirmed-id" }));
    expect(JSON.stringify(host.snapshot())).not.toContain("http");
    await host.stop();
  });

  it("waits for the dead Job's output drains before closing and spawning a replacement", async () => {
    vi.useFakeTimers();
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    active.set(native.spawn.mock.results[0].value.job, 0);
    let complete = false;
    native.drainStatus.mockImplementation(() => ({ complete, channels: [] }));
    const recovering = host.start();
    await vi.advanceTimersByTimeAsync(100);
    expect(native.close).not.toHaveBeenCalled();
    expect(native.spawn).toHaveBeenCalledTimes(1);
    complete = true;
    await vi.advanceTimersByTimeAsync(20);
    await recovering;
    expect(native.close).toHaveBeenCalledTimes(1);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await host.stop();
  });

  it("retains a dead Job when close fails and forbids a replacement until that same handle closes", async () => {
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    const previous = native.spawn.mock.results[0].value.job;
    active.set(previous, 0);
    native.close.mockImplementationOnce(() => { throw new Error("close rejected"); });
    await expect(host.start()).rejects.toThrow("ASSISTANT_CLOSE_FAILED");
    expect(native.spawn).toHaveBeenCalledTimes(1);
    await host.start();
    expect(native.close.mock.calls.slice(0, 2)).toEqual([[previous], [previous]]);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await host.stop();
  });

  it("bounds streamed response bytes independently of content-length", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new Uint8Array(8 * 1024 * 1024));
      controller.enqueue(new Uint8Array(1));
      controller.close();
    } })));
    await expect(host.request({ operation: "config" })).rejects.toThrow("ASSISTANT_RESPONSE_TOO_LARGE");
    await host.stop();
  });

  it("bounds startup to 60 seconds and reclaims an unready process", async () => {
    vi.useFakeTimers();
    const { host, native } = fixture({ noReadyFirst: true });
    const result = expect(host.start()).rejects.toThrow("ASSISTANT_STARTUP_TIMEOUT");
    await vi.advanceTimersByTimeAsync(60_000);
    await result;
    expect(native.terminate).toHaveBeenCalledTimes(1);
    expect(native.close).toHaveBeenCalledTimes(1);
  });

  it("aborts a timed-out request without replaying the write or exposing transport details", async () => {
    vi.useFakeTimers();
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const before = fetchImpl.mock.calls.length;
    fetchImpl.mockImplementationOnce(async (_url, init) => await new Promise<Response>((_done, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("transport-secret")), { once: true });
    }));
    const result = expect(host.request({ operation: "send", message: "hello", requestId: "timeout-id" }))
      .rejects.toThrow("ASSISTANT_REQUEST_TIMEOUT");
    await vi.advanceTimersByTimeAsync(15_000);
    await result;
    expect(fetchImpl).toHaveBeenCalledTimes(before + 1);
    await host.stop();
  });

  it("serializes start-stop-start without leaking a cancelled startup or duplicating replacement", async () => {
    const { host, native } = fixture({ noReadyFirst: true, graceful: true });
    const first = host.start();
    const firstResult = expect(first).rejects.toThrow("ASSISTANT_STOPPED");
    await Promise.resolve();
    const stopped = host.stop();
    const replacement = host.start();
    expect(host.start()).toBe(replacement);
    await firstResult;
    await stopped;
    await expect(replacement).resolves.toEqual({ state: "ready", errorCode: null });
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(native.close).toHaveBeenCalledTimes(1);
    await host.stop();
    expect(native.close).toHaveBeenCalledTimes(2);
  });
});
