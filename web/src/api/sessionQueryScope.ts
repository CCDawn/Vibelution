/**
 * Scope of a session-index refresh after a turn commits.
 *
 * The session index lives under one `sessions` prefix but several key shapes:
 * the bare default list, the paginated/searched `query` variants, and the
 * archived listing. A committed turn only changes the recency and status of the
 * session that ran it, so broad invalidation re-fetches every shape — including
 * the search a user may be typing into and deep cursor pages nobody is looking
 * at. Keep the pages that actually represent "my session list" fresh and leave
 * open search/deep-cursor variants to their own lifecycle.
 */
export function isSessionIndexQueryStaleAfterTurn(queryKey: readonly unknown[]): boolean {
  if (queryKey[0] !== "sessions") {
    return false;
  }
  if (queryKey.length === 1) {
    return true;
  }
  if (queryKey[1] !== "query") {
    // Archived listing and any other members of the `sessions` family still
    // describe the same session set, so a committed turn can change them.
    return true;
  }
  const search = queryKey[2];
  const cursor = queryKey[4];
  return !search && !cursor;
}

/** Whether a `sessions` key belongs to a search or deep-cursor page. */
export function isSessionIndexQueryNarrowedByUser(queryKey: readonly unknown[]): boolean {
  return queryKey[0] === "sessions"
    && queryKey[1] === "query"
    && Boolean(queryKey[2] || queryKey[4]);
}
