import { describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { parseMainControlClaim, projectMainControlResult, runMainControlPump, type MainControlRequest } from "../src/assistant/mainControlTransport.js";

const wire = (overrides: object = {}) => ({ schemaVersion: 1, request: {
  deliveryId: "a".repeat(32), action: "project_lifecycle", projectId: "synthetic:uuid", operation: "start", requestId: "request-1", ...overrides,
} });
const request = wire().request as MainControlRequest;
const result = { schemaVersion: 1 as const, projectId: request.projectId, operation: "start", requestId: "request-1", state: "completed", code: "accepted", accepted: true };

describe("generation-scoped main control transport", () => {
  it("binds episodic sync and recovery to the approved project and original operation", () => {
    const row = { deliveryId: "a".repeat(32), action: "episodic_sync", projectId: "synthetic:uuid",
      previewId: "b".repeat(64), turnId: "turn-1", timeoutMs: 10000 };
    const parsed = parseMainControlClaim({ schemaVersion: 1, request: row })!;
    const migrationId = `episodic-${createHash("sha256").update(`${row.projectId}:${row.previewId}`).digest("hex").slice(0, 40)}`;
    const complete = { schemaVersion: 1, projectId: row.projectId, previewId: row.previewId, migrationId,
      state: "complete", code: "synchronized", appliedCount: 1, conflictCount: 0, readyForCutover: false };
    expect(projectMainControlResult(parsed, complete)).toEqual(complete);
    expect(projectMainControlResult(parsed, { ...complete, path: "C:/private" })).toMatchObject({ state: "unknown" });
    const original = "episodic-" + "f".repeat(40);
    const recovery = parseMainControlClaim({ schemaVersion: 1, request: { ...row, recoverSyncId: original } })!;
    expect(projectMainControlResult(recovery, undefined)).toMatchObject({ state: "unknown", migrationId: original });
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, recoverSyncId: "affairs-" + "f".repeat(40) } })).toThrow();
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, path: "C:/private" } })).toThrow();
    const resolveSyncId = "episodic-" + "e".repeat(40), reviewToken = "c".repeat(64);
    const resolution = parseMainControlClaim({ schemaVersion: 1, request: { ...row, resolveSyncId, reviewToken } })!;
    expect(resolution).toMatchObject({ resolveSyncId, reviewToken });
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, resolveSyncId } })).toThrow();
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, resolveSyncId, reviewToken, recoverSyncId: original } })).toThrow();
    const resolved = { ...complete, code: "resolved", appliedCount: 0 };
    expect(projectMainControlResult(resolution, resolved)).toEqual(resolved);
    expect(projectMainControlResult(parsed, resolved)).toMatchObject({ state: "unknown" });
    expect(projectMainControlResult(resolution, complete)).toMatchObject({ state: "unknown" });
  });
  it("keeps initial migration requests bound to their project, category and stable operation ID", () => {
    const projectId = "synthetic:uuid", category = "personal";
    const operationId = `initial-${createHash("sha256").update(`${projectId}:${category}`).digest("hex").slice(0, 40)}`;
    const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue", projectId,
      previewId: "b".repeat(64), turnId: "turn-1", category, operationId, timeoutMs: 10000 };
    const parsed = parseMainControlClaim({ schemaVersion: 1, request: row })!;
    expect(parsed).toEqual(row);
    for (const change of [{ path: "C:/private" }, { category: "history" }, { operationId: "initial-" + "0".repeat(40) }, { timeoutMs: 120001 }])
      expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, ...change } })).toThrow();
    const result = { schemaVersion: 1, projectId, previewId: row.previewId, category, operationId,
      state: "queued", code: "queued", readyForCutover: false };
    expect(projectMainControlResult(parsed, result)).toEqual(result);
    for (const change of [{ readyForCutover: true }, { operationId: "initial-" + "0".repeat(40) }, { path: "C:/private" }, { state: "completed" }])
      expect(projectMainControlResult(parsed, { ...result, ...change })).toMatchObject({ state: "unknown", code: "unknown" });
    const receipt = parseMainControlClaim({ schemaVersion: 1, request: { deliveryId: row.deliveryId,
      action: "initial_migration_receipt", projectId, category, operationId } })!;
    const completed = { schemaVersion: 1, projectId, category, operationId, state: "completed", code: "completed", readyForCutover: false };
    expect(projectMainControlResult(receipt, completed)).toEqual(completed);
    expect(projectMainControlResult(receipt, { ...completed, sourcePath: "C:/private" })).toMatchObject({ state: "unknown" });
  });
  it("binds affairs sync to the exact request and projects only closed results", () => {
    const row = { deliveryId: "a".repeat(32), action: "affairs_sync", projectId: "synthetic:uuid",
      previewId: "b".repeat(64), turnId: "turn-1", timeoutMs: 10000 };
    const parsed = parseMainControlClaim({ schemaVersion: 1, request: row })!;
    expect(parsed).toEqual(row);
    for (const changed of [{ path: "C:/private" }, { timeoutMs: 120001 }, { previewId: "a" }, { turnId: "file:///private" }])
      expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, ...changed } })).toThrow();
    const migrationId = "affairs-" + createHash("sha256").update(`${row.projectId}:${row.previewId}`).digest("hex").slice(0, 40);
    const base = { schemaVersion: 1, projectId: row.projectId, previewId: row.previewId, migrationId, readyForCutover: false };
    const complete = { ...base, state: "complete", code: "synchronized", appliedCount: 2, conflictCount: 0 };
    const partial = { ...base, state: "partial", code: "unresolved", appliedCount: 1, conflictCount: 2 };
    const rejected = { ...base, state: "rejected", code: "cancelled" };
    const unknown = { ...base, state: "unknown", code: "unknown" };
    for (const value of [complete, partial, rejected, unknown]) expect(projectMainControlResult(parsed, value)).toEqual(value);
    for (const code of ["unresolved", "pending", "baseline_unavailable"])
      expect(projectMainControlResult(parsed, { ...rejected, code })).toEqual({ ...rejected, code });
    for (const value of [{ ...complete, migrationId: "affairs-" + "0".repeat(40) }, { ...complete, projectId: "other" },
      { ...complete, previewId: "c".repeat(64) }, { ...complete, readyForCutover: true }, { ...complete, conflictCount: 1 },
      { ...partial, conflictCount: 0 }, { ...partial, appliedCount: true }, { ...partial, conflictCount: -1 },
      { ...complete, appliedCount: 4097 }, { ...partial, conflictCount: 4097 },
      { ...rejected, appliedCount: 0 }, { ...complete, detail: "secret" }, { ...complete, code: "unresolved" }])
      expect(projectMainControlResult(parsed, value)).toEqual(unknown);
    const accessor = { ...complete }; Object.defineProperty(accessor, "appliedCount", { enumerable: true, get: () => 2 });
    expect(projectMainControlResult(parsed, accessor)).toEqual(unknown);
    const recovery = parseMainControlClaim({ schemaVersion: 1, request: { ...row, recoverSyncId: "affairs-" + "f".repeat(40) } })!;
    expect(projectMainControlResult(recovery, undefined)).toEqual({ ...unknown, migrationId: "affairs-" + "f".repeat(40) });
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, recoverSyncId: "C:/private" } })).toThrow();
  });
  it("applies the deadline to affairs sync and never replays an unknown result", async () => {
    const controller = new AbortController();
    const row = { deliveryId: "a".repeat(32), action: "affairs_sync", projectId: "synthetic:uuid",
      previewId: "b".repeat(64), turnId: "turn-1", timeoutMs: 10 };
    let claimed = false;
    const invoke = vi.fn(async (path: string) => {
      if (path.endsWith("/settle")) { controller.abort(); return { schemaVersion: 1, accepted: true }; }
      if (!claimed) { claimed = true; return { schemaVersion: 1, request: row }; }
      return await new Promise((_resolve, reject) => controller.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    });
    const onRequest = vi.fn(async (_request: MainControlRequest, signal?: AbortSignal) => {
      await new Promise<void>(resolve => signal!.addEventListener("abort", () => resolve(), { once: true }));
      throw new Error("unknown");
    });
    await runMainControlPump({ signal: controller.signal, invoke, onRequest, isCurrent: () => !controller.signal.aborted, onFailure: vi.fn() });
    expect(onRequest).toHaveBeenCalledTimes(1);
    const settled = invoke.mock.calls.find(([path]) => path.endsWith("/settle"));
    expect(settled).toBeDefined();
  });
  it("keeps history imports bound to the native turn and a closed result", () => {
    const history = { deliveryId: "a".repeat(32), action: "history_import", projectId: "synthetic:uuid",
      previewId: "b".repeat(64), turnId: "turn-1", timeoutMs: 10000 };
    const parsed = parseMainControlClaim({ schemaVersion: 1, request: history });
    expect(parsed).toEqual(history);
    expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...history, path: "C:/private" } })).toThrow();
    const published = { schemaVersion: 1, projectId: history.projectId, previewId: history.previewId,
      state: "published", code: "imported", historyCount: 1, readyForCutover: false };
    expect(projectMainControlResult(parsed!, published)).toEqual(published);
    expect(projectMainControlResult(parsed!, { ...published, readyForCutover: true })).toMatchObject({ state: "unknown" });
  });
  it("admits only closed opaque lifecycle/status envelopes", () => {
    expect(parseMainControlClaim(wire())).toEqual(request);
    expect(parseMainControlClaim({ schemaVersion: 1, request: null })).toBeNull();
    for (const override of [{ force: true }, { operation: "force-stop" }, { projectId: "file:///private" }, { requestId: "../request" }, { deliveryId: "old" }]) {
      expect(() => parseMainControlClaim(wire(override))).toThrow();
    }
    expect(() => parseMainControlClaim({ ...wire(), url: "http://private" })).toThrow();
    expect(() => parseMainControlClaim(wire({ action: "project_status", operation: "status" }))).toThrow();
  });

  it("projects only matching public facts and sanitizes arbitrary callback errors/details", () => {
    expect(projectMainControlResult(request, result)).toEqual(result);
    for (const invalid of [{ ...result, requestId: "other" }, { ...result, message: "SECRET C:/private" }, { ...result, code: "SECRET" }, { ...result, state: "completed", accepted: false },
      { ...result, state: "completed", code: "project_unavailable" }, { ...result, state: "queued", code: "accepted" }]) {
      const projected = projectMainControlResult(request, invalid);
      expect(projected).toMatchObject({ state: "unknown", code: "control_unavailable" });
      expect(JSON.stringify(projected)).not.toContain("SECRET");
    }
  });

  it("does not replay a request when its result acknowledgement is lost", async () => {
    const signal = new AbortController();
    let claimed = false;
    const invoke = vi.fn(async (path: string) => {
      if (path.endsWith("/next")) {
        if (!claimed) { claimed = true; return wire(); }
        return await new Promise((_resolve, reject) => signal.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
      }
      throw new Error("lost acknowledgement SECRET");
    });
    const onRequest = vi.fn(async () => result);
    const failure = vi.fn(() => signal.abort());
    await runMainControlPump({ signal: signal.signal, invoke, onRequest, isCurrent: () => !signal.signal.aborted, onFailure: failure });
    expect(onRequest).toHaveBeenCalledTimes(1);
    expect(failure).toHaveBeenCalledTimes(1);
  });

  it("lets an admitted main command settle after host retirement without replying to a replacement", async () => {
    const signal = new AbortController();
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const started = new Promise<void>(resolve => { entered = resolve; });
    let claimed = false;
    const invoke = vi.fn(async (path: string) => {
      if (!claimed) { claimed = true; return wire(); }
      if (signal.signal.aborted) throw new Error("aborted");
      return await new Promise((_resolve, reject) => signal.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    });
    const onRequest = vi.fn(async () => { entered(); await gate; return result; });
    const pending = runMainControlPump({ signal: signal.signal, invoke, onRequest, isCurrent: () => !signal.signal.aborted, onFailure: vi.fn() });
    await started; signal.abort(); release(); await pending;
    expect(onRequest).toHaveBeenCalledTimes(1);
    expect(invoke.mock.calls.every(([path]) => path.endsWith("/next"))).toBe(true);
  });
});
