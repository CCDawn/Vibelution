import type { SessionDetail } from "../../api/types";

export type AssistantReplyActivity = {
  known: string[] | null;
  unread: string[];
  pulseKey: string;
  pulseUntil: number;
};
export const EMPTY_REPLY_ACTIVITY: AssistantReplyActivity = { known: null, unread: [], pulseKey: "", pulseUntil: 0 };
const LIMIT = 128;

/** Read settled native final messages only. Logical itemId survives revisions. */
export function assistantReplyIds(detail: SessionDetail): string[] {
  return [...new Set((detail.messages ?? []).flatMap(message => {
    if (message.role !== "assistant" || message.status !== "completed"
      || ["session_active_turn_layer", "session_live_overlay"].includes(String(message.metadata?.kind))) return [];
    return (message.turnItems ?? []).filter(item => item.type === "agent_message"
      && item.phase === "final_answer" && item.status === "completed" && item.text.trim())
      .flatMap(item => message.turnId && item.itemId ? [`${message.turnId}:${item.itemId}`] : []);
  }))];
}

export function observeAssistantReplies(previous: AssistantReplyActivity, ids: string[], reading: boolean, now: number): AssistantReplyActivity {
  // First discovery adopts history. A new window never announces historical replies.
  const fresh = previous.known === null ? [] : ids.filter(id => !previous.known!.includes(id));
  const unread = reading ? [] : [...new Set([...previous.unread, ...fresh])].slice(-LIMIT);
  const notify = !reading && fresh.length > 0;
  return {
    known: [...new Set([...(previous.known ?? []), ...ids])].slice(-LIMIT), unread,
    pulseKey: notify ? fresh[fresh.length - 1] : previous.pulseKey,
    pulseUntil: notify ? now + 1400 : previous.pulseUntil,
  };
}

type ReplyStore = {
  getSnapshot: () => AssistantReplyActivity;
  subscribe: (listener: () => void) => () => void;
  observe: (ids: string[], reading: boolean) => void;
  markRead: () => void;
};
const stores = new Map<string, ReplyStore>();

/** UI acknowledgement only: stores bounded native IDs, never message text or transcript. */
export function assistantReplyStore(identity: string): ReplyStore {
  const cached = stores.get(identity);
  if (cached) return cached;
  const storageKey = `vibelution.assistant-replies.v1:${identity}`;
  function load(fallback: AssistantReplyActivity): AssistantReplyActivity {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return fallback;
      const value = JSON.parse(raw) as Partial<AssistantReplyActivity>;
      const ids = (list: unknown) => Array.isArray(list) ? list.filter((id): id is string => typeof id === "string").slice(-LIMIT) : [];
      return { known: value.known === null ? null : ids(value.known), unread: ids(value.unread),
        pulseKey: typeof value.pulseKey === "string" ? value.pulseKey : "",
        pulseUntil: Number.isFinite(value.pulseUntil) ? Number(value.pulseUntil) : 0 };
    } catch { return fallback; }
  }
  let snapshot = load(EMPTY_REPLY_ACTIVITY);
  const listeners = new Set<() => void>();
  function publish(next: AssistantReplyActivity, persist: boolean) {
    if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
    snapshot = next;
    if (persist) { try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* local acknowledgement still works */ } }
    listeners.forEach(listener => listener());
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === storageKey || event.key === null) publish(load(EMPTY_REPLY_ACTIVITY), false);
  };
  const store: ReplyStore = {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      if (listeners.size === 0) window.addEventListener("storage", onStorage);
      listeners.add(listener);
      return () => { listeners.delete(listener); if (!listeners.size) window.removeEventListener("storage", onStorage); };
    },
    observe(ids, reading) { publish(observeAssistantReplies(load(snapshot), ids, reading, Date.now()), true); },
    markRead() { const current = load(snapshot); publish({ ...current, unread: [], pulseUntil: 0 }, true); },
  };
  stores.set(identity, store);
  return store;
}
