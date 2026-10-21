/**
 * Cross-window session-index change notifications.
 *
 * A pin/unpin/archive/delete write only invalidates React Query caches in the
 * window that performed it. Every other window may have a session stream that
 * owns live queries with the index poll off (`resolveChatLiveQueryPolicy`), and
 * a metadata flip produces no transcript frame to carry it — so its session
 * rail never converges. The writing window announces the change through the
 * same localStorage `storage`-event channel used by theme/font preferences,
 * and other windows invalidate their sessions index query on receipt.
 */
import { useEffect } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";
import { getPageInstanceId } from "../app/pageInstance";

export const SESSION_INDEX_SYNC_STORAGE_KEY = "vibelution.chat.session-index-sync";

export type SessionIndexChangeType =
  | "pin"
  | "unpin"
  | "archive"
  | "unarchive"
  | "delete"
  | "metadata";

export type SessionIndexChangeMessage = {
  sessionId: string;
  changeType: SessionIndexChangeType;
  /** Page instance id of the writing window; receivers skip their own writes. */
  sourceId: string;
  /** Write wall-clock; keeps consecutive identical writes distinguishable. */
  at: number;
};

const SESSION_INDEX_CHANGE_TYPES: readonly SessionIndexChangeType[] = [
  "pin",
  "unpin",
  "archive",
  "unarchive",
  "delete",
  "metadata",
];

export function normalizeSessionIndexChangeType(value: unknown): SessionIndexChangeType | null {
  const text = String(value ?? "").trim();
  return (SESSION_INDEX_CHANGE_TYPES as readonly string[]).includes(text)
    ? text as SessionIndexChangeType
    : null;
}

export function parseSessionIndexChangeMessage(rawValue: unknown): SessionIndexChangeMessage | null {
  if (typeof rawValue !== "string" || !rawValue.trim()) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawValue) as Partial<SessionIndexChangeMessage> | null;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const sessionId = String(parsed.sessionId ?? "").trim();
    const changeType = normalizeSessionIndexChangeType(parsed.changeType);
    if (!sessionId || !changeType) {
      return null;
    }
    const at = Number(parsed.at);
    return {
      sessionId,
      changeType,
      sourceId: String(parsed.sourceId ?? "").trim(),
      at: Number.isFinite(at) ? at : 0,
    };
  } catch {
    return null;
  }
}

function browserLocalStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

/**
 * Announce a session-index write to every other browser window. Storage events
 * are not delivered to the writing document itself; the payload still carries
 * `sourceId` so a receiver that also listens (or a future BroadcastChannel
 * transport) can deduplicate its own writes. Never throws.
 */
export function broadcastSessionIndexChange(
  message: { sessionId: string; changeType: SessionIndexChangeType; sourceId?: string; at?: number },
  storage: Storage | null = browserLocalStorage(),
): void {
  const payload: SessionIndexChangeMessage = {
    sessionId: String(message.sessionId || "").trim(),
    changeType: normalizeSessionIndexChangeType(message.changeType) ?? "metadata",
    sourceId: String(message.sourceId ?? getPageInstanceId()).trim(),
    at: message.at ?? Date.now(),
  };
  if (!payload.sessionId || !storage) {
    return;
  }
  try {
    storage.setItem(SESSION_INDEX_SYNC_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Quota/private-mode failures must not break the mutation that triggered it.
  }
}

export type SessionIndexChangeListener = (message: SessionIndexChangeMessage) => void;

/**
 * Subscribe to session-index writes from other windows. `ownSourceId` filters
 * self-originated messages so a writer that also listens never double-applies.
 */
export function subscribeSessionIndexChanges(
  listener: SessionIndexChangeListener,
  options: { ownSourceId?: string; storageKey?: string } = {},
): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const storageKey = options.storageKey ?? SESSION_INDEX_SYNC_STORAGE_KEY;
  const ownSourceId = String(options.ownSourceId ?? "").trim();
  const onStorage = (event: StorageEvent) => {
    // key === null means clear(); it carries no session change.
    if (event.key !== storageKey) {
      return;
    }
    const message = parseSessionIndexChangeMessage(event.newValue);
    if (!message) {
      return;
    }
    if (ownSourceId && message.sourceId === ownSourceId) {
      return;
    }
    listener(message);
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}

/**
 * Cross-window reaction to a session-index write: the sessions index query is
 * the shared rail authority, and its `["sessions"]` prefix also reaches the
 * archived listing and per-session detail caches.
 */
export function applySessionIndexChangeToQueryClient(
  queryClient: QueryClient,
  message: SessionIndexChangeMessage,
): void {
  if (!message.sessionId) {
    return;
  }
  void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
}

/** Chat-route glue: keep the rail convergent across windows. */
export function useSessionIndexCrossWindowSync(queryClient: QueryClient): void {
  useEffect(() => {
    return subscribeSessionIndexChanges(
      (message) => applySessionIndexChangeToQueryClient(queryClient, message),
      { ownSourceId: getPageInstanceId() },
    );
  }, [queryClient]);
}
