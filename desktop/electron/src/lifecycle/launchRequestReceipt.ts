import { mkdirSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { resolveLauncherRuntimeDir } from "./projectStoragePaths.js";

const REQUEST_ID = /^launch_[a-f0-9]{32}$/;
const RETENTION_MS = 60 * 60 * 1000;
const seen = new Map<string, number>();

export type LaunchRequestMetadata = {
  launchRequestId?: string;
  launchRequestOperation?: string;
  launchRequestHandoffPid?: number;
};

export type LaunchRequestReceipt = {
  duplicate: boolean;
  failed(code: string, message: string): void;
  dispatched(commandId?: string): void;
  handoff(operation: string): void;
  completed(commandId: string, ready: boolean): void;
  handedOff(): boolean;
};

type ReceiptRecord = Record<string, unknown>;
function readReceipt(path: string): ReceiptRecord | null {
  try {
    const value: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid launch receipt");
    return value as ReceiptRecord;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

function persistenceError(status: string, cause: unknown): Error {
  return new Error(`LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: ${status}`, { cause });
}

export function normalizeLaunchRequestId(value: unknown): string {
  return typeof value === "string" && REQUEST_ID.test(value) ? value : "";
}

/** Feedback from the lifecycle owner; this never runs or retries a lifecycle. */
export function beginLaunchRequestReceipt(input: {
  shellRoot: string; projectRoot: string; operation: string; requestId?: string; handoffFromPid?: number;
}): LaunchRequestReceipt {
  const requestId = normalizeLaunchRequestId(input.requestId);
  const noop: LaunchRequestReceipt = { duplicate: false, failed: () => {}, dispatched: () => {},
    handoff: () => {}, completed: () => {}, handedOff: () => false };
  if (!requestId || !["start", "restart", "rebuild-and-start", "stop", "force-stop"].includes(input.operation)) {
    return noop;
  }
  const now = Date.now();
  for (const [key, timestamp] of seen) {
    if (now - timestamp > RETENTION_MS) seen.delete(key);
  }
  if (seen.has(requestId)) return { ...noop, duplicate: true };
  let receiptPath = "";
  const record = {
    schemaVersion: 1, requestId, projectRoot: resolve(input.projectRoot),
    operation: input.operation, shellPid: process.pid
  };
  try {
    const directory = join(resolveLauncherRuntimeDir(input.shellRoot), "launch-requests");
    mkdirSync(directory, { recursive: true });
    receiptPath = join(directory, `${requestId}.json`);
    const previous = readReceipt(receiptPath);
    if (previous) {
      const resume = previous.schemaVersion === 1 && previous.requestId === requestId
        && previous.projectRoot === record.projectRoot && previous.operation === input.operation
        && previous.status === "handoff" && Number(input.handoffFromPid) > 0
        && previous.shellPid === input.handoffFromPid
        && Number.isFinite(Date.parse(String(previous.updatedAt || "")))
        && now - Date.parse(String(previous.updatedAt)) >= 0
        && now - Date.parse(String(previous.updatedAt)) < RETENTION_MS;
      // Process-local de-duplication is insufficient: a replacement owner must
      // only resume a handoff explicitly addressed by the refresh helper.
      if (!resume) return { ...noop, duplicate: true };
    } else if (Number(input.handoffFromPid) > 0) {
      // Missing/expired handoff evidence never authorizes another execution.
      return { ...noop, duplicate: true };
    }
    // Reap abandoned receipts without following links or touching other files.
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isFile() || !/^launch_[a-f0-9]{32}\.json(?:\.\d+\.tmp)?$/.test(entry.name)) continue;
      try {
        const path = join(directory, entry.name);
        if (now - statSync(path).mtimeMs > RETENTION_MS) unlinkSync(path);
      } catch { /* Another observer may already have removed this receipt. */ }
    }
  } catch (error) {
    // An identified request cannot execute without its durable admission proof.
    throw persistenceError("received", error);
  }
  let handedOff = false;
  const write = (status: "received" | "failed" | "dispatched" | "handoff" | "completed",
    extra: ReceiptRecord = {}, initial = false, required = false) => {
    const temporary = `${receiptPath}.${process.pid}.tmp`;
    try {
      const current = readReceipt(receiptPath);
      if (!initial && current && (current.shellPid !== process.pid || ["failed", "completed"].includes(String(current.status)))) {
        if (required) throw new Error("Launch receipt owner or terminal state changed");
        return;
      }
      writeFileSync(temporary, JSON.stringify({ ...record,
        ...(!initial && current?.commandId ? { commandId: current.commandId } : {}), status, ...extra,
        updatedAt: new Date().toISOString() }), "utf8");
      renameSync(temporary, receiptPath);
    } catch (error) {
      // Admission and handoff must land before any execution/exit. Later
      // feedback failures retain uncertainty rather than replaying a command.
      if (required) throw persistenceError(status, error);
    } finally {
      try { unlinkSync(temporary); } catch { /* Already renamed or never created. */ }
    }
  };
  try {
    write("received", { ...(input.handoffFromPid ? { handoffFromPid: input.handoffFromPid } : {}) }, true, true);
  } catch (error) {
    // A transient failure may still permit a negative acknowledgement. A
    // wholly unavailable feedback surface stays unknown, never successful.
    write("failed", { code: "launch_request_receipt_unavailable", message: String(error).slice(0, 300) }, true);
    throw error;
  }
  seen.set(requestId, now);
  return {
    duplicate: false,
    failed: (code, message) => write("failed", { code: code.slice(0, 80), message: message.slice(0, 300) }),
    dispatched: (commandId = "") => write("dispatched", { commandId }),
    handoff: (operation) => {
      write("handoff", { replacementOperation: operation }, false, true);
      handedOff = true;
    },
    completed: (commandId, ready) => {
      if (!commandId) return;
      const readyAt = new Date().toISOString();
      write("completed", { commandId, accepted: true,
        completion: { ownerPid: process.pid, commandId, ready, readyAt } });
    },
    handedOff: () => handedOff
  };
}
