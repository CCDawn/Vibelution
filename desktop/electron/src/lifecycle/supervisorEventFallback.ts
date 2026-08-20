import { appendFileSync, mkdirSync, renameSync, statSync } from "node:fs";
import { dirname, join } from "node:path";

const FALLBACK_FILE_NAME = "electron-supervisor-events.jsonl";
const FALLBACK_MAX_BYTES = 8 * 1024 * 1024;

export type SupervisorEventFallbackInput = {
  eventCode: string;
  message: string;
  fields?: Record<string, unknown>;
};

export type SupervisorEventFallbackRecord = SupervisorEventFallbackInput & {
  at: string;
};

export function supervisorEventFallbackPath(workspaceRoot: string): string {
  return join(workspaceRoot, ".runtime", "launcher", FALLBACK_FILE_NAME);
}

/**
 * Supervisor events normally reach the runtime scene through the backend bridge.
 * I6 decision: keep this independent file instead of appending to Python
 * ``events.jsonl``. Runtime Manager / evolution keep their own JSONL; tools
 * merge the two streams. Dual appenders on one file were the original risk.
 */
export function appendSupervisorEventFallback(
  workspaceRoot: string,
  event: SupervisorEventFallbackInput,
  now: () => Date = () => new Date(),
): boolean {
  const target = supervisorEventFallbackPath(workspaceRoot);
  try {
    mkdirSync(dirname(target), { recursive: true });
    try {
      if (statSync(target).size > FALLBACK_MAX_BYTES) {
        renameSync(target, `${target}.1`);
      }
    } catch {
      // First write or unreadable size; rotation is best-effort.
    }
    const record: SupervisorEventFallbackRecord = { at: now().toISOString(), ...event };
    appendFileSync(target, `${JSON.stringify(record)}\n`, "utf8");
    return true;
  } catch {
    return false;
  }
}
