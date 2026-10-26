import { isAppearanceAction, parseAppearanceClaim, appearanceControlResult, type AppearanceMainControlRequest } from "./appearanceControlProtocol.js";
/** Closed, generation-scoped transport over the existing private host connection.
 * It has no credentials, paths, scheduler, transcript or business-state writer.
 */
export type ProjectMainControlRequest = {
  deliveryId: string;
  projectId: string;
} & ({ action: "project_status"; operation: "status"; requestId?: never }
  | { action: "project_lifecycle" | "project_lifecycle_receipt"; operation: "start" | "stop" | "restart"; requestId: string });
export type MainControlRequest = ProjectMainControlRequest | AppearanceMainControlRequest;
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
/** Fail closed rather than relay arbitrary errors, native rows, paths or messages. */
export function projectMainControlResult(request: MainControlRequest, value: unknown): PublicResult {
  if (request.action === "launcher_theme_get" || request.action === "launcher_theme_set" || request.action === "operator_image_upload") return appearanceControlResult(request,value);
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
            if (request.action === "operator_image_upload") value = await options.onRequest(request, AbortSignal.any([options.signal,AbortSignal.timeout(request.timeoutMs)]));
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
