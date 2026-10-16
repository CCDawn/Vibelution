/**
 * Drag a session page onto the right rail, or a rail tab back onto the top session bar.
 * The payload is a second drag format so composer reference drops keep working.
 */
import type { ChatRightRailTab } from "./chatRightRailModel";

export const PANE_DOCK_MIME = "application/x-vibelution-pane-dock";
export const DOCKED_SESSION_TAB_PREFIX = "docked-session:";

export type PaneDockPayload =
  | { v: 1; source: "session"; sessionId: string; title: string }
  | { v: 1; source: "rail"; tabId: string; sessionId?: string; scope?: "session" | "project" };

export type DockedSession = {
  sessionId: string;
  title: string;
};

export type SessionBarDockChip = {
  key: string;
  tabId: string;
  sessionId: string;
  scope: "session" | "project";
  title: string;
  active: boolean;
};

type DockTransfer = {
  getData?: (format: string) => string;
  setData?: (format: string, data: string) => void;
};

export function dockedSessionTabId(sessionId: string): string {
  return `${DOCKED_SESSION_TAB_PREFIX}${sessionId}`;
}

export function sessionIdFromDockedTab(tabId: string): string | null {
  if (!tabId.startsWith(DOCKED_SESSION_TAB_PREFIX)) {
    return null;
  }
  const sessionId = tabId.slice(DOCKED_SESSION_TAB_PREFIX.length).trim();
  return sessionId || null;
}

export function writePaneDock(transfer: DockTransfer | null | undefined, payload: PaneDockPayload) {
  transfer?.setData?.(PANE_DOCK_MIME, JSON.stringify(payload));
}

export function readPaneDock(transfer: DockTransfer | null | undefined): PaneDockPayload | null {
  const raw = transfer?.getData?.(PANE_DOCK_MIME) ?? "";
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<PaneDockPayload> | null;
    if (!parsed || parsed.v !== 1) {
      return null;
    }
    if (parsed.source === "session") {
      const sessionId = String(parsed.sessionId || "").trim();
      if (!sessionId) {
        return null;
      }
      return {
        v: 1,
        source: "session",
        sessionId,
        title: String(parsed.title || "").trim() || sessionId,
      };
    }
    if (parsed.source === "rail") {
      const tabId = String(parsed.tabId || "").trim();
      if (!tabId) {
        return null;
      }
      const sessionId = String(parsed.sessionId || "").trim();
      return {
        v: 1,
        source: "rail",
        tabId,
        ...(sessionId ? { sessionId } : {}),
        ...(parsed.scope === "project" || parsed.scope === "session" ? { scope: parsed.scope } : {}),
      };
    }
  } catch {
    return null;
  }
  return null;
}

/** Side chats and subagent tabs already point at a session. Other rail tabs stay panels. */
export function railTabSessionTarget(tab: Pick<ChatRightRailTab, "kind" | "targetId" | "childSessionId">): string | null {
  if (tab.kind === "subagent") {
    return tab.targetId?.trim() || null;
  }
  if (tab.kind === "side") {
    return tab.childSessionId?.trim() || null;
  }
  return null;
}

export type SessionBarDrop =
  | { action: "restore-session"; sessionId: string }
  | { action: "open-session"; sessionId: string; closeTabId: string }
  | { action: "show-in-center"; tabId: string }
  | { action: "ignore" };

export function classifySessionBarDrop(
  payload: PaneDockPayload | null,
  tab: Pick<ChatRightRailTab, "id" | "kind" | "targetId" | "childSessionId"> | null,
): SessionBarDrop {
  if (!payload || payload.source !== "rail") {
    return { action: "ignore" };
  }
  const dockedSessionId = sessionIdFromDockedTab(payload.tabId);
  if (dockedSessionId) {
    return { action: "restore-session", sessionId: dockedSessionId };
  }
  if (!tab || tab.id !== payload.tabId) {
    return { action: "ignore" };
  }
  const sessionId = railTabSessionTarget(tab);
  if (sessionId) {
    return { action: "open-session", sessionId, closeTabId: tab.id };
  }
  return { action: "show-in-center", tabId: tab.id };
}
