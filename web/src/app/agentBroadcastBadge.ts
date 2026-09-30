import type { ProjectAgentBusEvent } from "../api/types";

/**
 * Agent-broadcast unread badge for the top-bar bell. The project agent bus is
 * a global broadcast surface (agents and the user can all post), so the shell
 * only tracks "is there anything newer than what I last saw": the latest bus
 * event timestamp is compared against a localStorage read cursor. Opening the
 * broadcast page advances the cursor, which clears the dot.
 */
export const AGENT_BROADCAST_READ_STORAGE_KEY = "vibelution.workbench.agent-broadcast-read.v1";

/** Newest-event timestamp in ms (server appends chronologically; last event wins). */
export function agentBroadcastEventTimeMs(
  event: Pick<ProjectAgentBusEvent, "createdAt" | "updatedAt"> | undefined,
): number {
  if (!event) {
    return 0;
  }
  const raw = String(event.updatedAt || event.createdAt || "").trim();
  if (!raw) {
    return 0;
  }
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function hasUnseenAgentBroadcast(latestEventMs: number, readAtMs: number): boolean {
  return latestEventMs > 0 && latestEventMs > readAtMs;
}

function agentBroadcastStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readStoredAgentBroadcastReadAtMs(): number {
  try {
    const raw = String(agentBroadcastStorage()?.getItem(AGENT_BROADCAST_READ_STORAGE_KEY) ?? "").trim();
    if (!raw) {
      return 0;
    }
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  } catch {
    // Storage unavailable: treat everything as unseen for this visit.
    return 0;
  }
}

export function storeAgentBroadcastReadAtMs(readAtMs: number): void {
  try {
    agentBroadcastStorage()?.setItem(AGENT_BROADCAST_READ_STORAGE_KEY, String(Math.max(0, Math.floor(readAtMs))));
  } catch {
    // The in-memory cursor state still covers this page visit.
  }
}
