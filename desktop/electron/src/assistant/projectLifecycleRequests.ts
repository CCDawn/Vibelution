import { constants, closeSync, fstatSync, lstatSync, openSync, readSync, realpathSync, type Stats } from "node:fs";
import { dirname, parse } from "node:path";
import { mainLineCommandResultPath } from "../lifecycle/mainLine/commandEvidence.js";
import { projectLifecycleResultCode, type createAssistantProjectLifecycle } from "./projectLifecycle.js";
import {
  AssistantProjectLifecycleRequestStoreError, normalizeLifecycleRequest,
  type AssistantProjectLifecycleRequestStore, type LifecycleRequestIdentity, type LifecycleRequestRecord,
} from "./projectLifecycleRequestStore.js";

export type AssistantLifecycleRequestResult = {
  schemaVersion: 1;
  requestId?: string;
  projectId?: string;
  operation?: LifecycleRequestIdentity["operation"];
  state: "completed" | "queued" | "rejected" | "unknown" | "not_found";
  code: string;
  accepted?: boolean;
};
type Facade = ReturnType<typeof createAssistantProjectLifecycle>;
const MAX_RECEIPT_BYTES = 64 * 1024;
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const same = (a: Stats, b: Stats) => a.dev === b.dev && a.ino === b.ino && a.nlink === b.nlink;

/** Read only the native result, with bounded I/O and no symlink/hardlink traversal.
 * A missing, partial, replaced, handoff-only or error result proves no outcome.
 */
function nativeReceipt(row: LifecycleRequestRecord): Record<string, unknown> | null {
  if (!row.binding || !row.command) return null;
  const path = mainLineCommandResultPath(row.binding.runtimeManagerDir, row.command.commandId);
  try {
    const ancestors: Array<{ path: string; info: Stats; physical: string }> = [];
    for (let current = dirname(path); ; current = dirname(current)) {
      const info = lstatSync(current);
      if (!info.isDirectory() || info.isSymbolicLink()) return null;
      ancestors.push({ path: current, info, physical: realpathSync.native(current) });
      if (current === parse(current).root) break;
    }
    const info = lstatSync(path);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size < 1 || info.size > MAX_RECEIPT_BYTES) return null;
    const descriptor = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    let raw: Buffer;
    try {
      const opened = fstatSync(descriptor);
      if (!same(info, opened) || opened.size !== info.size) return null;
      const bytes = Buffer.alloc(MAX_RECEIPT_BYTES + 1);
      let length = 0, count: number;
      do { count = readSync(descriptor, bytes, length, bytes.length - length, null); length += count; }
      while (count && length < bytes.length);
      const after = fstatSync(descriptor);
      if (length !== info.size || !same(opened, after) || after.size !== info.size
        || after.mtimeMs !== opened.mtimeMs || after.ctimeMs !== opened.ctimeMs) return null;
      raw = bytes.subarray(0, length);
    } finally { closeSync(descriptor); }
    const after = lstatSync(path);
    if (after.isSymbolicLink() || !same(info, after) || after.size !== info.size
      || after.mtimeMs !== info.mtimeMs || after.ctimeMs !== info.ctimeMs) return null;
    for (const ancestor of ancestors) {
      const current = lstatSync(ancestor.path);
      if (!same(ancestor.info, current) || current.isSymbolicLink() || realpathSync.native(ancestor.path) !== ancestor.physical) return null;
    }
    const text = raw.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(raw)) return null;
    const result: unknown = JSON.parse(text);
    if (!object(result) || result.schemaVersion !== 1 || result.source !== "electron_main"
      || result.commandId !== row.command.commandId || result.operation !== row.command.operation || result.type !== row.command.type
      || typeof result.accepted !== "boolean" || result.ok !== result.accepted || result.completed !== true
      || (result.timedOut !== undefined && result.timedOut !== false)
      || typeof result.startedAt !== "string" || !Number.isFinite(Date.parse(result.startedAt))
      || typeof result.settledAt !== "string" || !Number.isFinite(Date.parse(result.settledAt))
      || Date.parse(result.settledAt) < Date.parse(result.startedAt)
      || typeof result.runMs !== "number" || !Number.isFinite(result.runMs) || result.runMs < 0) return null;
    return result;
  } catch { return null; }
}

