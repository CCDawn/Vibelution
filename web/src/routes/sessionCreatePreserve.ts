/**
 * Short-lived client pins for optimistic / just-created chat sessions.
 *
 * Create seeds local index caches, then broad `["sessions"]` invalidation can
 * refetch bootstrap/index/agent lists that briefly omit the new row. Keeping a
 * pinned summary lets merge helpers re-attach the tab until the server list
 * catches up (same durability idea as delete tombstones, opposite polarity).
 */

import type { SessionSummary } from "../api/types";
import { isTempSessionId } from "./sessionOptimisticIds";

const DEFAULT_TTL_MS = 60_000;

type PreservedCreate = {
  summary: SessionSummary;
  pinnedAt: number;
};

const preservedBySessionId = new Map<string, PreservedCreate>();

type PreserveClock = {
  nowMs?: number;
  ttlMs?: number;
};

function cleanId(sessionId: string | null | undefined): string {
  return String(sessionId || "").trim();
}

export function pinSessionCreatePreserve(
  summary: SessionSummary,
  options: PreserveClock = {},
): void {
  const id = cleanId(summary.id);
  if (!id) {
    return;
  }
  preservedBySessionId.set(id, {
    summary: { ...summary, id },
    pinnedAt: options.nowMs ?? Date.now(),
  });
}

export function unpinSessionCreatePreserve(sessionId: string): void {
  const id = cleanId(sessionId);
  if (!id) {
    return;
  }
  preservedBySessionId.delete(id);
}

export function clearExpiredSessionCreatePreserves(options: PreserveClock = {}): void {
  const nowMs = options.nowMs ?? Date.now();
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  for (const [sessionId, entry] of preservedBySessionId) {
    if (nowMs - entry.pinnedAt >= ttlMs) {
      preservedBySessionId.delete(sessionId);
    }
  }
}

export function isSessionCreatePreserved(
  sessionId: string,
  options: PreserveClock = {},
): boolean {
  const id = cleanId(sessionId);
  if (!id) {
    return false;
  }
  const entry = preservedBySessionId.get(id);
  if (!entry) {
    return false;
  }
  const nowMs = options.nowMs ?? Date.now();
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  if (nowMs - entry.pinnedAt >= ttlMs) {
    preservedBySessionId.delete(id);
    return false;
  }
  return true;
}

/**
 * Re-attach pinned (and still-local temp) sessions missing from a server page.
 * Once the server includes an id, its pin is cleared.
 */
export function mergePreservedCreatedSessions<T extends { id?: string }>(
  serverItems: T[] | null | undefined,
  options: PreserveClock & { localItems?: Array<T | SessionSummary> | null } = {},
): T[] {
  clearExpiredSessionCreatePreserves(options);
  const serverList = serverItems ?? [];
  const serverIds = new Set(
    serverList.map((item) => cleanId(item.id)).filter(Boolean),
  );

  for (const id of [...preservedBySessionId.keys()]) {
    if (serverIds.has(id)) {
      preservedBySessionId.delete(id);
    }
  }

  const result: T[] = [];
  const seen = new Set<string>();
  const push = (item: T) => {
    const id = cleanId(item.id);
    if (!id || seen.has(id)) {
      return;
    }
    seen.add(id);
    result.push(item);
  };

  for (const entry of preservedBySessionId.values()) {
    push(entry.summary as unknown as T);
  }

  for (const item of options.localItems ?? []) {
    const id = cleanId(item.id);
    if (!id || serverIds.has(id)) {
      continue;
    }
    if (isTempSessionId(id) || isSessionCreatePreserved(id, options)) {
      push(item as unknown as T);
    }
  }

  for (const item of serverList) {
    push(item);
  }

  return result;
}

/** Test helper — clears all in-memory create pins. */
export function resetSessionCreatePreservesForTests(): void {
  preservedBySessionId.clear();
}
