/**
 * Pure connect/grace helpers for the Chat session detail SSE.
 * Does not open EventSource — that remains sole owner of useSessionDetailStream.
 */

export const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350;
export const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000;

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

export function resolveSessionStreamShouldConnect(options: {
  activeSessionId: string | null | undefined;
  routeTargetMatches: boolean;
  chatPollingVisible: boolean;
  routeSwitchGraceActive: boolean;
}): boolean {
  return Boolean(
    options.activeSessionId
    && options.routeTargetMatches
    && (options.chatPollingVisible || options.routeSwitchGraceActive),
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
