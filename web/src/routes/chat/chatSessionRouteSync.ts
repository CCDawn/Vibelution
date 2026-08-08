import { isTempSessionId } from "../sessionOptimisticIds";

/**
 * Pure helpers for URL ↔ active session sync during optimistic tab switches.
 *
 * handleOpenDirectSession sets activeSessionId before React Router updates
 * location.search. A naive "URL is source of truth" effect would immediately
 * stomp the optimistic id back to the previous ?session=… and look stuck.
 */

export const SESSION_ROUTE_INTENT_GRACE_MS = 2_000;

export function shouldCanonicalizeUrlSessionSelection(options: {
  requestedSessionId: string | null | undefined;
  activeSessionId: string | null | undefined;
  intentSessionId: string | null | undefined;
}): boolean {
  const requestedSessionId = String(options.requestedSessionId || "").trim();
  if (!requestedSessionId || isTempSessionId(requestedSessionId)) {
    return false;
  }
  const activeSessionId = String(options.activeSessionId || "").trim();
  const intentSessionId = String(options.intentSessionId || "").trim();
  // A route target is canonicalized unless the current user intent already
  // scheduled the same server-side select (the normal tab-click path).
  return activeSessionId !== requestedSessionId || intentSessionId !== requestedSessionId;
}

export function shouldDeferUrlSessionSync(options: {
  requestedSessionId: string | null | undefined;
  activeSessionId: string | null | undefined;
  intentSessionId: string | null | undefined;
  intentAtMs: number;
  nowMs?: number;
  graceMs?: number;
}): boolean {
  const requestedSessionId = String(options.requestedSessionId || "").trim();
  const activeSessionId = String(options.activeSessionId || "").trim();
  const intentSessionId = String(options.intentSessionId || "").trim();
  if (!requestedSessionId || !activeSessionId) {
    return false;
  }
  if (activeSessionId === requestedSessionId) {
    return false;
  }
  // Only defer when the operator already painted the target optimistically and
  // the URL has not caught up yet (navigate in flight).
  if (!intentSessionId || intentSessionId !== activeSessionId || intentSessionId === requestedSessionId) {
    return false;
  }
  const nowMs = options.nowMs ?? Date.now();
  const graceMs = options.graceMs ?? SESSION_ROUTE_INTENT_GRACE_MS;
  return nowMs - Number(options.intentAtMs || 0) < graceMs;
}
