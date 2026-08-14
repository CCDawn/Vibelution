/**
 * Pure Chat route transition policy (no store, no navigate capability).
 *
 * The committed React Router URL is the single authority for the current Chat
 * selection. These helpers only decide whether a user-confirmed lifecycle
 * result may retire the current explicit route; background misses must keep the
 * URL and render an unavailable surface instead.
 */

export type ArchivedSessionRouteTransition = {
  /** True when the explicit route target is among the archived session ids. */
  shouldRetireRoute: boolean;
  /** Route target after retirement (fallback session id or "" for bare). */
  nextRequestedSessionId: string;
};

/**
 * A user-confirmed Agent archive may retire the explicit route target. The
 * caller must still compare-and-swap: the transition applies only while the
 * current route remains the archived target.
 */
export function resolveArchivedSessionRouteTransition(options: {
  archivedSessionIds: readonly string[];
  requestedSessionId: string | null | undefined;
  fallbackSessionId: string | null | undefined;
}): ArchivedSessionRouteTransition {
  const archivedSessionIds = new Set(
    options.archivedSessionIds.map((sessionId) => String(sessionId || "").trim()).filter(Boolean),
  );
  const requestedSessionId = String(options.requestedSessionId || "").trim();
  const fallbackSessionId = String(options.fallbackSessionId || "").trim();
  const requestedArchived = archivedSessionIds.has(requestedSessionId);
  return {
    shouldRetireRoute: requestedArchived,
    nextRequestedSessionId: requestedArchived ? fallbackSessionId : requestedSessionId,
  };
}

/**
 * The archive endpoint seals the full Agent session set in one transaction.
 * Its returned session list is therefore more authoritative than the currently
 * loaded Chat index, which may be paged or temporarily stale during archive.
 */
export function resolveAuthoritativeArchivedSessionIds(options: {
  optimisticSessionIds?: readonly string[] | null;
  archiveSummary?: {
    sessions?: {
      sessionIds?: unknown;
    } | null;
  } | null;
}): string[] {
  const serverSessionIds = options.archiveSummary?.sessions?.sessionIds;
  const source = Array.isArray(serverSessionIds)
    ? serverSessionIds
    : (options.optimisticSessionIds ?? []);
  return [...new Set(
    source.map((sessionId) => String(sessionId || "").trim()).filter(Boolean),
  )];
}
