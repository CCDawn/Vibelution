import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherTaskCleanupScope, LauncherTaskCleanupTarget } from "../../../api/launcherAssistantTaskCleanup";

let api: typeof import("../../../api/launcherAssistantTaskCleanup");
let invoke: ReturnType<typeof vi.fn>;
const key = (target: LauncherTaskCleanupTarget) => JSON.stringify([target.kind, target.projectId,
  target.kind === "dispatch" ? target.dispatchId : target.originAction, target.kind === "team_run" ? target.requestId : null]);
function scope(count = 1): LauncherTaskCleanupScope {
  return { agentId: "assistant-1", directSessionId: "session-1", targets: Array.from({ length: count }, (_, index) => ({
    kind: "dispatch", projectId: "project-1", dispatchId: `dispatch-${index}`,
  })) };
}
function preview(targets: LauncherTaskCleanupTarget[], fingerprint = "native-preview") {
  return { schemaVersion: 1, fingerprint, estimatedBytes: targets.length * 10, items: targets.map(target => ({
    key: key(target), title: "任务", status: "ready", estimatedBytes: 10,
    resources: [{ kind: "task_files", count: 1, bytes: 10 }], retained: [],
  })) };
}
function deleted(targets: LauncherTaskCleanupTarget[]) {
  return { schemaVersion: 1, releasedBytes: targets.length * 8, items: targets.map(target => ({
    key: key(target), status: "deleted", releasedBytes: 8, retained: [], failures: [],
  })) };
}

