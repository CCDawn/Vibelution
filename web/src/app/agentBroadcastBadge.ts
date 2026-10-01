import type { ProjectAgentBusEvent } from "../api/types";

/**
 * Agent-broadcast unread badge for the top-bar bell. The project agent bus is
 * a global broadcast surface (agents and the user can all post), so the shell
 * only tracks "is there anything newer than what I last saw": the latest bus
 * event timestamp is compared against a localStorage read cursor. Opening the
 * broadcast page advances the cursor, which clears the dot.
 *
 * First-visit semantics: a browser with no stored cursor has never seen the
 * badge, so the first event it observes is silently adopted as the baseline
 * cursor (no unread dot). Only events that land after that baseline count as
 * unseen — history must not light up the bell on first load.
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

/** Result of resolving the bell unread gate for the current snapshot. */
export interface AgentBroadcastBadgeState {
  unread: boolean;
  /** Cursor that should be in effect after this snapshot (ms). */
  cursorMs: number;
  /** True when the first-ever observed event was just silently adopted as the baseline. */
  adoptedBaseline: boolean;
}

/**
 * Resolve the bell unread gate. A null stored cursor means "never seen the
 * badge": the first observed event becomes the silent baseline instead of
 * flagging the whole broadcast history unread. Callers must persist
 * {@link AgentBroadcastBadgeState.cursorMs} when `adoptedBaseline` is true so
 * the baseline survives reloads.
 */
export function resolveAgentBroadcastBadgeState(
  latestEventMs: number,
  storedCursorMs: number | null,
): AgentBroadcastBadgeState {
  if (storedCursorMs === null) {
    if (latestEventMs > 0) {
      return { unread: false, cursorMs: latestEventMs, adoptedBaseline: true };
    }
    // No events observed yet: keep the cursor unset so the genuinely first
    // event still gets adopted as the baseline when it lands.
    return { unread: false, cursorMs: 0, adoptedBaseline: false };
  }
  return {
    unread: hasUnseenAgentBroadcast(latestEventMs, storedCursorMs),
    cursorMs: storedCursorMs,
    adoptedBaseline: false,
  };
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

/**
 * Stored read cursor in ms, or null when this browser has never recorded one
 * (first visit / corrupt value). Null is distinct from "has a cursor": only a
 * null cursor triggers the silent first-sight baseline adoption.
 */
export function readStoredAgentBroadcastReadAtMs(): number | null {
  try {
    const raw = String(agentBroadcastStorage()?.getItem(AGENT_BROADCAST_READ_STORAGE_KEY) ?? "").trim();
    if (!raw) {
      return null;
    }
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  } catch {
    // Storage unavailable: this visit still self-heals through the in-memory
    // null cursor (state adoption happens once per mount at most).
    return null;
  }
}

export function storeAgentBroadcastReadAtMs(readAtMs: number): void {
  try {
    agentBroadcastStorage()?.setItem(AGENT_BROADCAST_READ_STORAGE_KEY, String(Math.max(0, Math.floor(readAtMs))));
  } catch {
    // The in-memory cursor state still covers this page visit.
  }
}
