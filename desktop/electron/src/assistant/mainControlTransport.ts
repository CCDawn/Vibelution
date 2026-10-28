import { createHash } from "node:crypto";
import { isAppearanceAction, parseAppearanceClaim, appearanceControlResult, type AppearanceMainControlRequest } from "./appearanceControlProtocol.js";
/** Closed, generation-scoped transport over the existing private host connection.
 * It has no credentials, paths, scheduler, transcript or business-state writer.
 */
export type ProjectMainControlRequest = {
  deliveryId: string;
  projectId: string;
} & ({ action: "project_status"; operation: "status"; requestId?: never }
  | { action: "project_lifecycle" | "project_lifecycle_receipt"; operation: "start" | "stop" | "restart"; requestId: string });
export type HistoryMainControlRequest = { deliveryId: string; action: "history_import"; projectId: string; previewId: string; turnId: string; timeoutMs: number };
export type AffairsSyncMainControlRequest = Omit<HistoryMainControlRequest, "action"> & { action: "affairs_sync"; recoverSyncId?: string };
export type InitialMigrationMainControlRequest = Omit<HistoryMainControlRequest, "action"> & {
  action: "initial_migration_queue"; category: "personal" | "knowledge"; operationId: string;
};
export type InitialMigrationReceiptRequest = { deliveryId: string; action: "initial_migration_receipt"; projectId: string;
  category: "personal" | "knowledge"; operationId: string };
export type MainControlRequest = ProjectMainControlRequest | AppearanceMainControlRequest | HistoryMainControlRequest | AffairsSyncMainControlRequest | InitialMigrationMainControlRequest | InitialMigrationReceiptRequest;
type PublicResult = Record<string, unknown>;
const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
const forbiddenScheme = /^(?:https?|file|data|javascript|mailto|ftp|wss?):/i;
const opaque = (value: unknown, max: number): value is string => typeof value === "string"
  && value.length <= max && ID.test(value) && !forbiddenScheme.test(value);
