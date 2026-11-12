/**
 * Stable conversation-view identity across the optimistic create rebase.
 *
 * `createSessionMutation` opens a temp `temp-session-*` route first and swaps
 * it for the server id on success. The route genuinely changes, but the
 * operator is still looking at the same conversation, so remounting the
 * conversation view there only buys a visible flash and a fresh composer
 * island. This module keeps the one swap addressable: the view key stays on
 * the temp id it was mounted with, and every other switch resolves to its own
 * session id and remounts as before.
 */
let pendingRebase: { fromId: string; toId: string } | null = null;

function normalizeSessionId(sessionId: string | null | undefined): string {
  return String(sessionId || "").trim();
}

/** Record the create rebase that the next render should absorb. */
export function rememberComposerViewRebase(
  fromId: string | null | undefined,
  toId: string | null | undefined,
): void {
  const from = normalizeSessionId(fromId);
  const to = normalizeSessionId(toId);
  if (!from || !to || from === to) {
    return;
  }
  pendingRebase = { fromId: from, toId: to };
}

/**
 * View key for a session id.
 *
 * Only the real id that just replaced a temp id resolves back to that temp id;
 * anything else returns its own id, so ordinary conversation switches keep
 * their current fresh-instance behaviour.
 */
export function resolveComposerViewKey(sessionId: string | null | undefined): string {
  const id = normalizeSessionId(sessionId);
  return pendingRebase && pendingRebase.toId === id ? pendingRebase.fromId : id;
}

/** Test seam: the mapping is module state. */
export function resetComposerViewRebaseForTests(): void {
  pendingRebase = null;
}
