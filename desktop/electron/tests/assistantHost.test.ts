/** Fake-Job coverage for the Launcher-owned assistant source-host lifecycle. */
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost, type AssistantHostOptions, type AssistantHostRequest } from "../src/assistant/assistantHost.js";
import { invokeAssistant, LAUNCHER_ASSISTANT_URL } from "../src/assistant/assistantBridge.js";
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

function fixture(options: { stale?: boolean; noReadyFirst?: boolean; graceful?: boolean; pythonArguments?: string[]; env?: NodeJS.ProcessEnv; projectsSuspended?: boolean; initialMigrationControl?: boolean; mainControl?: AssistantHostOptions["mainControl"] } = {}) {
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
      ...(options.initialMigrationControl ? { initialMigrationControlVersion: 1 } : {}),
      ...(options.mainControl ? { mainControlVersion: 1 } : {}) });
    if (url.endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" } });
    if (url.endsWith("/api/assistant/session")) return Response.json({ id: "s", messages: [] });
    if (url.endsWith("/migration-barrier/status")) return Response.json({ schemaVersion: 1, state: "ready" });
    if (url.endsWith("/shutdown")) {
      if (options.graceful) active.set(currentJob, 0);
      return Response.json({ stopping: true });
    }
    return Response.json({ accepted: true });
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"),
    sourceRoot: root, pythonPath: python, pythonArguments: options.pythonArguments, projects: { project: root }, projectsSuspended: options.projectsSuspended, initialMigrationControl: options.initialMigrationControl, native, fetch: fetchImpl,
    ...(options.mainControl ? { mainControl: options.mainControl } : {}),
    env: { VIBELUTION_CONFIG_PATH: join(root, "config.toml"), ...options.env, VIBELUTION_ASSISTANT_TOKEN: "must-not-override-token" } });
  return { host, native, fetchImpl, inputs, root, active };
}

function usageSnapshot() {
  const numbers = { inputTokens: 100, cachedInputTokens: 0, cacheReadInputTokens: 0, cacheCreationInputTokens: 0,
    uncachedInputTokens: 100, outputTokens: 0, reasoningOutputTokens: 0, totalTokens: 100, latencyMs: 0,
    cacheHitRate: 0, cacheUsageObserved: true, cacheUsageMissingReason: "" };
  return { sessionId: "s", agentId: "a", lastTokenUsage: { ...numbers, source: "provider_usage" },
    sessionTokenUsage: { ...numbers, callCount: 1, observedCallCount: 1, estimatedCallCount: 0, missingCallCount: 0,
      notCalledCount: 0, cacheObservedInputTokens: 100, cacheObservedCallCount: 1, cacheUnobservedCallCount: 0,
      cacheUsageComplete: true } };
}

