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
 * When the bridge is down (the exact failure that needs diagnosing), keep a
 * bounded local trace next to the other launcher runtime artifacts so the
 * failure itself does not erase its own evidence.
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