function closed(value: unknown, required: string[], optional: string[] = []): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(value).length === Object.keys(descriptors).length
    && required.every(key => Object.hasOwn(descriptors, key))
    && Object.entries(descriptors).every(([key, descriptor]) => [...required, ...optional].includes(key)
      && Object.hasOwn(descriptor, "value") && descriptor.enumerable);
}
export function parseMainControlClaim(value: unknown): MainControlRequest | null {
  const invalid = () => { throw new Error("ASSISTANT_MAIN_CONTROL_INVALID"); };
  if (!closed(value, ["schemaVersion", "request"]) || value.schemaVersion !== 1) return invalid();
  if (value.request === null) return null;
  const row = value.request;
  if (row && typeof row === "object" && isAppearanceAction(Object.getOwnPropertyDescriptor(row,"action")?.value)) return parseAppearanceClaim(row);
  if (row && typeof row === "object" && Object.getOwnPropertyDescriptor(row, "action")?.value === "initial_migration_receipt") {
    if (!closed(row, ["deliveryId", "action", "projectId", "category", "operationId"])
      || typeof row.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(row.deliveryId) || !opaque(row.projectId, 160)
      || (row.category !== "personal" && row.category !== "knowledge")
      || row.operationId !== `initial-${createHash("sha256").update(`${row.projectId}:${row.category}`).digest("hex").slice(0, 40)}`) return invalid();
    return { deliveryId: row.deliveryId, action: "initial_migration_receipt", projectId: row.projectId,
      category: row.category, operationId: row.operationId as string };
  }
  if (row && typeof row === "object" && Object.getOwnPropertyDescriptor(row, "action")?.value === "initial_migration_queue") {
    if (!closed(row, ["deliveryId", "action", "projectId", "previewId", "turnId", "category", "operationId", "timeoutMs"])
      || typeof row.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(row.deliveryId) || !opaque(row.projectId, 160)
      || typeof row.previewId !== "string" || !/^[a-f0-9]{64}$/.test(row.previewId) || !opaque(row.turnId, 160)
      || (row.category !== "personal" && row.category !== "knowledge")
      || row.operationId !== `initial-${createHash("sha256").update(`${row.projectId}:${row.category}`).digest("hex").slice(0, 40)}`
      || typeof row.timeoutMs !== "number" || !Number.isSafeInteger(row.timeoutMs) || row.timeoutMs < 1 || row.timeoutMs > 120000) return invalid();
    return { deliveryId: row.deliveryId, action: "initial_migration_queue", projectId: row.projectId,
      previewId: row.previewId, turnId: row.turnId, category: row.category, operationId: row.operationId as string, timeoutMs: row.timeoutMs };
  }
  if (row && typeof row === "object" && ["history_import", "affairs_sync"].includes(Object.getOwnPropertyDescriptor(row, "action")?.value)) {
    if (!closed(row, ["deliveryId", "action", "projectId", "previewId", "turnId", "timeoutMs"],
      Object.getOwnPropertyDescriptor(row, "action")?.value === "affairs_sync" ? ["recoverSyncId"] : [])
      || typeof row.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(row.deliveryId) || !opaque(row.projectId, 160)
      || typeof row.previewId !== "string" || !/^[a-f0-9]{64}$/.test(row.previewId) || !opaque(row.turnId, 160)
      || typeof row.timeoutMs !== "number" || !Number.isSafeInteger(row.timeoutMs) || row.timeoutMs < 1 || row.timeoutMs > 120000
      || (Object.hasOwn(row, "recoverSyncId") && (typeof row.recoverSyncId !== "string" || !/^affairs-[a-f0-9]{40}$/.test(row.recoverSyncId)))) return invalid();
    return { deliveryId: row.deliveryId, action: row.action as "history_import" | "affairs_sync", projectId: row.projectId,
      previewId: row.previewId, turnId: row.turnId, timeoutMs: row.timeoutMs,
      ...(typeof row.recoverSyncId === "string" ? { recoverSyncId: row.recoverSyncId } : {}) };
  }
  if (!closed(row, ["deliveryId", "action", "projectId", "operation"], ["requestId"])
    || typeof row.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(row.deliveryId) || !opaque(row.projectId, 160)) return invalid();
  const base = { deliveryId: row.deliveryId, projectId: row.projectId };
  if (row.action === "project_status" && row.operation === "status" && !Object.hasOwn(row, "requestId")) return { ...base, action: row.action, operation: row.operation };
  if (typeof row.action !== "string" || !["project_lifecycle", "project_lifecycle_receipt"].includes(row.action)
    || typeof row.operation !== "string" || !["start", "stop", "restart"].includes(row.operation) || !opaque(row.requestId, 128)) return invalid();
  return { ...base, action: row.action as "project_lifecycle" | "project_lifecycle_receipt",
    operation: row.operation as "start" | "stop" | "restart", requestId: row.requestId };
}
const CODES = new Set([
  "invalid_request", "project_unavailable", "registration_changed", "storage_owner_changed", "prerequisite_required", "context_limit", "status_unavailable", "lifecycle_failed", "cancelled",
  "status", "accepted", "rejected", "active_work_blocked", "restart_queued", "lifecycle_intent_superseded", "backend_retire_incomplete", "close_backoff_coalesced",
  "request_invalid", "request_conflict", "request_store_invalid", "request_store_read_failed", "request_store_write_failed", "request_limit_exceeded", "reservation_invalid", "binding_conflict",
  "request_failed", "request_unbound", "receipt_unavailable", "request_not_found", "control_unavailable", "control_busy",
]);
const STATES = new Set(["completed", "queued", "rejected", "unknown", "not_found"]);
export function affairsSyncMigrationId(projectId: string, previewId: string): string {
  return `affairs-${createHash("sha256").update(`${projectId}:${previewId}`).digest("hex").slice(0, 40)}`;
}
export function unknownAffairsSyncResult(input: { projectId: string; previewId: string; recoverSyncId?: string }): PublicResult {
  return { schemaVersion: 1, projectId: input.projectId, previewId: input.previewId,
    migrationId: input.recoverSyncId ?? affairsSyncMigrationId(input.projectId, input.previewId), state: "unknown", code: "unknown", readyForCutover: false };
}
export function parseAffairsSyncResult(input: { projectId: string; previewId: string; recoverSyncId?: string }, value: unknown): PublicResult | null {
  if (!closed(value, ["schemaVersion", "projectId", "previewId", "migrationId", "state", "code", "readyForCutover"], ["appliedCount", "conflictCount"])
    || value.schemaVersion !== 1 || value.projectId !== input.projectId || value.previewId !== input.previewId
    || value.migrationId !== (input.recoverSyncId ?? affairsSyncMigrationId(input.projectId, input.previewId)) || value.readyForCutover !== false
    || typeof value.state !== "string" || typeof value.code !== "string"
    || (input.recoverSyncId !== undefined && !["confirmed", "unknown"].includes(value.state))
    || !["complete:synchronized", "partial:unresolved", "confirmed:matched", "rejected:preview_invalid", "rejected:project_unavailable", "rejected:cancelled", "rejected:busy", "rejected:unresolved", "rejected:pending", "rejected:baseline_unavailable", "unknown:unknown"].includes(`${value.state}:${value.code}`)) return null;
  if (value.state === "complete" || value.state === "partial") {
    if (typeof value.appliedCount !== "number" || !Number.isSafeInteger(value.appliedCount) || value.appliedCount < 0 || value.appliedCount > 4096
      || typeof value.conflictCount !== "number" || !Number.isSafeInteger(value.conflictCount) || value.conflictCount < 0 || value.conflictCount > 4096
      || (value.state === "complete" ? value.conflictCount !== 0 : value.conflictCount === 0)) return null;
  } else if (value.state === "confirmed") {
    if (input.recoverSyncId === undefined || Object.hasOwn(value, "appliedCount")
      || typeof value.conflictCount !== "number" || !Number.isSafeInteger(value.conflictCount)
      || value.conflictCount < 0 || value.conflictCount > 4096) return null;
  } else if (Object.hasOwn(value, "appliedCount") || Object.hasOwn(value, "conflictCount")) return null;
  return { ...value };
}
/** Fail closed rather than relay arbitrary errors, native rows, paths or messages. */
export function projectMainControlResult(request: MainControlRequest, value: unknown): PublicResult {
  if (request.action === "launcher_theme_get" || request.action === "launcher_theme_set" || request.action === "operator_image_upload") return appearanceControlResult(request,value);
  if (request.action === "initial_migration_receipt") {
    const base = { schemaVersion: 1, projectId: request.projectId, category: request.category,
      operationId: request.operationId, readyForCutover: false };
    const unknown = { ...base, state: "unknown", code: "unknown" };
    if (!closed(value, ["schemaVersion", "projectId", "category", "operationId", "state", "code", "readyForCutover"])
      || value.schemaVersion !== 1 || value.projectId !== request.projectId || value.category !== request.category
      || value.operationId !== request.operationId || value.readyForCutover !== false || typeof value.state !== "string"
      || value.code !== value.state || !["queued", "completed", "partial", "unknown", "not_found"].includes(value.state)) return unknown;
    return { ...value };
  }
  if (request.action === "initial_migration_queue") {
    const base = { schemaVersion: 1, projectId: request.projectId, previewId: request.previewId,
      category: request.category, operationId: request.operationId, readyForCutover: false };
    const unknown = { ...base, state: "unknown", code: "unknown" };
    if (!closed(value, ["schemaVersion", "projectId", "previewId", "category", "operationId", "state", "code", "readyForCutover"])
      || value.schemaVersion !== 1 || value.projectId !== request.projectId || value.previewId !== request.previewId
      || value.category !== request.category || value.operationId !== request.operationId || value.readyForCutover !== false
      || typeof value.state !== "string" || typeof value.code !== "string"
      || !["queued:queued", "unknown:unknown", "rejected:cancelled", "rejected:unavailable", "rejected:busy"].includes(`${value.state}:${value.code}`)) return unknown;
    return { ...value };
  }
  if (request.action === "affairs_sync") return parseAffairsSyncResult(request, value) ?? unknownAffairsSyncResult(request);
  if (request.action === "history_import") {
    const unavailable = () => ({ schemaVersion: 1, projectId: request.projectId, previewId: request.previewId,
      state: "unknown", code: "unknown", readyForCutover: false });
    if (!closed(value, ["schemaVersion", "projectId", "previewId", "state", "code", "readyForCutover"], ["historyCount"])
      || value.schemaVersion !== 1 || value.projectId !== request.projectId || value.previewId !== request.previewId
      || value.readyForCutover !== false || typeof value.state !== "string" || typeof value.code !== "string"
      || !["published:imported", "rejected:preview_invalid", "rejected:project_unavailable", "rejected:cancelled", "rejected:busy", "unknown:unknown"].includes(`${value.state}:${value.code}`)
      || (value.state === "published" ? typeof value.historyCount !== "number" || !Number.isSafeInteger(value.historyCount) || value.historyCount < 0 || value.historyCount > 10000 : Object.hasOwn(value, "historyCount"))) return unavailable();
    return { ...value };
  }
  const status = request.action === "project_status";
  const base = { schemaVersion: 1, projectId: request.projectId, operation: request.operation,
    ...(!status ? { requestId: request.requestId } : {}) };
  const unavailable = () => ({ ...base, ...(status ? { accepted: false, code: "status_unavailable" }
    : { state: "unknown", code: "control_unavailable" }) });
  if (!closed(value, status ? ["schemaVersion", "projectId", "operation", "accepted", "code"]
    : ["schemaVersion", "projectId", "operation", "requestId", "state", "code"], status ? ["status"] : ["accepted"])
    || value.schemaVersion !== 1 || value.projectId !== request.projectId || value.operation !== request.operation
    || typeof value.code !== "string" || !CODES.has(value.code)) return unavailable();
  if (status) {
    if (typeof value.accepted !== "boolean") return unavailable();
    if (value.status !== undefined && (!closed(value.status, ["state"], ["activeWorkCount"])
      || typeof value.status.state !== "string" || !["stopped", "starting", "running", "stopping", "failed", "unknown"].includes(value.status.state)
      || (value.status.activeWorkCount !== undefined && (typeof value.status.activeWorkCount !== "number"
        || !Number.isSafeInteger(value.status.activeWorkCount) || value.status.activeWorkCount < 0)))) return unavailable();
    return { ...base, accepted: value.accepted, code: value.code,
      ...(value.status ? { status: { ...(value.status as object) } } : {}) };
  }
  if (value.requestId !== request.requestId || typeof value.state !== "string" || !STATES.has(value.state)
    || (value.accepted !== undefined && typeof value.accepted !== "boolean")
    || (["completed", "queued"].includes(value.state) && value.accepted !== true)
    || (value.state === "queued" && value.code !== "restart_queued")
    || (value.state === "completed" && !["accepted", "close_backoff_coalesced"].includes(value.code))
    || (["rejected", "unknown", "not_found"].includes(value.state) && value.accepted === true)) return unavailable();
  return { ...base, state: value.state, code: value.code, ...(value.accepted !== undefined ? { accepted: value.accepted } : {}) };
}