/** Admission references only: never persists business outcome or replays uncertain work.
 * The caller owns one instance for the lifetime of Electron main. Recreating it
 * resumes receipt lookup, not commands. Request/command IDs are distinct.
 */
export function createAssistantProjectLifecycleRequests(options: {
  facade: Facade;
  store: AssistantProjectLifecycleRequestStore;
}): {
  dispatch(input: unknown, execution?: { signal?: AbortSignal }): Promise<AssistantLifecycleRequestResult>;
  receipt(input: unknown): Promise<AssistantLifecycleRequestResult>;
} {
  const base = (request: LifecycleRequestIdentity) => ({ schemaVersion: 1 as const, ...request });
  const failure = (error: unknown, request?: LifecycleRequestIdentity): AssistantLifecycleRequestResult => ({
    ...(request ? base(request) : { schemaVersion: 1 as const }), state: "rejected",
    code: error instanceof AssistantProjectLifecycleRequestStoreError ? error.code : "request_failed",
  });
  function authorize(request: LifecycleRequestIdentity): void {
    try { options.facade.bindingFor(request.projectId); }
    catch { throw new AssistantProjectLifecycleRequestStoreError("project_unavailable"); }
  }
  function inspect(row: LifecycleRequestRecord): AssistantLifecycleRequestResult {
    const result = base(row.request);
    if (!row.binding || !row.command) return { ...result, state: "unknown", code: "request_unbound" };
    let binding;
    try { binding = options.facade.bindingFor(row.request.projectId); }
    catch { return { ...result, state: "rejected", code: "registration_changed" }; }
    if (JSON.stringify(binding) !== JSON.stringify(row.binding)) return { ...result, state: "rejected", code: "registration_changed" };
    const receipt = nativeReceipt(row);
    // Revalidate permission after filesystem I/O as well as before it.
    try {
      if (JSON.stringify(options.facade.bindingFor(row.request.projectId)) !== JSON.stringify(row.binding)) {
        return { ...result, state: "rejected", code: "registration_changed" };
      }
    } catch { return { ...result, state: "rejected", code: "registration_changed" }; }
    if (!receipt) return { ...result, state: "unknown", code: "receipt_unavailable" };
    const accepted = receipt.accepted as boolean;
    const code = projectLifecycleResultCode(accepted, receipt.code);
    return { ...result, accepted, code, state: !accepted ? "rejected" : code === "restart_queued" ? "queued" : "completed" };
  }
  return {
    async dispatch(input, execution = {}) {
      let request: LifecycleRequestIdentity | undefined;
      let attempted = false;
      try {
        request = normalizeLifecycleRequest(input);
        execution.signal?.throwIfAborted();
        authorize(request);
        const reservation = await options.store.reserve(request);
        if (!reservation.created) return inspect(reservation.record);
        const captured = request, token = reservation.reservationToken!;
        attempted = true;
        const result = await options.facade.dispatch({ projectId: request.projectId, operation: request.operation }, {
          signal: execution.signal,
          onCommand: async (binding, command) => {
            if (!["start", "stop", "restart"].includes(command.operation) || !["open", "close", "restart"].includes(command.type)) {
              throw new Error("unsupported native command");
            }
            await options.store.bind(captured, token, binding, {
              commandId: command.commandId, type: command.type as "open" | "close" | "restart",
              operation: command.operation as LifecycleRequestIdentity["operation"],
            });
          },
        });
        const row = await options.store.get(request.requestId);
        if (!row) return { ...base(request), state: "unknown", code: "receipt_unavailable" };
        if (!row.command && !result.accepted) return { ...base(request), state: "rejected", code: result.code };
        return inspect(row);
      } catch (error) { return { ...failure(error, request), ...(attempted ? { state: "unknown" as const } : {}) }; }
    },
    async receipt(input) {
      let request: LifecycleRequestIdentity | undefined;
      try {
        request = normalizeLifecycleRequest(input);
        authorize(request);
        const row = await options.store.get(request.requestId);
        if (!row) return { ...base(request), state: "not_found", code: "request_not_found" };
        if (JSON.stringify(row.request) !== JSON.stringify(request)) throw new AssistantProjectLifecycleRequestStoreError("request_conflict");
        return inspect(row);
      } catch (error) { return failure(error, request); }
    },
  };
}