beforeEach(async () => {
  vi.resetModules(); vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-02T10:00:00Z"));
  invoke = vi.fn(async (request: { operation: string; targets: LauncherTaskCleanupTarget[] }) => request.operation === "previewTaskCleanup"
    ? preview(request.targets, `native-${request.targets[0].kind === "dispatch" ? request.targets[0].dispatchId : request.targets[0].requestId}`)
    : deleted(request.targets));
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  api = await import("../../../api/launcherAssistantTaskCleanup");
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("Launcher task cleanup batched transport", () => {
  it("keeps a confirmed-absence evidence note and falls back for unknown codes", async () => {
    expect(api.launcherTaskCleanupSourceNote("task_absent", "zh")).toBe("源项目确认无此任务，已移除本地关联。");
    expect(api.launcherTaskCleanupSourceNote("credential_unavailable", "zh"))
      .toContain("无法再被观察或恢复");
    expect(api.launcherTaskCleanupSourceNote("project_unregistered", "en"))
      .toBe("The source project is no longer authorized; the local association was removed.");
    expect(api.launcherTaskCleanupSourceNote("future_code", "zh")).toContain("已移除本地关联");
    expect(api.launcherTaskCleanupSourceNote(undefined, "zh")).toBeNull();
    const input = scope(1), plan = await api.previewLauncherTaskCleanup(input);
    invoke.mockImplementation(async (request: { operation: string; targets: LauncherTaskCleanupTarget[] }) =>
      request.operation === "previewTaskCleanup" ? preview(request.targets, "native-preview")
        : { ...deleted(request.targets), items: deleted(request.targets).items.map(item => ({ ...item, sourceConfirmed: "task_absent" })) });
    const result = await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(result.items[0].sourceConfirmed).toBe("task_absent");
  });
  it("keeps a native-blocked evidence note through validation and falls back for unknown codes", async () => {
    expect(api.launcherTaskCleanupNativeNote("blocked", "zh")).toContain("已移除任务关联");
    expect(api.launcherTaskCleanupNativeNote("blocked", "en")).toContain("source task");
    expect(api.launcherTaskCleanupNativeNote("future_code", "zh")).toContain("已移除任务关联");
    expect(api.launcherTaskCleanupNativeNote(undefined, "zh")).toBeNull();
    const input = scope(1), plan = await api.previewLauncherTaskCleanup(input);
    invoke.mockImplementation(async (request: { operation: string; targets: LauncherTaskCleanupTarget[] }) =>
      request.operation === "previewTaskCleanup"
        ? { ...preview(request.targets), items: preview(request.targets).items.map(item => ({ ...item, nativeCleanup: "blocked" })) }
        : { ...deleted(request.targets), items: deleted(request.targets).items.map(item => ({ ...item, nativeCleanup: "blocked" })) });
    const result = await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(result.items[0].status).toBe("deleted");
    expect(result.items[0].nativeCleanup).toBe("blocked");
  });
  it("deducts storage growth in one batch from release in another batch", async () => {
    const input = scope(33), plan = await api.previewLauncherTaskCleanup(input);
    let batch = 0;
    invoke.mockImplementation(async request => ({ ...deleted(request.targets),
      releasedBytes: batch === 0 ? 0 : 20, storageDeltaBytes: batch++ === 0 ? -12 : 20 }));
    const result = await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(result.releasedBytes).toBe(8);
    expect(result.storageDeltaBytes).toBe(8);
  });
  it("previews and executes every target in ordered batches of 32 with each native fingerprint", async () => {
    const input = scope(65), plan = await api.previewLauncherTaskCleanup(input);
    expect(plan.fingerprint).toMatch(/^[a-f0-9]{64}$/);
    expect(plan.estimatedBytes).toBe(650);
    expect(plan.items.map(item => item.key)).toEqual(input.targets.map(key));
    expect(invoke.mock.calls.map(([request]) => request.targets.length)).toEqual([32, 32, 1]);
    const result = await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(result.releasedBytes).toBe(520);
    expect(result.items.map(item => item.key)).toEqual(input.targets.map(key));
    expect(invoke.mock.calls.slice(3).map(([request]) => (request as unknown as { fingerprint: string }).fingerprint))
      .toEqual(["native-dispatch-0", "native-dispatch-32", "native-dispatch-64"]);
    await expect(api.executeLauncherTaskCleanup(input, plan.fingerprint)).rejects.toThrow("已失效");
    expect(invoke).toHaveBeenCalledTimes(6);
  });

  it("preserves all team aliases even across a transport batch boundary", async () => {
    const input = scope(31);
    for (let index = 0; index < 3; index += 1) input.targets.push({ kind: "team_run", projectId: "project-1", requestId: `request-${index}`,
      originAction: index === 0 ? "team_run" : "flow_start", teamId: "team-1", flowId: "flow-1", runId: "run-1" });
    const plan = await api.previewLauncherTaskCleanup(input);
    expect(plan.items).toHaveLength(34);
    expect(invoke.mock.calls.flatMap(([request]) => request.targets).filter(target => target.kind === "team_run")).toHaveLength(3);
    await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(invoke.mock.calls.filter(([request]) => request.operation === "executeTaskCleanup").flatMap(([request]) => request.targets)).toEqual(input.targets);
  });

  it("reports a failed batch as unconfirmed without inventing released bytes and continues the remaining approved batches", async () => {
    const input = scope(65), plan = await api.previewLauncherTaskCleanup(input);
    invoke.mockImplementation(async request => {
      if (request.targets[0].dispatchId === "dispatch-32") throw new Error("offline");
      return deleted(request.targets);
    });
    const result = await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(result.releasedBytes).toBe(33 * 8);
    expect(result.items.filter(item => item.status === "deleted")).toHaveLength(33);
    expect(result.items.filter(item => item.status === "blocked")).toHaveLength(32);
    expect(result.items[32]).toMatchObject({ releasedBytes: 0, failures: [{ code: "cleanup_batch_unconfirmed", message: expect.stringContaining("未获确认") }] });
    expect(invoke.mock.calls.slice(3)).toHaveLength(3);
  });

  it("refuses a preview with missing or mismatched aliases", async () => {
    invoke.mockImplementation(async request => preview(request.targets.slice(0, -1)));
    await expect(api.previewLauncherTaskCleanup(scope(2))).rejects.toThrow("不可用");
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("binds the preview to the exact assistant, session, references and ordering", async () => {
    const input = scope(2), plan = await api.previewLauncherTaskCleanup(input);
    for (const changed of [{ ...input, agentId: "assistant-2" }, { ...input, directSessionId: "session-2" },
      { ...input, targets: [...input.targets].reverse() },
      { ...input, targets: input.targets.map(target => ({ ...target, localOnly: true })) }, scope(1)]) {
      await expect(api.executeLauncherTaskCleanup(changed, plan.fingerprint)).rejects.toThrow("已失效");
    }
    expect(invoke).toHaveBeenCalledTimes(1);
    await api.executeLauncherTaskCleanup(input, plan.fingerprint);
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it("expires composite plans after five minutes and bounds them to sixteen entries", async () => {
    const first = await api.previewLauncherTaskCleanup(scope());
    for (let index = 0; index < 16; index += 1) await api.previewLauncherTaskCleanup(scope());
    await expect(api.executeLauncherTaskCleanup(scope(), first.fingerprint)).rejects.toThrow("已失效");
    const latest = await api.previewLauncherTaskCleanup(scope());
    vi.setSystemTime(Date.now() + 5 * 60_000);
    await expect(api.executeLauncherTaskCleanup(scope(), latest.fingerprint)).rejects.toThrow("已失效");
    expect(invoke.mock.calls.every(([request]) => request.operation === "previewTaskCleanup")).toBe(true);
  });

  it("blocks scopes above 512 without sending or silently truncating targets", async () => {
    await expect(api.previewLauncherTaskCleanup(scope(513))).rejects.toThrow("超过 512");
    expect(invoke).not.toHaveBeenCalled();
    const plan = await api.previewLauncherTaskCleanup(scope(512));
    expect(plan.items).toHaveLength(512);
    expect(invoke).toHaveBeenCalledTimes(16);
  });

  it("stops later preview batches after abort and never returns an approvable old plan", async () => {
    const controller = new AbortController();
    invoke.mockImplementation(async request => { controller.abort(); return preview(request.targets); });
    await expect(api.previewLauncherTaskCleanup(scope(65), { signal: controller.signal })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("stops later execute batches after abort while preserving the host's already sent request", async () => {
    const input = scope(65), plan = await api.previewLauncherTaskCleanup(input), controller = new AbortController();
    invoke.mockImplementation(async request => { controller.abort(); return deleted(request.targets); });
    await expect(api.executeLauncherTaskCleanup(input, plan.fingerprint, { signal: controller.signal })).rejects.toThrow();
    expect(invoke.mock.calls.filter(([request]) => request.operation === "executeTaskCleanup")).toHaveLength(1);
  });

  it("cleans all targets in one action and executes each small batch immediately", async () => {
    const result = await api.cleanupLauncherTasks(scope(37));
    expect(result.items).toHaveLength(37);
    expect(result.items.every(item => item.status === "deleted")).toBe(true);
    expect(invoke.mock.calls.map(([request]) => request.operation)).toEqual(
      Array.from({ length: 19 }, () => ["previewTaskCleanup", "executeTaskCleanup"]).flat());
    expect(invoke.mock.calls.every(([request]) => request.targets.length <= 2)).toBe(true);
  });

  it("keeps a blocked source's actual reason and continues with other targets", async () => {
    invoke.mockImplementation(async request => {
      if (request.operation === "executeTaskCleanup") return deleted(request.targets);
      const value = preview(request.targets);
      value.items[0] = { ...value.items[0], status: "blocked", reason: "任务仍在运行" } as typeof value.items[0];
      return value;
    });
    const result = await api.cleanupLauncherTasks(scope(6));
    expect(result.items.filter(item => item.status === "deleted")).toHaveLength(3);
    expect(result.items[0].failures[0].message).toBe("任务仍在运行");
    expect(result.items[4].status).toBe("blocked");
  });

  it("stops subsequent direct batches when the page or identity aborts", async () => {
    const controller = new AbortController();
    invoke.mockImplementation(async request => {
      if (request.operation === "executeTaskCleanup") { controller.abort(); return deleted(request.targets); }
      return preview(request.targets);
    });
    await expect(api.cleanupLauncherTasks(scope(9), { signal: controller.signal })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(2);
  });
});
