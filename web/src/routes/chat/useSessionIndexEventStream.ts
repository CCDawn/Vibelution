import { useEffect } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import {
  removeSessionFromAgentSessionCaches,
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

function patchSessionRow(
  queryClient: QueryClient,
  sessionId: string,
  patch: Record<string, unknown>,
): void {
  updateSessionSummaryCaches(queryClient, (sessions) => {
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
  });
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
 * Keep the rail convergent from the server instead of from the window that ran
 * the turn. Disabled while the route is not showing a session list.
 */
export function useSessionIndexEventStream(
  queryClient: QueryClient,
  options: { enabled: boolean },
): void {
  const enabled = options.enabled;
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const waitForReconnect = () => new Promise<void>((resolve) => {
      reconnectTimer = setTimeout(resolve, SESSION_INDEX_RECONNECT_MS);
    });

    const run = async () => {
      while (!stopped) {
        try {
          await consumeGuardedEventStream({
            url: SESSION_INDEX_EVENTS_PATH,
            signal: controller.signal,
            onFrame: (frame) => {
              const delta = parseSessionIndexDelta(frame.data);
              if (delta) {
                applySessionIndexDeltaToQueryClient(queryClient, delta);
              }
            },
          });
        } catch {
          // A dropped read is recoverable; the reconnect below owns recovery.
        }
        if (stopped) {
          return;
        }
        await waitForReconnect();
      }
    };

    void run();

    return () => {
      stopped = true;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      controller.abort();
    };
  }, [enabled, queryClient]);
}