/** Transport concurrency only. Native queues and request associations own effects.
 * Retirement stops delivery and replies; it never cancels an admitted project command.
 */
export async function runMainControlPump(options: {
  signal: AbortSignal;
  isCurrent: () => boolean;
  invoke: (path: string, method: "GET" | "POST", body?: object) => Promise<unknown>;
  onRequest: (request: MainControlRequest, signal?: AbortSignal) => Promise<unknown>;
  onFailure: () => void;
}): Promise<void> {
  let failed = false;
  const active = new Set<string>();
  const current = () => !failed && !options.signal.aborted && options.isCurrent();
  const worker = async () => {
    try {
      while (current()) {
        const claimed = await options.invoke("/api/assistant/main-control/next", "GET");
        if (!current()) return;
        const request = parseMainControlClaim(claimed);
        if (!request) continue; // The host bounds empty long polls to ten seconds.
        if (active.has(request.deliveryId)) throw new Error("ASSISTANT_MAIN_CONTROL_DUPLICATE");
        active.add(request.deliveryId);
        try {
          let value: unknown;
          try {
            if (request.action === "operator_image_upload" || request.action === "history_import" || request.action === "affairs_sync" || request.action === "initial_migration_queue") value = await options.onRequest(request, AbortSignal.any([options.signal,AbortSignal.timeout(request.timeoutMs)]));
            else if (request.action === "launcher_theme_get" || request.action === "launcher_theme_set") value = await options.onRequest(request,options.signal);
            else value = await options.onRequest(request);
          }
          catch { /* Unknown result is queried by the same request ID, never re-executed here. */ }
          if (!current()) return;
          const result = projectMainControlResult(request, value);
          const acknowledgement = await options.invoke("/api/assistant/main-control/settle", "POST",
            { schemaVersion: 1, deliveryId: request.deliveryId, result });
          if (!closed(acknowledgement, ["schemaVersion", "accepted"]) || acknowledgement.schemaVersion !== 1
            || typeof acknowledgement.accepted !== "boolean") throw new Error("ASSISTANT_MAIN_CONTROL_INVALID");
          // accepted:false is an expired waiter, not permission to repeat an effect.
        } finally { active.delete(request.deliveryId); }
      }
    } catch {
      if (current()) { failed = true; options.onFailure(); }
    }
  };
  await Promise.all(Array.from({ length: 4 }, worker));
}