describe("AssistantHost", () => {
  it("binds control continuation sends to the captured identity and preserves the exact retry body", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const controlContinuation = { agentId: "a", sessionId: "s", turnId: "old-turn", headId: "head", ledgerSeq: 4 };
    const request = { operation: "send" as const, requestId: "control-1", controlContinuation,
      message: "控制已交回，请先重新观察当前页面或授权窗口，再继续当前任务；不要重放未经确认的操作。" };
    fetchImpl.mockRejectedValueOnce(new Error("ack lost"));
    await expect(host.request(request)).rejects.toThrow("ASSISTANT_TRANSPORT_FAILED");
    const failedBody = fetchImpl.mock.calls.at(-1)?.[1]?.body;
    await host.request(request);
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(failedBody);
    expect(JSON.parse(String(failedBody))).toEqual({ message: request.message, requestId: "control-1", controlContinuation });
    const before = fetchImpl.mock.calls.length;
    for (const changes of [{ agentId: "new-agent" }, { sessionId: "new-session" }])
      await expect(host.request({ ...request, controlContinuation: { ...controlContinuation, ...changes } }))
        .rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    for (const changes of [{ message: "continue freely" }, { attachmentIds: ["file-1"] }, { references: [{ messageId: "m" }] },
      { controlContinuation: null }, { controlContinuation: { ...controlContinuation, ledgerSeq: true } },
      { controlContinuation: { ...controlContinuation, headId: " head " } },
      { controlContinuation: { ...controlContinuation, extra: true } }])
      await expect(host.request({ ...request, ...changes } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl.mock.calls.length).toBe(before);
    await host.stop();
  });

  it("rejects a control send retained across migration once the new native identity is ready", async () => {
    const { host, fetchImpl, native, root } = fixture({ graceful: true });
    Object.assign(native, { exitCode: vi.fn(() => 0) });
    await host.start();
    const request = { operation: "send" as const, requestId: "old-control", controlContinuation:
      { agentId: "a", sessionId: "s", turnId: "old-turn", headId: "head", ledgerSeq: 4 },
      message: "控制已交回，请先重新观察当前页面或授权窗口，再继续当前任务；不要重放未经确认的操作。" };
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    const queued = host.request(request);
    expect(await host.retireForMigration()).toBe(true);
    host.prepareForMigrationRestart({ schemaVersion: 1, revision: 0, projects: { project: root } }, false);
    const originalFetch = fetchImpl.getMockImplementation()!;
    fetchImpl.mockImplementation(async (...args) => String(args[0]).endsWith("/api/assistant")
      ? Response.json({ assistant: { agentId: "new-agent", directSessionId: "new-session" } }) : originalFetch(...args));
    await host.startForMigration();
    admission.release();
    await expect(queued).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/api/assistant/messages"))).toHaveLength(0);
    await host.stop();
  });

  it("reads a fixed compact usage snapshot and refuses identity or scope injection", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const snapshot = usageSnapshot();
    fetchImpl.mockResolvedValueOnce(Response.json(snapshot));
    await expect(host.request({ operation: "usageSummary" })).resolves.toEqual(snapshot);
    const [url, options] = fetchImpl.mock.calls.at(-1)!;
    expect(String(url)).toBe("http://127.0.0.1:12345/api/assistant/usage-summary");
    expect(options?.method).toBe("GET");
    expect(options?.body).toBeUndefined();
    const calls = fetchImpl.mock.calls.length;
    for (const key of ["sessionId", "agentId", "scope", "projectRoot", "ledgerPath"])
      await expect(host.request({ operation: "usageSummary", [key]: "foreign" } as AssistantHostRequest))
        .rejects.toThrow("ASSISTANT_USAGE_INVALID");
    expect(fetchImpl.mock.calls.length).toBe(calls);
    for (const key of ["sessionId", "agentId"]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ ...snapshot, [key]: "foreign" }));
      await expect(host.request({ operation: "usageSummary" })).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    }
    await host.stop();
  });

  it("rejects unsafe, overbroad and oversized usage responses instead of returning zero", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const snapshot = usageSnapshot();
    for (const invalid of [{ ...snapshot, globalTokenUsage: {} },
      { ...snapshot, lastTokenUsage: { ...snapshot.lastTokenUsage, ledgerPath: "private" } },
      { ...snapshot, lastTokenUsage: { ...snapshot.lastTokenUsage, source: ["provider_usage"] } },
      { ...snapshot, sessionTokenUsage: { ...snapshot.sessionTokenUsage, cacheHitRate: 1.1 } },
      { ...snapshot, sessionTokenUsage: { ...snapshot.sessionTokenUsage, cachedInputTokens: true } },
      { ...snapshot, sessionTokenUsage: { ...snapshot.sessionTokenUsage, cacheObservedInputTokens: Number.MAX_SAFE_INTEGER + 1 } }]) {
      fetchImpl.mockResolvedValueOnce(Response.json(invalid));
      await expect(host.request({ operation: "usageSummary" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
    fetchImpl.mockResolvedValueOnce(Response.json({ ...snapshot, private: "x".repeat(8192) }));
    await expect(host.request({ operation: "usageSummary" })).rejects.toThrow("ASSISTANT_RESPONSE_TOO_LARGE");
    fetchImpl.mockResolvedValueOnce(Response.json({ private: "hidden" }, { status: 503 }));
    await expect(host.request({ operation: "usageSummary" })).rejects.toThrow("ASSISTANT_USAGE_UNAVAILABLE");
    await host.stop();
  });

  it("keeps usage reads safe before migration sealing and read-only during lifecycle admission", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const snapshot = usageSnapshot();
    const admission = host.beginMigrationAdmission();
    fetchImpl.mockResolvedValueOnce(Response.json(snapshot));
    await expect(host.request({ operation: "usageSummary" })).resolves.toEqual(snapshot);
    await admission.seal();
    const calls = fetchImpl.mock.calls.length;
    let settled = false;
    const pending = host.request({ operation: "usageSummary" }).then(value => { settled = true; return value; });
    await Promise.resolve(); await Promise.resolve();
    expect(settled).toBe(false); expect(fetchImpl.mock.calls.length).toBe(calls);
    fetchImpl.mockResolvedValueOnce(Response.json(snapshot));
    admission.release();
    await expect(pending).resolves.toEqual(snapshot);
    const lifecycle = host.beginLifecycleAdmission();
    fetchImpl.mockResolvedValueOnce(Response.json(snapshot));
    await expect(host.request({ operation: "usageSummary" })).resolves.toEqual(snapshot);
    await lifecycle.seal(); lifecycle.commit();
    let lifecycleSettled = false;
    const held = host.request({ operation: "usageSummary" }).then(value => { lifecycleSettled = true; return value; });
    await Promise.resolve(); await Promise.resolve();
    expect(lifecycleSettled).toBe(false);
    fetchImpl.mockResolvedValueOnce(Response.json(snapshot));
    lifecycle.release();
    await expect(held).resolves.toEqual(snapshot);
    await host.stop();
  });

  it("keeps assistant budget reads and CAS writes fixed to the native owner", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ revision: 3, maxCallsPerTurn: 16 }));
    await expect(host.request({ operation: "budgetParameters" })).resolves.toEqual({ revision: 3, maxCallsPerTurn: 16 });
    expect(fetchImpl.mock.calls.at(-1)![1]?.method).toBe("GET");
    for (const maxCallsPerTurn of [0, null, 64]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ revision: 4, maxCallsPerTurn }));
      await expect(host.request({ operation: "setBudgetParameters", revision: 3, maxCallsPerTurn })).resolves.toEqual({ revision: 4, maxCallsPerTurn });
      expect(String(fetchImpl.mock.calls.at(-1)![0])).toBe("http://127.0.0.1:12345/api/assistant/budget-parameters");
      expect(fetchImpl.mock.calls.at(-1)![1]?.method).toBe("PATCH");
      expect(JSON.parse(String(fetchImpl.mock.calls.at(-1)![1]?.body))).toEqual({ revision: 3, maxCallsPerTurn });
    }
    const calls = fetchImpl.mock.calls.length;
    for (const payload of [{ operation: "budgetParameters", sessionId: "foreign" },
      { operation: "setBudgetParameters", revision: 3, maxCallsPerTurn: 0, sessionId: "foreign" },
      { operation: "setBudgetParameters", revision: true, maxCallsPerTurn: 0 },
      { operation: "setBudgetParameters", revision: 3, maxCallsPerTurn: 201 }])
      await expect(host.request(payload as AssistantHostRequest)).rejects.toThrow("ASSISTANT_BUDGET_INVALID");
    expect(fetchImpl.mock.calls.length).toBe(calls);
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 409 }));
    await expect(host.request({ operation: "setBudgetParameters", revision: 3, maxCallsPerTurn: 0 })).rejects.toThrow("ASSISTANT_BUDGET_CONFLICT");
    expect(fetchImpl.mock.calls.length).toBe(calls + 1);
    await host.stop();
  });
  it("posts management presets once with closed CAS inputs and bounded verified receipts", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const request = { operation: "setManagementPermissionPreset" as const, preset: "auto_review" as const, expectedRevision: 4 };
    const before = fetchImpl.mock.calls.length;
    for (const payload of [{ ...request, extra: true }, { ...request, preset: "custom" }, { ...request, expectedRevision: true },
      { ...request, expectedRevision: -1 }, { ...request, expectedRevision: 0.5 }, { ...request, expectedRevision: Number.MAX_SAFE_INTEGER + 1 }])
      await expect(host.request(payload as AssistantHostRequest)).rejects.toThrow("ASSISTANT_PERMISSION_INVALID");
    expect(fetchImpl.mock.calls.length).toBe(before);
    fetchImpl.mockResolvedValueOnce(Response.json({ preset: "auto_review", revision: 5 }));
    await expect(host.request(request)).resolves.toEqual({ preset: "auto_review", revision: 5 });
    expect(String(fetchImpl.mock.calls.at(-1)![0])).toBe("http://127.0.0.1:12345/api/assistant/management-permission");
    expect(fetchImpl.mock.calls.at(-1)![1]?.method).toBe("POST");
    expect(JSON.parse(String(fetchImpl.mock.calls.at(-1)![1]?.body))).toEqual({ preset: "auto_review", expectedRevision: 4 });
    for (const reply of [{ preset: "full_access", revision: 5 }, { preset: "auto_review", revision: true },
      { preset: "auto_review", revision: 3 }, { preset: "auto_review", revision: 6 }, { preset: "auto_review", revision: 5, extra: true }]) {
      fetchImpl.mockResolvedValueOnce(Response.json(reply));
      await expect(host.request(request)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
    for (const [status, code] of [[409, "CONFLICT"], [422, "INVALID"], [503, "UNAVAILABLE"], [404, "UNAVAILABLE"]] as const) {
      fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status }));
      const calls = fetchImpl.mock.calls.length;
      await expect(host.request(request)).rejects.toThrow(`ASSISTANT_PERMISSION_${code}`);
      expect(fetchImpl.mock.calls.length).toBe(calls + 1);
    }
    await host.stop();
  });

  it("permits a management change before migration sealing but preserves sealed and closing admission", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const request = { operation: "setManagementPermissionPreset" as const, preset: "auto_review" as const, expectedRevision: 0 };
    const admission = host.beginMigrationAdmission();
    fetchImpl.mockResolvedValueOnce(Response.json({ preset: "auto_review", revision: 1 }));
    await expect(host.request(request)).resolves.toEqual({ preset: "auto_review", revision: 1 });
    await admission.seal();
    const calls = fetchImpl.mock.calls.length;
    let settled = false;
    const held = host.request(request).then(result => { settled = true; return result; });
    await Promise.resolve(); await Promise.resolve();
    expect(settled).toBe(false); expect(fetchImpl.mock.calls.length).toBe(calls);
    fetchImpl.mockResolvedValueOnce(Response.json({ preset: "auto_review", revision: 1 }));
    admission.release();
    await held;
    const lifecycle = host.beginLifecycleAdmission();
    await lifecycle.seal(); lifecycle.commit();
    await expect(host.request(request)).rejects.toThrow("ASSISTANT_LIFECYCLE_CLOSING");
    lifecycle.release();
    await host.stop();
  });

  it("rejects malformed management-permission status projections while admitting an old host", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const assistant = { agentId: "a", directSessionId: "s", displayName: "Assistant" };
    for (const permission of [null, {}, { preset: "full_access", revision: true }, { preset: "custom", revision: 0 },
      { preset: "auto_review", revision: 0, extra: true }, { preset: "auto_review", revision: Number.MAX_SAFE_INTEGER + 1 }]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ assistant, settings: { managementPermission: permission } }));
      await expect(host.request({ operation: "status" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
    fetchImpl.mockResolvedValueOnce(Response.json({ assistant }));
    await expect(host.request({ operation: "status" })).resolves.toEqual({ assistant });
    await host.stop();
  });

  it("switches only the fixed assistant model and requires the verified model readback", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    for (const extra of [{ agentId: "foreign" }, { directSessionId: "foreign" }])
      await expect(host.request({ operation: "setModel", modelId: "local/other", ...extra } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    fetchImpl.mockResolvedValueOnce(Response.json({ modelId: "local/other" }));
    await expect(host.request({ operation: "setModel", modelId: "local/other" })).resolves.toEqual({ modelId: "local/other" });
    const call = fetchImpl.mock.calls.find(([url]) => String(url).endsWith("/api/assistant/model"));
    expect(call?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ modelId: "local/other" });
    fetchImpl.mockResolvedValueOnce(Response.json({ modelId: "wrong" }));
    await expect(host.request({ operation: "setModel", modelId: "local/other" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 409 }));
    await expect(host.request({ operation: "setModel", modelId: "local/other" })).rejects.toThrow("ASSISTANT_MODEL_BUSY");
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 422 }));
    await expect(host.request({ operation: "setModel", modelId: "local/other" })).rejects.toThrow("ASSISTANT_MODEL_INVALID");
    await host.stop();
  });
  it("vetoes lifecycle commit for an arriving message and admits the original request once after release", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const admission = host.beginLifecycleAdmission();
    await admission.seal();
    const request = { operation: "send" as const, message: "arriving user", requestId: "original-lifecycle-message" };
    const contents = { mainFrame: { url: LAUNCHER_ASSISTANT_URL }, isDestroyed: () => false };
    const sent = invokeAssistant({ sender: contents, senderFrame: contents.mainFrame }, request,
      { contents, host, setExpanded: vi.fn(), hide: vi.fn() });
    await Promise.resolve();
    expect(() => admission.commit()).toThrow("ASSISTANT_LIFECYCLE_BUSY");
    expect(fetchImpl.mock.calls.filter(call => String(call[0]).endsWith("/messages"))).toHaveLength(0);
    fetchImpl.mockResolvedValueOnce(Response.json({ accepted: true, sessionId: "s", clientSubmissionId: request.requestId, turnId: "s-turn" }));
    admission.release();
    await sent;
    const writes = fetchImpl.mock.calls.filter(call => String(call[0]).endsWith("/messages"));
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ message: request.message, requestId: request.requestId });
    await host.stop();
  });

  it("rejects a post-commit message before native admission so the persisted composer can retry its original ID", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const admission = host.beginLifecycleAdmission();
    await admission.seal(); admission.commit();
    const before = fetchImpl.mock.calls.length;
    const contents = { mainFrame: { url: LAUNCHER_ASSISTANT_URL }, isDestroyed: () => false };
    await expect(invokeAssistant({ sender: contents, senderFrame: contents.mainFrame },
      { operation: "send", message: "new draft", requestId: "after-commit" },
      { contents, host, setExpanded: vi.fn(), hide: vi.fn() })).rejects.toThrow("ASSISTANT_LIFECYCLE_CLOSING");
    expect(fetchImpl.mock.calls.length).toBe(before);
    admission.release();
    await host.stop();
  });

  it("lets a cancelled exit hand the sealed gates back so the stopped host starts again", async () => {
    const { host } = fixture({ graceful: true });
    await host.start();
    const admission = host.beginLifecycleAdmission();
    await admission.seal();
    admission.commit();
    await host.stop();
    // The retained lease release stayed blocked while Main counted as the
    // shutdown owner (reopen false), so both gates are still held here: the
    // exact stranded state after a cancelled exit. Every later start refuses
    // forever until Main explicitly hands the gates back.
    await expect(host.start()).rejects.toThrow("ASSISTANT_LIFECYCLE_CLOSING");
    host.resumeAfterCancelledExit();
    // The stale admission wrapper stays inert after recovery: releasing it
    // must not throw and must not reopen anything a fresh exit now owns.
    admission.release();
    await expect(host.start()).resolves.toMatchObject({ state: "ready" });
    // The migration gate reopens with the lifecycle gate; a later exit can
    // seal a fresh admission pair on the resumed host.
    const migration = host.beginMigrationAdmission();
    await migration.seal();
    migration.release();
    const next = host.beginLifecycleAdmission();
    await next.seal();
    next.commit();
    await host.stop();
  });

  it("recovers a sealed-but-uncommitted cancelled exit the same way and refuses a running host", async () => {
    const { host } = fixture({ graceful: true });
    await host.start();
    expect(() => host.resumeAfterCancelledExit()).toThrow("ASSISTANT_NOT_READY");
    const admission = host.beginLifecycleAdmission();
    await admission.seal();
    await host.stop();
    await expect(host.start()).rejects.toThrow("ASSISTANT_LIFECYCLE_CLOSING");
    host.resumeAfterCancelledExit();
    await expect(host.start()).resolves.toMatchObject({ state: "ready" });
    await host.stop();
  });

  it.each([
    ["native session conflict", 409, { detail: { code: "SESSION_CONFLICT" } }, "ASSISTANT_SESSION_CONFLICT"],
    ["retryable quiescing state", 503, { detail: { code: "ASSISTANT_QUIESCING" } }, "ASSISTANT_QUIESCING"],
    ["unrecognized migration wait", 503, { error: { code: "assistant_migration_wait" } }, "ASSISTANT_HTTP_FAILED"],
  ])("maps message submission failure %s from the structured error body", async (_label, status, body, expectedError) => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const request = { operation: "send" as const, message: "failure probe", requestId: "failure-probe-1" };
    fetchImpl.mockResolvedValueOnce(Response.json(body, { status }));
    // The submission stays a single delivery; retrying the idempotent requestId
    // is the renderer's decision, never an automatic host replay.
    await expect(host.request(request)).rejects.toThrow(expectedError);
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/api/assistant/messages"))).toHaveLength(1);
    await host.stop();
  });

  it("passes the attachment-read 404 through under its native code and keeps other unprefixed codes folded", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: { code: "ATTACHMENT_NOT_FOUND" } }, { status: 404 }));
    await expect(host.request({ operation: "readAttachment", artifactId: "gone-1" })).rejects.toThrow("ATTACHMENT_NOT_FOUND");
    // Only the explicitly listed unprefixed code crosses; a foreign code and a
    // bare 404 keep the legacy status-only fold, never an attachment verdict.
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: { code: "SOMETHING_ELSE" } }, { status: 404 }));
    await expect(host.request({ operation: "readAttachment", artifactId: "gone-2" })).rejects.toThrow("ASSISTANT_HTTP_FAILED");
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 404 }));
    await expect(host.request({ operation: "readAttachment", artifactId: "gone-3" })).rejects.toThrow("ASSISTANT_HTTP_FAILED");
    await host.stop();
  });

  it.each(["idle", "active", "unknown"] as const)("observes native %s privately and closes lifecycle admission before its final proof", async state => {
    const { host, fetchImpl } = fixture({ graceful: true });
    expect(await host.lifecycleStatus()).toBe("idle");
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state }));
    expect(await host.lifecycleStatus()).toBe(state);
    expect(String(fetchImpl.mock.calls.at(-1)![0])).toBe("http://127.0.0.1:12345/api/assistant/lifecycle-status");
    const admission = host.beginLifecycleAdmission();
    await admission.seal();
    expect(await host.lifecycleStatus()).toBe("unknown");
    expect(() => host.beginLifecycleAdmission()).toThrow("ASSISTANT_MIGRATION_BUSY");
    admission.release();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "idle", extra: true }));
    // An unparsable payload is a lost observation, not producer ambiguity.
    expect(await host.lifecycleStatus()).toBe("unobservable");
    await host.stop();
  });

  it.each([
    ["rpc timeout", () => new Error("ASSISTANT_REQUEST_TIMEOUT") as unknown],
    ["invalid payload", () => Response.json({ schemaVersion: 2, state: "active" }) as unknown],
    ["non-json body", () => new Response("not json", { status: 200, headers: { "content-type": "application/json" } }) as unknown]
  ])("classifies a lost observation (%s) as unobservable while the ready generation keeps serving", async (_label, failure) => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const response = failure() as Response | Error;
    if (response instanceof Response) fetchImpl.mockResolvedValueOnce(response);
    else fetchImpl.mockRejectedValueOnce(response);
    expect(await host.lifecycleStatus()).toBe("unobservable");
    // A later healthy poll recovers the idle proof instead of staying poisoned.
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "idle" }));
    expect(await host.lifecycleStatus()).toBe("idle");
    await host.stop();
  });

  it("keeps producer ambiguity unknown even when the observation itself failed", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "idle" }));
    expect(await host.lifecycleStatus()).toBe("idle");
    // A renderer write left in flight is a real producer: the held request
    // must keep the status unknown, never downgraded to unobservable.
    let release: ((response: Response) => void) | undefined;
    fetchImpl.mockImplementationOnce(() => new Promise<Response>((resolve) => { release = resolve; }));
    const pending = host.request({ operation: "send", message: "hello", requestId: "pending-write" });
    expect(await host.lifecycleStatus()).toBe("unknown");
    release!(Response.json({ assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" },
      settings: { managementPermission: { preset: "auto_review", revision: 0 } } }));
    await pending.catch(() => undefined);
    // The native side reporting its own uncertainty is producer ambiguity too.
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "unknown" }));
    expect(await host.lifecycleStatus()).toBe("unknown");
    await host.stop();
  });

  it.each<AssistantHostRequest>([
    { operation: "status" }, { operation: "detail" }, { operation: "dispatches" },
    { operation: "teamRuns" }, { operation: "config" }, { operation: "approvals" },
    { operation: "curation", sessionId: "s" }, { operation: "operatorAsset", kind: "avatar" },
    { operation: "assistantAvatar" }, { operation: "computerState" },
    { operation: "readAttachment", artifactId: "file-1" }
  ])("observes native lifecycle while a read-only $operation poll is pending", async request => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let release!: (response: Response) => void;
    fetchImpl.mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }));
    const pending = host.request(request).catch(() => undefined);
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, state: "idle" }));
    const state = await host.lifecycleStatus();
    release(Response.json({}));
    await pending;
    expect(state).toBe("idle");
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith("/api/assistant/lifecycle-status"))).toBe(true);
    await host.stop();
  });

  it("still drains read-only polls before sealing migration admission", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let release!: (response: Response) => void;
    fetchImpl.mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }));
    const pending = host.request({ operation: "status" }).catch(() => undefined);
    const admission = host.beginMigrationAdmission();
    let drained = false;
    const sealed = admission.seal().then(() => { drained = true; });
    await Promise.resolve();
    expect(drained).toBe(false);
    release(Response.json({}));
    await pending;
    await sealed;
    expect(drained).toBe(true);
    admission.release();
    await host.stop();
  });

  it.each(["idle", "failed"])("keeps a write arriving during a %s lifecycle probe unknown", async outcome => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let releaseObservation!: (response: Response) => void;
    let releaseWrite!: (response: Response) => void;
    fetchImpl.mockImplementationOnce(() => new Promise<Response>(resolve => { releaseObservation = resolve; }));
    const observation = host.lifecycleStatus();
    fetchImpl.mockImplementationOnce(() => new Promise<Response>(resolve => { releaseWrite = resolve; }));
    const pending = host.request({ operation: "send", message: "hello", requestId: "concurrent-write" }).catch(() => undefined);
    releaseObservation(outcome === "idle"
      ? Response.json({ schemaVersion: 1, state: "idle" })
      : new Response("invalid json", { status: 200 }));
    const state = await observation;
    releaseWrite(Response.json({}));
    await pending;
    expect(state).toBe("unknown");
    await host.stop();
  });

  it("classifies an observation failure caused by the host leaving its ready generation as unknown", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockRejectedValueOnce(new Error("ASSISTANT_REQUEST_TIMEOUT"));
    const observation = host.lifecycleStatus();
    await host.stop();
    expect(await observation).toBe("unknown");
  });

  it("binds read-only team pages to the current identity and a fixed endpoint", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const cursor = Buffer.from(JSON.stringify({ snapshot: "a".repeat(64), offset: 16 })).toString("base64url");
    const result = { schemaVersion: 1, assistant: { agentId: "a", directSessionId: "s" }, teamRuns: [], offset: 16 };
    fetchImpl.mockResolvedValueOnce(Response.json(result));
    await expect(host.request({ operation: "teamRuns", cursor })).resolves.toEqual(result);
    const call = fetchImpl.mock.calls.at(-1)!;
    expect(String(call[0])).toBe(`http://127.0.0.1:12345/api/assistant/team-runs?cursor=${cursor}`);
    expect(call[1]?.method).toBe("GET");
    expect(call[1]?.body).toBeUndefined();
    for (const assistant of [{ agentId: "other", directSessionId: "s" }, { agentId: "a", directSessionId: "other" }]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ ...result, assistant }));
      await expect(host.request({ operation: "teamRuns" })).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    }
    await host.stop();
  });

  it("leases the ready generation for the event pump and voids the lease on stop", async () => {
    const { host } = fixture({ graceful: true });
    expect(host.eventPumpLease()).toBeNull();
    await host.start();
    const lease = host.eventPumpLease();
    expect(lease).not.toBeNull();
    expect(lease!.origin).toBe("http://127.0.0.1:12345");
    expect(lease!.sessionId).toBe("s");
    expect(lease!.token).toMatch(/^[0-9a-f]{64}$/);
    expect(lease!.signal.aborted).toBe(false);
    await host.stop();
    expect(host.eventPumpLease()).toBeNull();
  });

  it("rejects team page URL, identity and cursor extensions before network access", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const reads = fetchImpl.mock.calls.length;
    for (const request of [
      { operation: "teamRuns", url: "https://example.com" },
      { operation: "teamRuns", projectId: "other" },
      { operation: "teamRuns", agentId: "other" },
      ...[undefined, null, "", "../private", "x\n", "x".repeat(257)].map(cursor => ({ operation: "teamRuns", cursor })),
    ]) await expect(host.request(request as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(reads);
    await host.stop();
  });

  it("passes team reads through the same owned-frame bridge gate", async () => {
    const contents = { mainFrame: { url: LAUNCHER_ASSISTANT_URL }, isDestroyed: () => false };
    const owner = { contents, host: { start: vi.fn().mockResolvedValue(undefined), request: vi.fn().mockResolvedValue({ teamRuns: [] }) },
      setExpanded: vi.fn(), hide: vi.fn() };
    const request = { operation: "teamRuns", cursor: "bounded" };
    await expect(invokeAssistant({ sender: contents, senderFrame: contents.mainFrame }, request, owner)).resolves.toEqual({ teamRuns: [] });
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith(request);
    await expect(invokeAssistant({ sender: {}, senderFrame: contents.mainFrame }, request, owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(owner.host.request).toHaveBeenCalledTimes(1);
  });

  it("rejects the retired panel operations without reaching the panels endpoint", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    // Well-formed requests in the shapes the removed branch used to accept.
    for (const request of [
      { operation: "panelSettings" }, { operation: "panelDialogue" }, { operation: "panelProposals" },
      { operation: "panelSettingsUpdate", payload: {} }, { operation: "panelModelUpdate", payload: { modelId: "m" } },
      { operation: "panelDialogueUpdate", payload: {} }, { operation: "panelAffairAdd", payload: { title: "x" } },
      { operation: "panelAffairs", kind: "todo", status: "open" },
      { operation: "panelAffairComplete", itemId: "i" }, { operation: "panelAffairCancel", itemId: "i" },
      { operation: "panelAffairReopen", itemId: "i" }, { operation: "panelAffairDue", itemId: "i", payload: { dueAt: null } },
      { operation: "panelProposalAccept", proposalId: "p" }, { operation: "panelProposalReject", proposalId: "p" },
    ]) await expect(host.request(request as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes("/api/assistant/panels"))).toBe(false);
    await host.stop();
  });
  it("only transports bound dispatch decisions with exact identities", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const request = { operation: "decideDispatchApproval" as const, dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: "a".repeat(64), decision: "accept" as const };
    await host.request(request);
    const call = fetchImpl.mock.calls.find(([url]) => String(url).endsWith("/dispatches/approval/decision"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: "a".repeat(64), decision: "accept" });
    await expect(host.request({ ...request, decision: "acceptAlways" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ ...request, dispatchId: "../other" })).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    for (const revision of ["", " ", "a".repeat(64) + "\n"]) {
      await expect(host.request({ ...request, revision })).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    const fallback = { operation: "declineDispatchApproval" as const, dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: "policy-1" };
    await host.request(fallback);
    await expect(host.request({ ...fallback, decision: "accept" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ ...fallback, revision: "" })).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await host.stop();
  });
  it("transports a fixed-session attachment and sends it without a renderer path", async () => {
    const { host, fetchImpl } = fixture();
    await host.start();
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toContain("/api/assistant/attachments/upload");
      expect(JSON.parse(String(options?.body))).toEqual({ filename: "note.txt", contentType: "text/plain", dataBase64: "Zml4dHVyZQ==" });
      return Response.json({ artifactId: "file-1", filename: "note.txt", contentType: "text/plain", sizeBytes: 7, kind: "user_document", status: "ready" });
    });
    const uploaded = await host.request({ operation: "uploadAttachment", filename: "note.txt", contentType: "text/plain", dataBase64: "Zml4dHVyZQ==" });
    expect(uploaded).toMatchObject({ artifactId: "file-1" });
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toContain("/api/assistant/messages");
      expect(JSON.parse(String(options?.body))).toEqual({ message: "", requestId: "request-1", attachmentIds: ["file-1"] });
      return Response.json({ accepted: true, turnId: "turn-1" });
    });
    await expect(host.request({ operation: "send", message: "", requestId: "request-1", attachmentIds: ["file-1"] })).resolves.toMatchObject({ accepted: true });
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toContain("/api/assistant/attachments/read");
      expect(JSON.parse(String(options?.body))).toEqual({ artifactId: "file-1" });
      return Response.json({ contentType: "text/plain", dataBase64: "Zml4dHVyZQ==" });
    });
    await expect(host.request({ operation: "readAttachment", artifactId: "file-1" })).resolves.toEqual({ contentType: "text/plain", dataBase64: "Zml4dHVyZQ==" });
    await expect(host.request({ operation: "readAttachment", artifactId: "../file" })).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ operation: "uploadAttachment", filename: "note.txt", contentType: "text/plain", dataBase64: "!!!!" })).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
  });
  it("stages a privacy secret through the closed native upload link", async () => {
    const { host, fetchImpl } = fixture();
    await host.start();
    // Legacy 4-field senders keep working; a labelled response echoes three keys.
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toContain("/api/assistant/attachments/upload");
      expect(JSON.parse(String(options?.body))).toEqual({ kind: "user_secret", value: "secret-value", secretKind: "api_key", label: "中转站" });
      return Response.json({ attachmentId: "sec_" + "a".repeat(32), kind: "user_secret", label: "中转站" });
    });
    const staged = await host.request({ operation: "upload_attachment", kind: "user_secret", value: "secret-value", secretKind: "api_key", label: "中转站" });
    expect(staged).toEqual({ attachmentId: "sec_" + "a".repeat(32), kind: "user_secret", label: "中转站" });
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      // Empty label stays out of the host body; the secret never echoes back.
      expect(JSON.parse(String(options?.body))).toEqual({ kind: "user_secret", value: "v", secretKind: "token" });
      return Response.json({ attachmentId: "sec_" + "b".repeat(32), kind: "user_secret" });
    });
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v", secretKind: "token", label: "" }))
      .resolves.toMatchObject({ kind: "user_secret" });
    // Generalized senders omit secretKind: it stays out of the forwarded body
    // and the host defaults it to "secret"; the label is still forwarded.
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      expect(JSON.parse(String(options?.body))).toEqual({ kind: "user_secret", value: "v", label: "显示名" });
      return Response.json({ attachmentId: "sec_" + "c".repeat(32), kind: "user_secret", label: "显示名" });
    });
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v", label: "显示名" }))
      .resolves.toEqual({ attachmentId: "sec_" + "c".repeat(32), kind: "user_secret", label: "显示名" });
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v", secretKind: "other" } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ operation: "upload_attachment", kind: "image", value: "v", secretKind: "api_key" } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: " ", secretKind: "api_key" } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    // Field sets outside the four allowed shapes (extra key) stay rejected.
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v", extra: 1 } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v", secretKind: "api_key", label: "x\ny" } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    // A 2-key response still passes; a malformed id or a 3-key response with
    // an invalid label is rejected.
    fetchImpl.mockImplementationOnce(async () => Response.json({ attachmentId: "file-1", kind: "user_secret" }));
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v" }))
      .rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockImplementationOnce(async () => Response.json({ attachmentId: "sec_" + "d".repeat(32), kind: "user_secret", label: "bad\nlabel" }));
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v" }))
      .rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockImplementationOnce(async () => Response.json({ attachmentId: "sec_" + "e".repeat(32), kind: "user_secret" }));
    await expect(host.request({ operation: "upload_attachment", kind: "user_secret", value: "v" }))
      .resolves.toMatchObject({ kind: "user_secret" });
  });
  it("retries the same migration host after a pre-spawn restart failure", async () => {
    const { host, native, root } = fixture({ graceful: true });
    Object.assign(native, { exitCode: vi.fn(() => 0) });
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    expect(await host.retireForMigration()).toBe(true);
    const snapshot = { schemaVersion: 1 as const, revision: 0, projects: { project: root } };
    host.prepareForMigrationRestart(snapshot, false);
    native.spawn.mockImplementationOnce(() => { throw new Error("synthetic spawn failure"); });
    await expect(host.startForMigration()).rejects.toThrow();
    host.prepareForMigrationRestart(snapshot, false);
    await expect(host.startForMigration()).resolves.toMatchObject({ state: "ready" });
    expect(native.terminate).not.toHaveBeenCalled();
    admission.release();
    await host.stop();
  });

  it("keeps an unconfirmed failed restart Job until its actual exit and output drain", async () => {
    const { host, native, root, active, fetchImpl } = fixture({ graceful: true });
    let exited = true, drained = true;
    Object.assign(native, { exitCode: vi.fn(() => exited ? 0 : null) });
    native.drainStatus.mockImplementation(() => ({ complete: drained, channels: [] }));
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    expect(await host.retireForMigration()).toBe(true);
    const snapshot = { schemaVersion: 1 as const, revision: 0, projects: { project: root } };
    host.prepareForMigrationRestart(snapshot, false);
    exited = false; drained = false;
    fetchImpl.mockResolvedValueOnce(Response.json({ status: "invalid" }));
    // Lost shutdown acknowledgement: the same Job must remain owned until it
    // actually exits and drains, even though the private request was sent.
    fetchImpl.mockRejectedValueOnce(new Error("shutdown reply lost"));
    await expect(host.startForMigration()).rejects.toThrow("ASSISTANT_HEALTH_INVALID");
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(2);
    expect(() => host.prepareForMigrationRestart(snapshot, false)).toThrow("ASSISTANT_DRAIN_PENDING");
    await expect(host.stop()).rejects.toThrow("ASSISTANT_DRAIN_PENDING");
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(native.terminate).not.toHaveBeenCalled();
    const job = [...active.keys()][0];
    active.set(job, 0); exited = true;
    expect(() => host.prepareForMigrationRestart(snapshot, false)).toThrow("ASSISTANT_DRAIN_PENDING");
    drained = true;
    host.prepareForMigrationRestart(snapshot, false);
    await expect(host.startForMigration()).resolves.toMatchObject({ state: "ready" });
    expect(native.terminate).not.toHaveBeenCalled();
    admission.release();
    await host.stop();
  });

  it("gracefully shuts down the reachable failed migration startup before retry", async () => {
    const { host, native, root, fetchImpl } = fixture({ graceful: true });
    Object.assign(native, { exitCode: vi.fn(() => 0) });
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    expect(await host.retireForMigration()).toBe(true);
    const snapshot = { schemaVersion: 1 as const, revision: 0, projects: { project: root } };
    host.prepareForMigrationRestart(snapshot, true);
    fetchImpl.mockResolvedValueOnce(Response.json({ status: "invalid" }));
    await expect(host.startForMigration()).rejects.toThrow("ASSISTANT_HEALTH_INVALID");
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(2);
    expect(native.terminate).not.toHaveBeenCalled();
    host.prepareForMigrationRestart(snapshot, true);
    await expect(host.startForMigration()).resolves.toMatchObject({ state: "ready" });
    admission.release();
    await host.stop();
  });

  it.each([
    ["HTTP error", () => new Response("failure", { status: 500 }), "ASSISTANT_HTTP_FAILED"],
    ["invalid JSON", () => new Response("invalid", { status: 200 }), "ASSISTANT_RESPONSE_INVALID"],
  ])("requests shutdown after startup health returns %s", async (_label, response, expectedError) => {
    const { host, native, root, fetchImpl } = fixture({ graceful: true });
    Object.assign(native, { exitCode: vi.fn(() => 0) });
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    expect(await host.retireForMigration()).toBe(true);
    const snapshot = { schemaVersion: 1 as const, revision: 0, projects: { project: root } };
    host.prepareForMigrationRestart(snapshot, true);
    fetchImpl.mockResolvedValueOnce(response());
    await expect(host.startForMigration()).rejects.toThrow(expectedError);
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(2);
    expect(native.terminate).not.toHaveBeenCalled();
    host.prepareForMigrationRestart(snapshot, true);
    await expect(host.startForMigration()).resolves.toMatchObject({ state: "ready" });
    admission.release();
    await host.stop();
  });

  it("retains an unreachable startup Job when its shutdown request also fails", async () => {
    const { host, native, root, fetchImpl } = fixture({ graceful: true });
    const exitCode = vi.fn<() => number | null>(() => null);
    Object.assign(native, { exitCode });
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    // The first host is known drained; the new Job stays unconfirmed.
    exitCode.mockReturnValueOnce(0);
    expect(await host.retireForMigration()).toBe(true);
    const snapshot = { schemaVersion: 1 as const, revision: 0, projects: { project: root } };
    host.prepareForMigrationRestart(snapshot, true);
    let healthStarted = false;
    fetchImpl.mockImplementation(async (url, init) => {
      if (String(url).endsWith("/health")) {
        healthStarted = true;
        return await new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("unreachable")), { once: true });
        });
      }
      throw new Error("unreachable");
    });
    const startup = expect(host.startForMigration()).rejects.toThrow();
    await vi.waitFor(() => expect(healthStarted).toBe(true));
    const stopping = expect(host.stop()).rejects.toThrow("ASSISTANT_DRAIN_PENDING");
    await startup;
    await stopping;
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(2);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(() => host.prepareForMigrationRestart(snapshot, true)).toThrow("ASSISTANT_DRAIN_PENDING");
    admission.release();
  });

  it("keeps approvals usable while waiting and fences them only for the final proof", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const fence = host.beginMigrationAdmission();
    await host.start();
    await host.request({ operation: "resolveApproval", requestId: "approval-1", decision: "accept" });
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith("/approvals/decision"))).toBe(true);
    await fence.seal();
    const blocked = host.request({ operation: "resolveApproval", requestId: "approval-2", decision: "accept" });
    await Promise.resolve();
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/approvals/decision"))).toHaveLength(1);
    fence.release();
    await blocked;
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/approvals/decision"))).toHaveLength(2);
    await host.stop();
  });

  it("keeps the same migration Job until root exit and both output drains are confirmed", async () => {
    const { host, native, fetchImpl, active } = fixture();
    let exit: number | null = null;
    let outputDrained = false;
    Object.assign(native, { exitCode: vi.fn(() => exit) });
    native.drainStatus.mockImplementation(() => ({ complete: outputDrained, channels: [] }));
    await host.start();
    const admission = host.beginMigrationAdmission();
    await admission.seal();
    expect(await host.retireForMigration()).toBe(false);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.close).not.toHaveBeenCalled();
    await expect(host.startForMigration()).rejects.toThrow("ASSISTANT_JOB_STILL_OWNED");
    await expect(host.stop()).rejects.toThrow("ASSISTANT_DRAIN_PENDING");
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.close).not.toHaveBeenCalled();
    const job = [...active.keys()][0];
    active.set(job, 0);
    expect(await host.retireForMigration()).toBe(false);
    exit = 0;
    expect(await host.retireForMigration()).toBe(false);
    outputDrained = true;
    expect(await host.retireForMigration()).toBe(true);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.close).toHaveBeenCalledOnce();
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/shutdown"))).toHaveLength(1);
    admission.release();
  });

  it("retires a crashed barrier owner only after its exact Job and output drain", async () => {
    const { host, native, active, fetchImpl } = fixture();
    let exit: number | null = null, drained = false;
    Object.assign(native, { exitCode: vi.fn(() => exit) });
    native.drainStatus.mockImplementation(() => ({ complete: drained, channels: [] }));
    await host.start();
    let finishRequest!: (response: Response) => void;
    fetchImpl.mockImplementationOnce(async () => await new Promise<Response>(resolve => { finishRequest = resolve; }));
    const request = host.request({ operation: "send", message: "queued", requestId: "one" });
    await vi.waitFor(() => expect(finishRequest).toBeTypeOf("function"));
    const admission = host.beginMigrationAdmission();
    const sealing = admission.seal();
    const job = [...active.keys()][0];
    active.set(job, 0); exit = 0; drained = true;
    expect(host.prepareDeadForMigrationRetirement()).toBe(false);
    finishRequest(Response.json({ accepted: true }));
    await request;
    await sealing;
    active.set(job, 1); exit = null; drained = false;
    expect(host.prepareDeadForMigrationRetirement()).toBe(false);
    active.set(job, 0);
    expect(host.prepareDeadForMigrationRetirement()).toBe(false);
    exit = 0;
    expect(host.prepareDeadForMigrationRetirement()).toBe(false);
    drained = true;
    expect(host.prepareDeadForMigrationRetirement()).toBe(true);
    expect(await host.retireForMigration()).toBe(true);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.close).toHaveBeenCalledOnce();
    admission.release();
  });

  it("drains already admitted renderer calls and keeps later message identity until release", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let finishFirst!: (response: Response) => void;
    fetchImpl.mockImplementationOnce(async () => await new Promise<Response>(done => { finishFirst = done; }));
    const first = host.request({ operation: "send", message: "first", requestId: "first-id" });
    await vi.waitFor(() => expect(finishFirst).toBeTypeOf("function"));
    const fence = host.beginMigrationAdmission();
    const sealing = fence.seal();
    let startReturned = false;
    const bridgeStart = host.start().then(() => { startReturned = true; });
    let drained = false;
    void fence.drained.then(() => { drained = true; });
    const message = { operation: "send" as const, message: "keep me", requestId: "original-id" };
    const later = host.request(message);
    message.message = "changed after admission";
    await Promise.resolve();
    expect(drained).toBe(false);
    expect(startReturned).toBe(false);
    finishFirst(Response.json({ accepted: true }));
    await first;
    await fence.drained;
    await sealing;
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/messages"))).toHaveLength(1);
    fence.release();
    await bridgeStart;
    await later;
    const writes = fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/messages"));
    expect(writes).toHaveLength(2);
    expect(JSON.parse(String(writes[1][1]?.body))).toEqual({ message: "keep me", requestId: "original-id" });
    await host.stop();
  });

  it("routes only the five fixed computer verbs with bounded DTOs and main-owned credentials", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const idle = { available: true, status: "idle", message: "", grantId: null, window: null, pending: null };
    const rows = [
      [{ operation: "computerState" }, "/api/assistant/computer", "GET", undefined, idle],
      [{ operation: "computerWindows" }, "/api/assistant/computer/windows", "POST", {}, { windows: [{ selectionId: "sel", title: "Title", appName: "App" }] }],
      [{ operation: "computerGrant", selectionId: "sel", allowVision: true }, "/api/assistant/computer/grant", "POST", { selectionId: "sel", allowVision: true }, idle],
      [{ operation: "computerControl", grantId: "grant", action: "pause" }, "/api/assistant/computer/control", "POST", { grantId: "grant", action: "pause" }, idle],
      [{ operation: "computerConfirm", grantId: "grant", pendingId: "pending", approved: false }, "/api/assistant/computer/confirm", "POST", { grantId: "grant", pendingId: "pending", approved: false }, idle],
    ] as const;
    for (const [request, path, method, body, result] of rows) {
      fetchImpl.mockImplementationOnce(async (url, options) => {
        expect(String(url)).toMatch(new RegExp(path + "$"));
        expect(options?.method).toBe(method);
        expect(new Headers(options?.headers).get("authorization")).toMatch(/^Bearer /);
        expect(options?.body ? JSON.parse(String(options.body)) : undefined).toEqual(body);
        return Response.json(result);
      });
      expect(await host.request(request as AssistantHostRequest)).toEqual(result);
    }
    const count = fetchImpl.mock.calls.length;
    for (const bad of [
      { operation: "computerGrant", selectionId: "x", allowVision: false },
      { operation: "computerConfirm", grantId: "g", pendingId: "p", approved: "yes" },
      { operation: "computerControl", grantId: "g", action: "click" },
      { operation: "computerState", url: "http://external" },
      { operation: "computerWindows", selectionId: "untrusted" },
    ]) await expect(host.request(bad as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl.mock.calls).toHaveLength(count);
    fetchImpl.mockResolvedValueOnce(Response.json({ ...idle, path: "private" }));
    await expect(host.request({ operation: "computerState" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    await host.stop();
  });

  it("passes the computer router's root-cause codes through to the renderer", async () => {
    // computer_control.py splits driver outage (503), moved operator state
    // (409) and a request that can never bind (422); the structured codes must
    // cross the host instead of folding back into ASSISTANT_HTTP_FAILED.
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const rows = [
      [503, { detail: { code: "ASSISTANT_COMPUTER_DRIVER_UNAVAILABLE", message: "driver" } }, "ASSISTANT_COMPUTER_DRIVER_UNAVAILABLE"],
      [409, { detail: { code: "ASSISTANT_COMPUTER_STATE_CHANGED", message: "state" } }, "ASSISTANT_COMPUTER_STATE_CHANGED"],
      [422, { detail: { code: "ASSISTANT_COMPUTER_REQUEST_INVALID", message: "invalid" } }, "ASSISTANT_COMPUTER_REQUEST_INVALID"],
    ] as const;
    for (const [status, body, expected] of rows) {
      fetchImpl.mockResolvedValueOnce(Response.json(body, { status }));
      await expect(host.request({ operation: "computerState" })).rejects.toThrow(expected);
    }
    // A legacy string detail (or unparseable body) keeps the status-only fold.
    fetchImpl.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 409 }));
    await expect(host.request({ operation: "computerState" })).rejects.toThrow("ASSISTANT_HTTP_FAILED");
    await host.stop();
  });

  it("forwards only valid optional computer authorization request IDs", async () => {
    const { host, fetchImpl } = fixture({ graceful: true }); await host.start();
    const idle = { available: true, status: "idle", message: "", grantId: null, window: null, pending: null };
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      expect(JSON.parse(String(options?.body))).toEqual({ selectionId: "sel", allowVision: true, authorizationRequestId: "req" });
      return Response.json(idle);
    });
    await host.request({ operation: "computerGrant", selectionId: "sel", allowVision: true, authorizationRequestId: "req" });
    for (const authorizationRequestId of [null, "", "x".repeat(101)]) {
      await expect(host.request({ operation: "computerGrant", selectionId: "sel", allowVision: true, authorizationRequestId } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    await host.stop();
  });

  it("accepts only the bounded operator authorization hint and rejects extra metadata", async () => {
    const { host, fetchImpl } = fixture({ graceful: true }); await host.start();
    const idle = { available: true, status: "idle", message: "", grantId: null, window: null, pending: null };
    const request = { id: "request", agentId: "assistant", sessionId: "session", turnId: "turn" };
    for (const authorizationRequest of [null, request]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ ...idle, authorizationRequest }));
      expect(await host.request({ operation: "computerState" })).toEqual({ ...idle, authorizationRequest });
    }
    for (const authorizationRequest of [{ ...request, title: "private" }, { ...request, turnId: "" }, { ...request, id: "x".repeat(101) }]) {
      fetchImpl.mockResolvedValueOnce(Response.json({ ...idle, authorizationRequest }));
      await expect(host.request({ operation: "computerState" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
    fetchImpl.mockResolvedValueOnce(Response.json({ ...idle, grantId: "grant", window: { selectionId: "s", title: "t", appName: "a" }, authorizationRequest: request }));
    await expect(host.request({ operation: "computerState" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockResolvedValueOnce(Response.json({ ...idle, status: "manual", authorizationRequest: request }));
    await expect(host.request({ operation: "computerState" })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    await host.stop();
  });

  it("lets the assistant view and confirm an existing computer action while a sealed migration waits", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const fence = host.beginMigrationAdmission(); await fence.seal();
    const state = { available: true, status: "waiting_confirmation", message: "", grantId: "g",
      window: { selectionId: "sel", title: "Title", appName: "App" },
      pending: { id: "p", action: "click", targetLabel: "Button", text: null } };
    const idle = { available: true, status: "idle", message: "", grantId: null, window: null, pending: null };
    const frame = { url: LAUNCHER_ASSISTANT_URL }, contents = { mainFrame: frame, isDestroyed: () => false };
    const owner = { contents, host, hide: () => {}, setExpanded: () => undefined };
    const event = { sender: contents, senderFrame: frame };
    const queued = invokeAssistant(event, { operation: "computerGrant", selectionId: "sel", allowVision: true }, owner);
    fetchImpl.mockResolvedValueOnce(Response.json(state));
    expect(await invokeAssistant(event, { operation: "computerState" }, owner)).toEqual(state);
    fetchImpl.mockResolvedValueOnce(Response.json(idle));
    expect(await invokeAssistant(event, { operation: "computerConfirm", grantId: "g", pendingId: "p", approved: false }, owner)).toEqual(idle);
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/computer/grant"))).toHaveLength(0);
    fetchImpl.mockResolvedValueOnce(Response.json(idle));
    fence.release(); expect(await queued).toEqual(idle);
    await host.stop();
  });

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
    fetchImpl.mockResolvedValueOnce(Response.json({ ...identity, ledgerKey: "c".repeat(64) }));
    await expect(host.observeLegacyReminderLedger("project", 0)).resolves.toEqual({ ...identity, ledgerKey: "c".repeat(64) });
    fetchImpl.mockResolvedValueOnce(Response.json({ ...identity, ledgerKey: "not-a-digest" }));
    await expect(host.observeLegacyReminderLedger("project", 0)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
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

  it("releases the original main-generated source permit even when acquire acknowledgement is lost", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let permitId = "";
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      permitId = JSON.parse(String(options?.body)).permitId;
      expect(permitId).toMatch(/^[a-f0-9]{64}$/);
      throw new Error("response lost");
    });
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/legacy-reminders\/permit\/release$/);
      expect(JSON.parse(String(options?.body))).toEqual({ permitId });
      return Response.json({ schemaVersion: 1, released: true });
    });
    await expect(host.acquireLegacyReminderPermit("project", 0)).rejects.toThrow();
    await host.stop();
  });

  it("waits for a confirmed permit release and retries with the original ID", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const ledgerKey = "c".repeat(64);
    const proof = { schemaVersion: 1, ledgerKey, coverage: "cooperating_route_writers", unmanagedSenders: "unknown", readyForCutover: false };
    let permitId = "";
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      permitId = JSON.parse(String(options?.body)).permitId;
      return Response.json({ ...proof, permitId });
    });
    fetchImpl.mockResolvedValueOnce(Response.json(proof));
    const permit = await host.acquireLegacyReminderPermit("project", 0);
    fetchImpl.mockImplementationOnce(async () => { throw new Error("release response lost"); });
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      expect(JSON.parse(String(options?.body))).toEqual({ permitId });
      return Response.json({ schemaVersion: 1, released: true });
    });
    await permit.release();
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/permit/release"))).toHaveLength(2);
    await host.stop();
  });

  it("keeps source permit private, checks the pinned ledger and explicitly releases it", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const ledgerKey = "c".repeat(64);
    let permitId = "";
    const proof = { schemaVersion: 1, ledgerKey, coverage: "cooperating_route_writers", unmanagedSenders: "unknown", readyForCutover: false };
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      permitId = JSON.parse(String(options?.body)).permitId;
      return Response.json({ ...proof, permitId });
    });
    fetchImpl.mockResolvedValueOnce(Response.json(proof));
    const permit = await host.acquireLegacyReminderPermit("project", 0);
    expect(permit.ledgerKey).toBe(ledgerKey);
    fetchImpl.mockResolvedValueOnce(Response.json({ ...proof, ledgerKey: "d".repeat(64) }));
    await expect(permit.check()).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    fetchImpl.mockImplementationOnce(async (_url, options) => {
      expect(JSON.parse(String(options?.body))).toEqual({ permitId });
      return Response.json({ schemaVersion: 1, released: true });
    });
    await permit.release();
    await expect(permit.check()).rejects.toThrow();
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
  it("reads a validated private full legacy reminder inventory", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const row = { day: "20261028", eventKey: "legacy:" + "a".repeat(64), state: "pending", channel: null, inflight: true };
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/legacy-reminders\/inventory$/);
      expect(JSON.parse(String(options?.body))).toEqual({});
      expect(new Headers(options?.headers).get("authorization")).toMatch(/^Bearer /);
      return Response.json({ schemaVersion: 1, records: [row], senders: 1 });
    });
    expect(await host.inventoryLegacyReminders()).toEqual({ schemaVersion: 1, records: [row], senders: 1 });
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, records: [{ ...row, channel: "system_notification" }], senders: 1 }));
    await expect(host.inventoryLegacyReminders()).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    await expect(host.request({ operation: "legacy-reminders/inventory" } as never)).rejects.toThrow();
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
  it.each([false, true])("accepts only an unknown-baseline reminder handoff binding (recovery=%s)", async (reauthorize) => {
    const { host, fetchImpl } = fixture({ graceful: true, initialMigrationControl: true });
    await host.start();
    const projectId = "project", digest = createHash("sha256").update(`${projectId}:reminder_handoff`).digest("hex").slice(0, 40);
    const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue" as const, projectId,
      previewId: "b".repeat(64), turnId: "turn-1", category: "reminder_handoff" as const,
      operationId: `initial-${digest}`, timeoutMs: 10000, ...(reauthorize ? { reauthorize: true as const } : {}) };
    const directory = { device: "1", inode: "2", birthtimeNs: "3" };
    const binding = { schemaVersion: 1, registeredProjectId: projectId,
      sourceScope: { projectId: "source", instanceId: "instance", agentId: "agent" }, category: row.category,
      turnId: row.turnId, operationId: row.operationId, syncId: `affairs-${digest}`, revision: 0,
      sourceIdentityDigest: "a".repeat(64), registryDigest: "b".repeat(64), targetIdentityDigest: "c".repeat(64),
      projectDirectory: directory, workspaceDirectory: directory, targetDirectory: directory,
      targetAgentId: "agent", targetSessionId: "session", authority: "native_policy_admitted",
      baselineId: null, baselineState: "unknown", readyForCutover: false };
    fetchImpl.mockResolvedValueOnce(Response.json(binding));
    await expect(host.prepareInitialMigration(row, 0)).resolves.toBe(true);
    const sent = JSON.parse(String(fetchImpl.mock.calls.at(-1)?.[1]?.body));
    expect(sent.reauthorize).toBe(reauthorize ? true : undefined);
    fetchImpl.mockResolvedValueOnce(Response.json({ ...binding, baselineState: "verified" }))
      .mockResolvedValueOnce(Response.json({ schemaVersion: 1, operationId: row.operationId, state: "unknown", drained: true }));
    await expect(host.prepareInitialMigration(row, 0)).resolves.toBe(false);
    await host.stop();
  });
  it("reads only the original native handoff receipt with false cutover", async () => {
    const { host, fetchImpl } = fixture({ graceful: true, initialMigrationControl: true });
    await host.start();
    const projectId = "project", digest = createHash("sha256").update(`${projectId}:reminder_handoff`).digest("hex").slice(0, 40);
    const result = { schemaVersion: 1, projectId, operationId: `initial-${digest}`, syncId: `affairs-${digest}`,
      state: "pending", code: "source_proof_unavailable", baselineState: "unknown", readyForCutover: false };
    fetchImpl.mockResolvedValueOnce(Response.json(result));
    expect(await host.reminderHandoffReceipt(projectId, 0)).toBe("pending");
    fetchImpl.mockResolvedValueOnce(Response.json({ ...result, readyForCutover: true }));
    await expect(host.reminderHandoffReceipt(projectId, 0)).rejects.toThrow();
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
  it("accepts only the bound explicit busy acknowledgement and drains malformed acknowledgements", async () => {
    const { host, fetchImpl } = fixture({ graceful: true, initialMigrationControl: true });
    await host.start();
    const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue" as const, projectId: "project",
      previewId: "b".repeat(64), turnId: "turn-1", category: "knowledge" as const,
      operationId: "initial-" + "c".repeat(40), timeoutMs: 10000 };
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, operationId: row.operationId, state: "rejected", code: "busy" }));
    expect(await host.prepareInitialMigration(row, 0)).toBe("busy");
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, operationId: "initial-" + "d".repeat(40), state: "rejected", code: "busy" }))
      .mockResolvedValueOnce(Response.json({ schemaVersion: 1, operationId: row.operationId, state: "unknown", drained: true }));
    expect(await host.prepareInitialMigration(row, 0)).toBe(false);
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
  it("fences episodic sync on cancellation without replay", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    let started = false, operationId = "";
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/episodic-sync$/);
      operationId = JSON.parse(String(options?.body)).operationId; started = true;
      return await new Promise<Response>((_resolve, reject) => options?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    }).mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/episodic-sync\/cancel$/);
      expect(JSON.parse(String(options?.body))).toEqual({ operationId, previewId: "a".repeat(64) });
      return Response.json({ schemaVersion: 1, operationId, cancelled: true });
    });
    const controller = new AbortController();
    const pending = host.syncEpisodic({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", revision: 0, signal: controller.signal });
    await vi.waitFor(() => expect(started).toBe(true)); controller.abort();
    await expect(pending).resolves.toMatchObject({ state: "unknown", migrationId: expect.stringMatching(/^episodic-/) });
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/episodic-sync"))).toHaveLength(1);
    await host.stop();
  });
  it("sends a reviewed episodic resolution without exposing a path", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const previewId = "a".repeat(64), resolveSyncId = "episodic-" + "b".repeat(40), reviewToken = "c".repeat(64);
    const migrationId = "episodic-" + createHash("sha256").update(`project:${previewId}`).digest("hex").slice(0, 40);
    fetchImpl.mockImplementationOnce(async (url, options) => {
      expect(String(url)).toMatch(/\/episodic-sync$/);
      expect(JSON.parse(String(options?.body))).toEqual({ projectId: "project", previewId, turnId: "turn-1", revision: 0,
        operationId: expect.stringMatching(/^[a-f0-9]{32}$/), resolveSyncId, reviewToken });
      return Response.json({ schemaVersion: 1, projectId: "project", previewId, migrationId,
        state: "complete", code: "resolved", appliedCount: 0, conflictCount: 0, readyForCutover: false });
    });
    await expect(host.syncEpisodic({ projectId: "project", previewId, turnId: "turn-1", revision: 0, resolveSyncId, reviewToken }))
      .resolves.toMatchObject({ state: "complete", code: "resolved" });
    await expect(host.syncEpisodic({ projectId: "project", previewId, turnId: "turn-1", revision: 0, resolveSyncId }))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
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
    const pending = host.importHistory({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", operationId: "b".repeat(32), revision: 0, signal: controller.signal });
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
    await expect(host.importHistory({ projectId: "project", previewId: "a".repeat(64), turnId: "turn-1", operationId: "b".repeat(32), revision: 0, signal: controller.signal }))
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
  it("restricts assistant avatar to the pinned identity, fixed path and ordinary response budget", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, agentId: "a", image: null }));
    await expect(host.request({ operation: "assistantAvatar" })).resolves.toEqual({ schemaVersion: 1, agentId: "a", image: null });
    expect(String(fetchImpl.mock.calls.at(-1)?.[0])).toBe("http://127.0.0.1:12345/api/assistant/avatar");
    const calls = fetchImpl.mock.calls.length;
    for (const extra of [{ path: "/api/private" }, { url: "http://example.test" }, { agentId: "other" }]) {
      await expect(host.request({ operation: "assistantAvatar", ...extra } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    expect(fetchImpl).toHaveBeenCalledTimes(calls);
    fetchImpl.mockResolvedValueOnce(Response.json({ schemaVersion: 1, agentId: "other", image: null }));
    await expect(host.request({ operation: "assistantAvatar" })).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    fetchImpl.mockResolvedValueOnce(new Response("{}", { headers: { "content-length": String(9 * 1024 * 1024) } }));
    await expect(host.request({ operation: "assistantAvatar" })).rejects.toThrow("ASSISTANT_RESPONSE_TOO_LARGE");
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
  it("switches the conversation version head once and rejects extra authority", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ id: "s", messages: [] }));
    await host.request({ operation: "switchHead", nodeId: "target-node" } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[0]).toContain("/api/assistant/head");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.method).toBe("POST");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ nodeId: "target-node" }));
    const before = fetchImpl.mock.calls.length;
    for (const value of [
      { operation: "switchHead", nodeId: "target-node", sessionId: "other" },
      { operation: "switchHead", nodeId: "   " },
      { operation: "switchHead", nodeId: 7 },
    ]) await expect(host.request(value as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    fetchImpl.mockResolvedValueOnce(Response.json({ id: "other-session", messages: [] }));
    await expect(host.request({ operation: "switchHead", nodeId: "target-node" } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    fetchImpl.mockRejectedValueOnce(new Error("ack lost"));
    await expect(host.request({ operation: "switchHead", nodeId: "target-node" } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_TRANSPORT_FAILED");
    await host.stop();
  });
  it("regenerates once with a stable request id and rejects malformed authority", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ id: "s", messages: [] }));
    await host.request({ operation: "regenerate", messageId: "target-message", requestId: "regen-1" } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[0]).toContain("/api/assistant/messages/regenerate");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ messageId: "target-message", requestId: "regen-1" }));
    const before = fetchImpl.mock.calls.length;
    for (const value of [
      { operation: "regenerate", messageId: "target-message", requestId: "regen-1", sessionId: "other" },
      { operation: "regenerate", messageId: "   ", requestId: "regen-1" },
      { operation: "regenerate", messageId: "target-message", requestId: "bad id" },
      { operation: "regenerate", messageId: "target-message" },
    ]) await expect(host.request(value as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    fetchImpl.mockResolvedValueOnce(Response.json({ id: "other-session", messages: [] }));
    await expect(host.request({ operation: "regenerate", messageId: "target-message", requestId: "regen-1" } as AssistantHostRequest)).rejects.toThrow("ASSISTANT_IDENTITY_INVALID");
    await host.stop();
  });
  it("carries bounded reference chips on the send verb and rejects malformed chips", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const reference = { kind: "message", referenceId: "message:m1", sourceSessionId: "s", sourceMessageId: "m1", quote: "text" };
    fetchImpl.mockResolvedValueOnce(Response.json({ accepted: true, sessionId: "s", turnId: "turn-1" }));
    await host.request({ operation: "send", message: "see this", requestId: "send-refs", references: [reference] } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ message: "see this", requestId: "send-refs", references: [reference] }));
    const before = fetchImpl.mock.calls.length;
    for (const value of [
      { operation: "send", message: "see this", requestId: "send-refs", references: "chip" },
      { operation: "send", message: "see this", requestId: "send-refs", references: [reference, reference, reference, reference, reference, reference, reference, reference, reference] },
      { operation: "send", message: "see this", requestId: "send-refs", references: ["plain"] },
    ]) await expect(host.request(value as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
    await host.stop();
  });
  it("steers the running turn with bounded guidance content only", async () => {
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    fetchImpl.mockResolvedValueOnce(Response.json({ id: "s" }));
    await host.request({ operation: "guidance", content: "hold on", mode: "safe" } as AssistantHostRequest);
    expect(fetchImpl.mock.calls.at(-1)?.[0]).toContain("/api/assistant/guidance");
    expect(fetchImpl.mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({ content: "hold on", mode: "safe" }));
    const before = fetchImpl.mock.calls.length;
    for (const value of [
      { operation: "guidance", content: "hold on", mode: "safe", sessionId: "other" },
      { operation: "guidance", content: "   ", mode: "safe" },
      { operation: "guidance", content: "hold on", mode: "unsafe" },
      { operation: "guidance", mode: "safe" },
    ]) await expect(host.request(value as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(fetchImpl).toHaveBeenCalledTimes(before);
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

  it("gives light UI reads shorter RPC budgets than writes", async () => {
    vi.useFakeTimers();
    const { host, fetchImpl } = fixture({ graceful: true });
    await host.start();
    const expectTimeoutAt = async (request: AssistantHostRequest, budgetMs: number) => {
      let timedOut = false;
      fetchImpl.mockImplementationOnce(async (_url, init) => await new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("hung")), { once: true });
      }));
      const pending = host.request(request).catch((error: unknown) => {
        timedOut = error instanceof Error && error.message === "ASSISTANT_REQUEST_TIMEOUT";
      });
      await vi.advanceTimersByTimeAsync(budgetMs - 1);
      expect(timedOut).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await pending;
      expect(timedOut).toBe(true);
    };
    await expectTimeoutAt({ operation: "status" }, 5_000);
    for (const operation of ["detail", "dispatches", "config", "approvals", "teamRuns"] as const) {
      await expectTimeoutAt({ operation } as AssistantHostRequest, 8_000);
    }
    await expectTimeoutAt({ operation: "curation", sessionId: "s" }, 8_000);
    await expectTimeoutAt({ operation: "assistantAvatar" }, 8_000);
    // Writes keep the original request budget; the read tier never shortened them.
    await expectTimeoutAt({ operation: "send", message: "hello", requestId: "write-budget" }, 15_000);
    await host.stop();
  });

  it("bounds a read invoke's startup wait while a write keeps the full recovery", async () => {
    vi.useFakeTimers();
    const { host, inputs, fetchImpl } = fixture({ noReadyFirst: true, graceful: true });
    const frame = { url: LAUNCHER_ASSISTANT_URL };
    const contents = { mainFrame: frame, isDestroyed: () => false };
    const owner = { contents, host, setExpanded: vi.fn(), hide: vi.fn() };
    const event = { sender: contents, senderFrame: frame };
    let readFailure = "";
    const read = invokeAssistant(event, { operation: "status" }, owner)
      .catch((error: unknown) => { readFailure = error instanceof Error ? error.message : ""; });
    await vi.advanceTimersByTimeAsync(1_999);
    expect(readFailure).toBe("");
    await vi.advanceTimersByTimeAsync(1);
    await read;
    expect(readFailure).toBe("ASSISTANT_NOT_READY");
    // A write invoke still owns the full recovery: it joins the same start and
    // is delivered once readiness lands, never failing fast at the grace mark.
    let writeSettled = "";
    const write = invokeAssistant(event, { operation: "send", message: "during start", requestId: "start-write" }, owner)
      .then(() => { writeSettled = "ok"; }, (error: unknown) => { writeSettled = error instanceof Error ? error.message : ""; });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(writeSettled).toBe("");
    const input = inputs[0]!;
    const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1] as string;
    const generation = input.arguments[input.arguments.indexOf("--instance-id") + 1] as string;
    writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant",
      instanceId: generation, pid: 900, port: 12_345 }));
    await vi.advanceTimersByTimeAsync(100);
    await write;
    expect(writeSettled).toBe("ok");
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(fetchImpl.mock.calls.filter(([url]) => String(url).endsWith("/messages"))).toHaveLength(1);
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

