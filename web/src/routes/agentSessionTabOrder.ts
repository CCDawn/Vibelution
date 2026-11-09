import type { SessionSummary } from "../api/types";

/**
 * User-defined ordering for the horizontal Agent session tab strip.
 *
 * The strip is a viewing affordance: drag order is persisted per Agent in
 * localStorage so a manual arrangement survives reloads and session refetches.
 * Sessions that the stored order does not know about (freshly created, or a
 * session that simply was not loaded when the drag happened) keep their
 * incoming position and are appended after the ordered ones.
 */
const STORAGE_KEY = "vibelution.agentSessionTabOrder.v1";

type AgentTabOrderStore = Record<string, string[]>;

/** localStorage accessor that also works when only globalThis is stubbed. */
function sessionTabOrderStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}


function readStore(): AgentTabOrderStore {
  try {
    const raw = sessionTabOrderStorage()?.getItem(STORAGE_KEY) ?? null;
    if (!raw) {
      return {};
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const store: AgentTabOrderStore = {};
    for (const [agentId, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!agentId || !Array.isArray(value)) {
        continue;
      }
      store[agentId] = value
        .map((id) => String(id || "").trim())
        .filter(Boolean);
    }
    return store;
  } catch {
    return {};
  }
}

function writeStore(store: AgentTabOrderStore): void {
  try {
    sessionTabOrderStorage()?.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Storage full or blocked: the strip simply falls back to server order.
  }
}

export function storedAgentSessionTabOrder(agentId: string): string[] {
  const normalized = String(agentId || "").trim();
  if (!normalized) {
    return [];
  }
  return readStore()[normalized] ?? [];
}

/** Reorder sessions to the stored manual order; unknown ids keep their order. */
export function applyAgentSessionTabOrder(
  sessions: readonly SessionSummary[],
  agentId: string,
): SessionSummary[] {
  const order = storedAgentSessionTabOrder(agentId);
  if (!order.length) {
    return [...sessions];
  }
  const rank = new Map(order.map((id, index) => [id, index]));
  return [...sessions].sort((left, right) => {
    const leftRank = rank.get(left.id);
    const rightRank = rank.get(right.id);
    if (leftRank === undefined && rightRank === undefined) {
      return 0;
    }
    if (leftRank === undefined) {
      return 1;
    }
    if (rightRank === undefined) {
      return -1;
    }
    return leftRank - rightRank;
  });
}

export function persistAgentSessionTabOrder(
  agentId: string,
  sessionIds: readonly string[],
): void {
  const normalized = String(agentId || "").trim();
  if (!normalized) {
    return;
  }
  const store = readStore();
  const ids = sessionIds.map((id) => String(id || "").trim()).filter(Boolean);
  if (!ids.length) {
    delete store[normalized];
  } else {
    store[normalized] = ids;
  }
  writeStore(store);
}

/**
 * Move `draggedId` next to `targetId`. Dropping onto itself is a no-op so a
 * stray drag does not rewrite storage.
 */
export function reorderSessionIds(
  ids: readonly string[],
  draggedId: string,
  targetId: string,
  position: "before" | "after",
): string[] {
  if (!draggedId || !targetId || draggedId === targetId) {
    return [...ids];
  }
  if (!ids.includes(draggedId) || !ids.includes(targetId)) {
    return [...ids];
  }
  const remaining = ids.filter((id) => id !== draggedId);
  const targetIndex = remaining.indexOf(targetId);
  if (targetIndex < 0) {
    return [...ids];
  }
  const insertAt = position === "after" ? targetIndex + 1 : targetIndex;
  const next = [...remaining];
  next.splice(insertAt, 0, draggedId);
  return next;
}
