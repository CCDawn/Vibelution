/**
 * Pure connect/grace helpers for the Chat session detail SSE.
 * Does not open EventSource — that remains sole owner of useSessionDetailStream.
 */

export const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350;
export const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000;
/**
 * Minimum spacing between authoritative refetches triggered by stream errors.
 * A flapping stream reports an error on every reconnect attempt; refreshing per
 * error rewrites the session cache repeatedly and can drive a render loop.
 */
export const SESSION_STREAM_ERROR_REFRESH_MIN_INTERVAL_MS = 10_000;

export type SessionStreamDecisionSnapshot = {
  sessionId: string;
  shouldConnect: boolean;
  pageVisible: boolean;
  chatStartupWarmupActive: boolean;
  chatPollingVisible: boolean;
  directSessionBackgroundSyncActive: boolean;
  routeTargetMatches: boolean;
  routeSettling: boolean;
  routeSwitchGraceActive: boolean;
  routeSwitchGraceMsRemaining: number;
};

export function resolveSessionStreamRouteTargetMatches(options: {
  activeSessionId: string | null | undefined;
  groupPanelActive: boolean;
  requestedSessionId: string | null | undefined;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const requestedSessionId = String(options.requestedSessionId || "").trim();
  return Boolean(
    activeSessionId
    && !options.groupPanelActive
    && (!requestedSessionId || requestedSessionId === activeSessionId),
  );
}

export function resolveSessionStreamRouteSettling(options: {
  activeSessionId: string | null | undefined;
  groupPanelActive: boolean;
  requestedSessionId: string | null | undefined;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const requestedSessionId = String(options.requestedSessionId || "").trim();
  return Boolean(
    activeSessionId
    && !options.groupPanelActive
    && requestedSessionId
    && requestedSessionId !== activeSessionId,
  );
}

export function resolveSessionStreamRouteSwitchGraceActive(options: {
  activeSessionId: string | null | undefined;
  routeTargetMatches: boolean;
  graceSessionId: string;
  graceUntilMs: number;
  nowMs?: number;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const nowMs = options.nowMs ?? Date.now();
  return Boolean(
    activeSessionId
    && options.routeTargetMatches
    && options.graceSessionId === activeSessionId
    && nowMs < options.graceUntilMs,
  );
}

/**
 * Transport status codes that can never recover by reconnecting: the session
 * is gone (404/410) or the request is not authorized (401/403). The guarded
 * session stream must enter a terminal failure on these instead of looping the
 * 3s reconnect forever; 5xx and network errors keep the reconnect policy.
 */
export const SESSION_STREAM_PERMANENT_FAILURE_STATUSES: readonly number[] = [401, 403, 404, 410];

export function isPermanentSessionStreamFailureStatus(status: number): boolean {
  return SESSION_STREAM_PERMANENT_FAILURE_STATUSES.includes(status);
}

/** Terminal stream failure observed for a session (transport-layer fact). */
export type SessionStreamTerminalFailure = {
  sessionId: string;
  status: number;
};

export function resolveSessionStreamShouldConnect(options: {
  activeSessionId: string | null | undefined;
  routeTargetMatches: boolean;
  chatPollingVisible: boolean;
  routeSwitchGraceActive: boolean;
  /**
   * A hidden window with a busy turn keeps the guarded stream open: closing it
   * drops live deltas and forces a cold reconnect on focus.
   */
  directSessionBackgroundSyncActive?: boolean;
  /** Terminal stream failure (404/410/401/403) for this session: never reconnect. */
  terminalFailure?: SessionStreamTerminalFailure | null;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const terminalFailure = options.terminalFailure;
  if (
    activeSessionId
    && terminalFailure
    && String(terminalFailure.sessionId || "").trim() === activeSessionId
    && isPermanentSessionStreamFailureStatus(terminalFailure.status)
  ) {
    return false;
  }
  return Boolean(
    options.activeSessionId
    && options.routeTargetMatches
    && (
      options.chatPollingVisible
      || options.routeSwitchGraceActive
      || options.directSessionBackgroundSyncActive
    ),
  );
}

/**
 * When the active session changes, open a short grace window so the stream
 * stays connected across route query churn.
 */
export function nextSessionStreamGraceWindow(options: {
  activeSessionId: string | null | undefined;
  currentGraceSessionId: string;
  currentGraceUntilMs: number;
  graceMs?: number;
  nowMs?: number;
}): { graceSessionId: string; graceUntilMs: number; changed: boolean } {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const graceMs = options.graceMs ?? SESSION_STREAM_ROUTE_SWITCH_GRACE_MS;
  const nowMs = options.nowMs ?? Date.now();
  if (!activeSessionId) {
    return {
      graceSessionId: options.currentGraceSessionId,
      graceUntilMs: options.currentGraceUntilMs,
      changed: false,
    };
  }
  if (options.currentGraceSessionId === activeSessionId) {
    return {
      graceSessionId: options.currentGraceSessionId,
      graceUntilMs: options.currentGraceUntilMs,
      changed: false,
    };
  }
  return {
    graceSessionId: activeSessionId,
    graceUntilMs: nowMs + graceMs,
    changed: true,
  };
}