describe("AssistantHost liveness watch and bounded respawn", () => {
  function killCurrentGeneration(active: Map<WorkbenchJobHandle, number>): void {
    const job = [...active.keys()].at(-1)!;
    active.set(job, 0);
  }

  /** Long polls hang like the host's bounded ones. A dying host resets every
   * socket it owns at once, and the dead generation's token never reconnects. */
  function controlChannel(fetchImpl: ReturnType<typeof fixture>["fetchImpl"], claim?: Record<string, unknown>) {
    const base = fetchImpl.getMockImplementation()!;
    const pending = new Map<(error: Error) => void, string>();
    const dead = new Set<string>();
    let claimed = !claim, polls = 0, deadRetries = 0;
    fetchImpl.mockImplementation(async (...args: Parameters<typeof globalThis.fetch>) => {
      const [url, init] = args;
      const token = String((init?.headers as Record<string, string> | undefined)?.Authorization ?? "");
      if (String(url).endsWith("/api/assistant/main-control/settle")) return Response.json({ schemaVersion: 1, accepted: true });
      if (!String(url).endsWith("/api/assistant/main-control/next")) return base(...args);
      polls += 1;
      if (dead.has(token)) { deadRetries += 1; throw new TypeError("fetch failed"); }
      if (!claimed) { claimed = true; return Response.json({ schemaVersion: 1, request: claim }); }
      return await new Promise<Response>((_resolve, reject) => {
        const fail = (error: Error) => { pending.delete(fail); reject(error); };
        pending.set(fail, token);
        init?.signal?.addEventListener("abort", () => fail(new Error("aborted")), { once: true });
      });
    });
    return {
      polls: () => polls,
      deadRetries: () => deadRetries,
      reset: () => { for (const [fail, token] of [...pending]) { dead.add(token); fail(new TypeError("fetch failed")); } },
    };
  }

  /** Scriptable control channel for the consecutive-failure semantics: every
   * /next poll parks until failAll() rejects it like a socket reset or
   * answerOne() completes one worker's claim (claim -> empty result ->
   * settle), which is the successful RPC that clears the failure count.
   * Settle always acks accepted. */
  function scriptedControlChannel(fetchImpl: ReturnType<typeof fixture>["fetchImpl"]) {
    const base = fetchImpl.getMockImplementation()!;
    let parked: Array<{ fail: (error: Error) => void; answer: () => void }> = [];
    let polls = 0;
    fetchImpl.mockImplementation(async (...args: Parameters<typeof globalThis.fetch>) => {
      const [url, init] = args;
      if (String(url).endsWith("/api/assistant/main-control/settle")) return Response.json({ schemaVersion: 1, accepted: true });
      if (!String(url).endsWith("/api/assistant/main-control/next")) return base(...args);
      polls += 1;
      return await new Promise<Response>((resolve, reject) => {
        const entry = {
          fail: (error: Error) => { parked = parked.filter(other => other !== entry); reject(error); },
          answer: () => {
            parked = parked.filter(other => other !== entry);
            resolve(Response.json({ schemaVersion: 1, request: { deliveryId: "b".repeat(32), action: "project_lifecycle",
              projectId: "project", operation: "start", requestId: "probe" } }));
          },
        };
        parked.push(entry);
        init?.signal?.addEventListener("abort", () => entry.fail(new Error("aborted")), { once: true });
      });
    });
    return {
      polls: () => polls,
      failAll: () => { for (const entry of [...parked]) entry.fail(new TypeError("fetch failed")); },
      answerOne: () => { parked[0]?.answer(); },
    };
  }

  function channelFailureLines(warn: { mock: { calls: unknown[][] } }): string[] {
    return warn.mock.calls.map(([line]) => String(line)).filter(line => line.includes("phase=channel_failure"));
  }

  /** A venv pythonw redirector root outlives its killed host child for a few ms. */
  function hostExitsAfter(active: Map<WorkbenchJobHandle, number>, ms: number): void {
    const job = [...active.keys()].at(-1)!;
    setTimeout(() => active.set(job, 0), ms);
  }

  function deathForensics(root: string, inputs: WorkbenchJobSpawnInput[], spawn: number): Record<string, unknown> | null {
    const args = inputs[spawn]!.arguments;
    const path = join(root, "runtime", args[args.indexOf("--instance-id") + 1]!, "death-forensics.json");
    return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown> : null;
  }

  function deathLines(warn: { mock: { calls: unknown[][] } }): string[] {
    return warn.mock.calls.map(([line]) => String(line)).filter(line => line.includes("ASSISTANT_HOST_DEATH"));
  }

  it("records exit forensics and respawns an unexpectedly dead generation with 2s/4s/8s backoff", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, inputs, active, root } = fixture({ graceful: true });
    Object.assign(native, { exitCode: vi.fn(() => 3) });
    await host.start();
    const instanceId = inputs[0]!.arguments[inputs[0]!.arguments.indexOf("--instance-id") + 1]!;
    const stderrPath = join(root, "runtime", instanceId, "stderr.log");
    writeFileSync(stderrPath, `${"x".repeat(3000)}\nFINAL-stderr-LINE`);
    killCurrentGeneration(active);
    native.spawn.mockImplementation(() => { throw new Error("spawn refused"); });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    const deathLine = warnSpy.mock.calls.map(([line]) => String(line)).find(line => line.includes("ASSISTANT_HOST_DEATH"));
    expect(deathLine).toContain("phase=unexpected_exit");
    expect(deathLine).toContain("detectedBy=liveness_poll");
    expect(deathLine).toContain("exitCode=3");
    expect(deathLine).toContain(`instanceId=${instanceId}`);
    expect(deathLine).toContain("pid=100");
    expect(deathLine).toMatch(/uptimeMs=\d+/);
    const tail = JSON.parse(deathLine!.match(/stderrTail=(.*)$/)![1]!) as string;
    expect(tail.length).toBeLessThanOrEqual(2048);
    expect(tail.endsWith("FINAL-stderr-LINE")).toBe(true);
    // Packaged shells capture no main stdout: the same evidence is on disk.
    expect(deathForensics(root, inputs, 0)).toMatchObject({ schemaVersion: 1, phase: "unexpected_exit", detectedBy: "liveness_poll",
      exitCode: 3, instanceId, pid: 100, hostPid: 900, uptimeMs: expect.any(Number), revision: expect.any(Number), deathsInSession: 1, stderrTail: tail });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(native.spawn).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(8_000);
    expect(native.spawn).toHaveBeenCalledTimes(4);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_HOST_FAILED" });
    warnSpy.mockRestore();
    await host.stop();
    expect(native.spawn).toHaveBeenCalledTimes(4);
  });

  it("stops retrying and reports the host unavailable after five failed respawns in the window", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    killCurrentGeneration(active);
    native.spawn.mockImplementation(() => { throw new Error("spawn refused"); });
    await vi.advanceTimersByTimeAsync(64_000);
    expect(native.spawn).toHaveBeenCalledTimes(6);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_HOST_UNAVAILABLE" });
    await expect(host.start()).rejects.toThrow("ASSISTANT_HOST_UNAVAILABLE");
    await vi.advanceTimersByTimeAsync(600_000);
    expect(native.spawn).toHaveBeenCalledTimes(6);
    warnSpy.mockRestore();
  });

  it("does not respawn after a shell-initiated stop", async () => {
    vi.useFakeTimers();
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    killCurrentGeneration(active);
    await vi.advanceTimersByTimeAsync(2_000);
    await host.stop();
    expect(host.snapshot()).toEqual({ state: "stopped", errorCode: null });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(native.spawn).toHaveBeenCalledTimes(1);
  });

  it("joins an in-flight respawn instead of spawning a second generation", async () => {
    vi.useFakeTimers();
    const { host, native, fetchImpl, active } = fixture({ graceful: true });
    await host.start();
    killCurrentGeneration(active);
    let releaseHealth!: () => void;
    const gate = new Promise<void>(done => { releaseHealth = done; });
    fetchImpl.mockImplementationOnce(async () => { await gate; return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant" }); });
    await vi.advanceTimersByTimeAsync(4_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    const joined = host.start();
    expect(joined).toBe(host.start());
    releaseHealth();
    await expect(joined).resolves.toMatchObject({ state: "ready" });
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await host.stop();
  });

  it("resets the respawn budget once a generation is ready again", async () => {
    vi.useFakeTimers();
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    killCurrentGeneration(active);
    native.spawn.mockImplementationOnce(() => { throw new Error("spawn refused"); });
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(native.spawn).toHaveBeenCalledTimes(3);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    killCurrentGeneration(active);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(native.spawn).toHaveBeenCalledTimes(4);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    await host.stop();
  });

  it("treats an exit under a held lifecycle admission as controlled and resumes the watch after release", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const deathLines = () => warnSpy.mock.calls.map(([line]) => String(line)).filter(line => line.includes("ASSISTANT_HOST_DEATH"));
    const { host, native, active } = fixture({ graceful: true });
    await host.start();
    const admission = host.beginLifecycleAdmission();
    killCurrentGeneration(active);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(deathLines()).toHaveLength(0);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    // A cancelled shutdown reopens the same host: a death that outlived the
    // admission is then an ordinary unexpected exit with bounded respawn.
    admission.release();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(deathLines()).toHaveLength(1);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    warnSpy.mockRestore();
    await host.stop();
  });

  it("does not respawn when stop lands while a respawn start is in flight", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, active } = fixture({ graceful: true });
    await host.start();
    killCurrentGeneration(active);
    let releaseHealth!: () => void;
    const gate = new Promise<void>(done => { releaseHealth = done; });
    fetchImpl.mockImplementationOnce(async () => { await gate; return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant" }); });
    await vi.advanceTimersByTimeAsync(4_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    const stopped = host.stop();
    releaseHealth();
    await expect(stopped).resolves.toEqual({ state: "stopped", errorCode: null });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "stopped", errorCode: null });
    warnSpy.mockRestore();
  });

  it("classifies a control failure during a redirector-delayed exit as a host death and respawns exactly once", async () => {
    // Live-fire defect record (2026-11-03): the host socket resets while the
    // venv pythonw redirector root still holds the Job (activeCount=1); the
    // accounting reaches zero ~5ms later. rpc() cannot see the exit, the pump
    // reports a control failure, and an instant activeCount probe still reads
    // 1, so the generation used to end ASSISTANT_MAIN_CONTROL_FAILED with no
    // respawn. Red on the pre-fix code and on an instant-probe-only fix.
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, active, root, inputs } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = controlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.polls()).toBeGreaterThan(0);
    const instanceId = inputs[0]!.arguments[inputs[0]!.arguments.indexOf("--instance-id") + 1]!;
    hostExitsAfter(active, 5);
    channel.reset();
    await vi.advanceTimersByTimeAsync(100);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(deathLines(warnSpy)[0]).toContain("detectedBy=main_control");
    expect(deathForensics(root, inputs, 0)).toMatchObject({ schemaVersion: 1, phase: "unexpected_exit", detectedBy: "main_control",
      exitCode: null, instanceId, pid: 100, hostPid: 900, uptimeMs: expect.any(Number), revision: expect.any(Number), deathsInSession: 1,
      stderrTail: expect.any(String), recordedAt: expect.any(String) });
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.spawn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(channel.deadRetries()).toBe(0);
    warnSpy.mockRestore();
    await host.stop();
  });

  it("does not reconnect the control transport to a dead host under reference recovery", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const leases: Array<() => void> = [];
    const { host, native, fetchImpl, active, root, inputs } = fixture({ graceful: true,
      mainControl: async (_request, _signal, context) => { leases.push(context!.retainLease()); return {}; } });
    const channel = controlChannel(fetchImpl, { deliveryId: "b".repeat(32), action: "project_lifecycle", projectId: "project",
      operation: "start", requestId: "lease-holder" });
    await host.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(leases).toHaveLength(1);
    hostExitsAfter(active, 5);
    channel.reset();
    await vi.advanceTimersByTimeAsync(150);
    expect(channel.deadRetries()).toBe(0);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    expect(deathForensics(root, inputs, 0)).toMatchObject({ phase: "unexpected_exit", detectedBy: "main_control" });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(deathLines(warnSpy)).toHaveLength(1);
    warnSpy.mockRestore();
    await host.stop();
  });

  it("reconnects a live host after one control-channel failure without retiring it", async () => {
    // Live-fire record (2026-11-03): one healthy host was terminated on the
    // first control RPC hiccup, three times 5-13 minutes apart, dropping
    // reminders and native sessions each time. A single failure now
    // reconnects the transport instead of retiring the generation.
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, root, inputs } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = scriptedControlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.polls()).toBeGreaterThan(0);
    channel.failAll();
    const polls = channel.polls();
    await vi.advanceTimersByTimeAsync(150);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    expect(channelFailureLines(warnSpy)).toHaveLength(1);
    expect(channelFailureLines(warnSpy)[0]).toContain("failures=1 limit=3");
    expect(deathLines(warnSpy)).toHaveLength(0);
    expect(deathForensics(root, inputs, 0)).toBeNull();
    // The transport reconnected and claims again on the same live host.
    expect(channel.polls()).toBeGreaterThan(polls);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(native.terminate).not.toHaveBeenCalled();
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(deathForensics(root, inputs, 0)).toBeNull();
    warnSpy.mockRestore();
    await host.stop();
  });

  it("resets the consecutive failure count after one successful claim", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, root, inputs } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = scriptedControlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(0);
    // Two consecutive failures reconnect twice; the host stays ready.
    channel.failAll();
    await vi.advanceTimersByTimeAsync(150);
    channel.failAll();
    await vi.advanceTimersByTimeAsync(450);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    // One completed claim proves the channel works and clears the count, so
    // two more failures still reconnect instead of reaching the limit.
    channel.answerOne();
    await vi.advanceTimersByTimeAsync(0);
    channel.failAll();
    await vi.advanceTimersByTimeAsync(150);
    channel.failAll();
    await vi.advanceTimersByTimeAsync(450);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    expect(deathForensics(root, inputs, 0)).toBeNull();
    expect(channelFailureLines(warnSpy).at(-1)).toContain("failures=2 limit=3");
    warnSpy.mockRestore();
    await host.stop();
  });

  it("retires a live host only on the third consecutive failure, with control-failure forensics", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, root, inputs } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = scriptedControlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(0);
    const instanceId = inputs[0]!.arguments[inputs[0]!.arguments.indexOf("--instance-id") + 1]!;
    channel.failAll();
    await vi.advanceTimersByTimeAsync(150);
    channel.failAll();
    await vi.advanceTimersByTimeAsync(450);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    channel.failAll();
    await vi.advanceTimersByTimeAsync(1_500);
    // The limit-th consecutive failure keeps the old terminal view and
    // terminates, but now leaves the same on-disk forensics as an unexpected
    // exit instead of dying unattributed.
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_MAIN_CONTROL_FAILED" });
    expect(native.terminate).toHaveBeenCalledTimes(1);
    expect(deathForensics(root, inputs, 0)).toMatchObject({ schemaVersion: 1, phase: "control_failure_retire",
      detectedBy: "main_control", exitCode: null, instanceId, pid: 100, hostPid: 900, uptimeMs: expect.any(Number),
      revision: expect.any(Number), recordedAt: expect.any(String), deathsInSession: 0, stderrTail: "",
      consecutiveControlFailures: 3, lastControlError: "ASSISTANT_TRANSPORT_FAILED" });
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(deathLines(warnSpy)[0]).toContain("phase=control_failure_retire");
    expect(deathLines(warnSpy)[0]).toContain("consecutiveFailures=3");
    expect(deathLines(warnSpy)[0]).toContain(`instanceId=${instanceId}`);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_MAIN_CONTROL_FAILED" });
    warnSpy.mockRestore();
  });

  it("never counts reference-recovery reconnects toward the kill limit", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const leases: Array<() => void> = [];
    const { host, native, fetchImpl } = fixture({ graceful: true,
      mainControl: async (_request, _signal, context) => { leases.push(context!.retainLease()); return {}; } });
    const channel = controlChannel(fetchImpl, { deliveryId: "c".repeat(32), action: "project_lifecycle", projectId: "project",
      operation: "start", requestId: "lease-holder" });
    await host.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(leases).toHaveLength(1);
    channel.reset();
    // The broken channel reconnects through the lease-retaining recovery
    // branch forever; it neither terminates the host nor feeds the plain
    // control-failure limit.
    await vi.advanceTimersByTimeAsync(5_000);
    expect(channel.deadRetries()).toBeGreaterThan(1);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(channelFailureLines(warnSpy)).toHaveLength(0);
    expect(deathLines(warnSpy)).toHaveLength(0);
    warnSpy.mockRestore();
    await host.stop();
  });

  it("gives the control channel a 30s claim budget before counting a failure", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = scriptedControlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(0);
    // A claim that hangs past the old 15s budget is still pending at 15s...
    await vi.advanceTimersByTimeAsync(15_000);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(channelFailureLines(warnSpy)).toHaveLength(0);
    // ...and only trips its own 30s budget into one counted reconnect.
    await vi.advanceTimersByTimeAsync(15_000);
    expect(channelFailureLines(warnSpy)).toHaveLength(1);
    expect(channelFailureLines(warnSpy)[0]).toContain("lastError=\"ASSISTANT_REQUEST_TIMEOUT\"");
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    expect(native.terminate).not.toHaveBeenCalled();
    warnSpy.mockRestore();
    await host.stop();
  });

  it("lets the first of the liveness poll and the control-pump settle window classify one exit", async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { host, native, fetchImpl, active, root, inputs } = fixture({ graceful: true, mainControl: async () => ({}) });
    const channel = controlChannel(fetchImpl);
    await host.start();
    await vi.advanceTimersByTimeAsync(1_990);
    hostExitsAfter(active, 5);
    channel.reset();
    await vi.advanceTimersByTimeAsync(10);
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    await vi.advanceTimersByTimeAsync(100);
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(deathForensics(root, inputs, 0)).toMatchObject({ detectedBy: "liveness_poll" });
    await vi.advanceTimersByTimeAsync(1_900);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    warnSpy.mockRestore();
    await host.stop();
  });

  it.each([
    { path: "control-channel", lease: false },
    { path: "reference-recovery", lease: true },
  ])("leaves a $path pump-observed death under a held lifecycle admission to the liveness poll after release", async ({ lease }) => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const leases: Array<() => void> = [];
    const { host, native, fetchImpl, active, root, inputs } = fixture({ graceful: true,
      mainControl: async (_request, _signal, context) => { if (lease) leases.push(context!.retainLease()); return {}; } });
    const channel = controlChannel(fetchImpl, lease ? { deliveryId: "c".repeat(32), action: "project_lifecycle", projectId: "project",
      operation: "start", requestId: "lease-holder" } : undefined);
    await host.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(leases).toHaveLength(lease ? 1 : 0);
    const admission = host.beginLifecycleAdmission();
    hostExitsAfter(active, 5);
    channel.reset();
    await vi.advanceTimersByTimeAsync(10_000);
    // A controlled lifecycle operation owns the exit: no observer classifies,
    // aborts, retires or reconnects while the admission is held.
    expect(deathLines(warnSpy)).toHaveLength(0);
    expect(deathForensics(root, inputs, 0)).toBeNull();
    expect(native.terminate).not.toHaveBeenCalled();
    expect(channel.deadRetries()).toBe(0);
    expect(native.spawn).toHaveBeenCalledTimes(1);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    admission.release();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(deathLines(warnSpy)).toHaveLength(1);
    expect(deathForensics(root, inputs, 0)).toMatchObject({ phase: "unexpected_exit", detectedBy: "liveness_poll", deathsInSession: 1 });
    expect(host.snapshot()).toEqual({ state: "failed", errorCode: "ASSISTANT_EXITED" });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(host.snapshot()).toEqual({ state: "ready", errorCode: null });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(native.spawn).toHaveBeenCalledTimes(2);
    expect(deathLines(warnSpy)).toHaveLength(1);
    warnSpy.mockRestore();
    await host.stop();
  });
});
