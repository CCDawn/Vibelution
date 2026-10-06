/**
 * Client tombstones for deleted or server-confirmed missing chat sessions.
 *
 * After optimistic delete, list invalidation can briefly re-introduce rows that
 * the server has not yet dropped (or recovery paths try to resurface). Filtering
 * by this set keeps the UI aligned with the user's delete action without blocking
 * tab switches on a full synchronous purge.
 * Confirmed not-found markers last for the browser process so expired list
 * protection cannot resurrect a cached writable conversation.
 */

const DEFAULT_TTL_MS = 120_000;

const deletedAtBySessionId = new Map<string, { deletedAt: number; confirmed: boolean }>();

type TombstoneClock = {
  nowMs?: number;
  ttlMs?: number;
};

export function markSessionDeleteTombstone(
  sessionId: string,
  options: TombstoneClock & { confirmed?: boolean } = {},
): void {
  const id = String(sessionId || "").trim();
  if (!id) {
    return;
  }
  deletedAtBySessionId.set(id, {
    deletedAt: options.nowMs ?? Date.now(),
    // A server-confirmed not-found must not become an optimistic TTL marker.
    confirmed: Boolean(options.confirmed || deletedAtBySessionId.get(id)?.confirmed),
  });
}

export function clearSessionDeleteTombstone(sessionId: string): void {
  const id = String(sessionId || "").trim();
  if (!id) {
    return;
  }
  deletedAtBySessionId.delete(id);
}

export function clearExpiredSessionDeleteTombstones(options: TombstoneClock = {}): void {
  const nowMs = options.nowMs ?? Date.now();
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  for (const [sessionId, marker] of deletedAtBySessionId) {
    if (!marker.confirmed && nowMs - marker.deletedAt >= ttlMs) {
      deletedAtBySessionId.delete(sessionId);
    }
  }
}

export function isSessionDeleteTombstoned(
  sessionId: string,
  options: TombstoneClock = {},
): boolean {
  const id = String(sessionId || "").trim();
  if (!id) {
    return false;
  }
  const marker = deletedAtBySessionId.get(id);
  if (marker === undefined) {
    return false;
  }
  // Confirmed absence lasts for this browser process, or until explicit clear.
  if (marker.confirmed) {
    return true;
  }
  const nowMs = options.nowMs ?? Date.now();
  const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  if (nowMs - marker.deletedAt >= ttlMs) {
    deletedAtBySessionId.delete(id);
    return false;
  }
  return true;
}

export function filterOutTombstonedSessions<T extends { id?: string }>(
  sessions: T[] | undefined,
  options: TombstoneClock = {},
): T[] | undefined {
  if (!sessions) {
    return sessions;
  }
  clearExpiredSessionDeleteTombstones(options);
  return sessions.filter((session) => !isSessionDeleteTombstoned(String(session.id || ""), options));
}

export function filterOutTombstonedConversations<
  T extends { directSessionId?: string; conversationId?: string; id?: string },
>(
  conversations: T[] | undefined,
  options: TombstoneClock = {},
): T[] | undefined {
  if (!conversations) {
    return conversations;
  }
  clearExpiredSessionDeleteTombstones(options);
  return conversations.filter((conversation) => {
    const candidates = [
      conversation.directSessionId,
      conversation.conversationId,
      conversation.id,
    ];
    return !candidates.some((value) => isSessionDeleteTombstoned(String(value || ""), options));
  });
}

/** Test helper — clears all in-memory tombstones. */
export function resetSessionDeleteTombstonesForTests(): void {
  deletedAtBySessionId.clear();
}
