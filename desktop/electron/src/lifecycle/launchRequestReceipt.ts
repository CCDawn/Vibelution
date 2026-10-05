import { mkdirSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { resolveLauncherRuntimeDir } from "./projectStoragePaths.js";

const REQUEST_ID = /^launch_[a-f0-9]{32}$/;
const RETENTION_MS = 60 * 60 * 1000;
const seen = new Map<string, number>();

export function normalizeLaunchRequestId(value: unknown): string {
  return typeof value === "string" && REQUEST_ID.test(value) ? value : "";
}

/** Transport feedback only; registry/queue and health remain lifecycle truth. */
export function beginLaunchRequestReceipt(input: {
  shellRoot: string; projectRoot: string; operation: string; requestId?: string;
}): { duplicate: boolean; failed(code: string, message: string): void; dispatched(): void } {
  const requestId = normalizeLaunchRequestId(input.requestId);
  const noop = { duplicate: false, failed: (_code: string, _message: string) => {}, dispatched: () => {} };
  if (!requestId || !["start", "restart", "rebuild-and-start", "stop", "force-stop"].includes(input.operation)) {
    return noop;
  }
  const now = Date.now();
  for (const [key, timestamp] of seen) {
    if (now - timestamp > RETENTION_MS) seen.delete(key);
  }
  if (seen.has(requestId)) return { ...noop, duplicate: true };
  seen.set(requestId, now);
  let receiptPath = "";
  const record = {
    schemaVersion: 1, requestId, projectRoot: resolve(input.projectRoot),
    operation: input.operation, shellPid: process.pid
  };
  try {
    const directory = join(resolveLauncherRuntimeDir(input.shellRoot), "launch-requests");
    mkdirSync(directory, { recursive: true });
    receiptPath = join(directory, `${requestId}.json`);
    // Reap abandoned receipts without following links or touching other files.
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isFile() || !/^launch_[a-f0-9]{32}\.json(?:\.\d+\.tmp)?$/.test(entry.name)) continue;
      try {
        const path = join(directory, entry.name);
        if (now - statSync(path).mtimeMs > RETENTION_MS) unlinkSync(path);
      } catch { /* Another observer may already have removed this receipt. */ }
    }
  } catch {
    // Feedback persistence must never replace or block the lifecycle owner.
  }
  const write = (status: "received" | "failed" | "dispatched", code = "", message = "") => {
    if (!receiptPath) return;
    const temporary = `${receiptPath}.${process.pid}.tmp`;
    try {
      writeFileSync(temporary, JSON.stringify({ ...record, status, code: code.slice(0, 80),
        message: message.slice(0, 300), updatedAt: new Date().toISOString() }), "utf8");
      renameSync(temporary, receiptPath);
    } catch {
      // The Python observer still has the existing registry/queue fallback.
    } finally {
      try { unlinkSync(temporary); } catch { /* Already renamed or never created. */ }
    }
  };
  write("received");
  return {
    duplicate: false,
    failed: (code, message) => write("failed", code, message),
    dispatched: () => write("dispatched")
  };
}
