import { useEffect, useRef, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionSummary } from "../../api/types";
import {
  clearSessionLiveCompletion,
  markSessionLiveCompletion,
} from "../sessionActivityIndicator";
import { resolveSessionActivity } from "../sessionActivityState";
import {
  removeSessionFromAgentSessionCaches,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import { consumeGuardedEventStream } from "./guardedEventStream";

/**
 * One connection covers every session's index row. The per-session transcript
 * stream stays the authority for what a session *contains*; this stream only
 * says which rail row moved, so a settled turn no longer has to invalidate the
 * whole `["sessions"]` prefix and refetch pages nobody is looking at.
 */
export const SESSION_INDEX_EVENTS_PATH = "/api/sessions/events";

/** Reconnect cadence for an index stream that dropped. */
const SESSION_INDEX_RECONNECT_MS = 3_000;

export type SessionIndexDelta = {
  /** `session.upserted` | `session.removed`. */
  type: string;
  sessionId: string;
  at?: string;
  /**
   * Index-row fields the change actually moved. Absent on frames the server
   * could only classify, which forces one index read instead of a silent miss.
   */
  patch?: Record<string, unknown>;
};

/**
 * Parse one SSE `data:` payload. `ready` and `heartbeat` frames carry no row
 * change and must not reach the query cache.
 */
export function parseSessionIndexDelta(data: string): SessionIndexDelta | null {
  const raw = String(data ?? "").trim();
  if (!raw) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  const sessionId = String(record.sessionId ?? "").trim();
  const type = String(record.type ?? "").trim();
  if (!sessionId || !type) {
    return null;
  }
  if (type !== "session.upserted" && type !== "session.removed") {
    return null;
  }
  const at = String(record.at ?? "").trim();
  const patch = (
    record.patch && typeof record.patch === "object"
      ? record.patch as Record<string, unknown>
      : undefined
  );
  const delta: SessionIndexDelta = { type, sessionId };
  if (at) {
    delta.at = at;
  }
  if (patch && Object.keys(patch).length > 0) {
    delta.patch = patch;
  }
  return delta;
}

function applySessionPatch(
  sessions: SessionSummary[] | undefined,
  sessionId: string,
  patch: Record<string, unknown>,
): SessionSummary[] | undefined {
  if (!sessions) {
    return sessions;
  }
  let changed = false;
  const next = sessions.map((session) => {
    if (session.id !== sessionId) {
      return session;
    }
    changed = true;
    return { ...session, ...patch } as typeof session;
  });
  // Reference-identical when the row is not on this page: the caches keep
  // their previous value and no subscriber re-renders.
  return changed ? next : sessions;
}

/**
 * A patch that says the row stopped is a completion nobody has opened yet, so it
 * has to outrank the first-paint silence. A patch that says the row started
 * running again drops the mark: the next settle is a different completion.
 */
function syncLiveCompletion(sessionId: string, patch: Record<string, unknown>): void {
  const text = (value: unknown) => (typeof value === "string" ? value : undefined);
  const state = resolveSessionActivity({
    status: text(patch.status),
    currentPhase: text(patch.currentPhase),
    lastTurnStatus: text(patch.lastTurnStatus),
    terminalReason: text(patch.terminalReason),
  });
  if (state.execution === "settled" || state.execution === "idle") {
    markSessionLiveCompletion(sessionId);
    return;
  }
  if (
    state.execution === "running"
    || state.execution === "queued"
    || state.execution === "stopping"
    || state.execution === "paused"
  ) {
    clearSessionLiveCompletion(sessionId);
  }
}

function patchSessionRow(
  queryClient: QueryClient,
  sessionId: string,
  patch: Record<string, unknown>,
): void {
  syncLiveCompletion(sessionId, patch);
  const apply = (sessions: SessionSummary[] | undefined) =>
    applySessionPatch(sessions, sessionId, patch);
  updateSessionSummaryCaches(queryClient, apply);
  // The Agent tab strip keeps its own per-Agent cache; the rail must move
  // there too, or a background session only updates after it is opened.
  updateAgentSessionSummaryCaches(queryClient, apply);
}

function removeSessionRow(
  queryClient: QueryClient,
  sessionId: string,
): void {
  updateSessionSummaryCaches(queryClient, (sessions) => {
    if (!sessions) {
      return sessions;
    }
    const next = sessions.filter((session) => session.id !== sessionId);
    return next.length === sessions.length ? sessions : next;
  });
  removeSessionFromAgentSessionCaches(queryClient, sessionId);
}

/**
 * Apply one index delta. A frame that carries no patch means "this row moved,
 * I could not say how" — that is the only case that still costs a list read.
 */
export function applySessionIndexDeltaToQueryClient(
  queryClient: QueryClient,
  delta: SessionIndexDelta,
): void {
  const sessionId = String(delta.sessionId ?? "").trim();
  if (!sessionId) {
    return;
  }
  if (delta.type === "session.removed") {
    removeSessionRow(queryClient, sessionId);
    return;
  }
  if (delta.patch && Object.keys(delta.patch).length > 0) {
    patchSessionRow(queryClient, sessionId, delta.patch);
    return;
  }
  void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
}

/**
 * A reconnect may have missed frames while the socket was down. The index
 * stream does not replay, so every connection after the first one re-reads
 * the rail once instead of trusting a delta we may never have seen.
 */
export function shouldResyncIndexOnConnect(previousConnections: number): boolean {
  return previousConnections > 0;
}

/**
 * Keep the rail convergent from the server instead of from the window that ran
 * the turn. Disabled while the route is not showing a session list.
 */
export function useSessionIndexEventStream(
  queryClient: QueryClient,
  options: {
    enabled: boolean;
    /**
     * Receives every upsert patch. A caller that also keeps local turn state
     * settles it here: this socket is the only signal a background session has.
     */
    onUpsertedPatch?: (sessionId: string, patch: Record<string, unknown>) => void;
  },
): boolean {
  const enabled = options.enabled;
  // Held in a ref so a fresh callback identity never re-opens the socket.
  const onUpsertedPatchRef = useRef(options.onUpsertedPatch);
  useEffect(() => {
    onUpsertedPatchRef.current = options.onUpsertedPatch;
  }, [options.onUpsertedPatch]);
  // The rail's polling policy needs to know whether this socket is actually
  // open: when it is down, no delta arrives for any background session.
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      setConnected(false);
      return;
    }
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const waitForReconnect = () => new Promise<void>((resolve) => {
      reconnectTimer = setTimeout(resolve, SESSION_INDEX_RECONNECT_MS);
    });

    let connections = 0;

    const run = async () => {
      while (!stopped) {
        if (shouldResyncIndexOnConnect(connections)) {
          // Frames dropped while this socket was down never come back, so the
          // rail re-reads instead of waiting for the next manual index read.
          void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
        }
        connections += 1;
        try {
          await consumeGuardedEventStream({
            url: SESSION_INDEX_EVENTS_PATH,
            signal: controller.signal,
            onOpen: () => setConnected(true),
            onFrame: (frame) => {
              const delta = parseSessionIndexDelta(frame.data);
              if (!delta) {
                return;
              }
              applySessionIndexDeltaToQueryClient(queryClient, delta);
              if (delta.type === "session.upserted" && delta.patch) {
                onUpsertedPatchRef.current?.(delta.sessionId, delta.patch);
              }
            },
          });
        } catch {
          // A dropped read is recoverable; the reconnect below owns recovery.
        }
        setConnected(false);
        if (stopped) {
          return;
        }
        await waitForReconnect();
      }
    };

    void run();

    return () => {
      stopped = true;
      setConnected(false);
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      controller.abort();
    };
  }, [enabled, queryClient]);
  return connected;
}
