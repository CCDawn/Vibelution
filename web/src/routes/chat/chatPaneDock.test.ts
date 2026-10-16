import { describe, expect, it } from "vitest";

import {
  EMPTY_CHAT_RIGHT_RAIL,
  openChatRightRailTab,
  setChatRightRailTabHost,
} from "./chatRightRailModel";
import {
  PANE_DOCK_MIME,
  classifySessionBarDrop,
  dockedSessionTabId,
  readPaneDock,
  sessionIdFromDockedTab,
  writePaneDock,
} from "./chatPaneDock";

describe("chat pane dock", () => {
  it("round-trips a session drag and a rail drag", () => {
    const store = new Map<string, string>();
    const transfer = {
      setData: (format: string, data: string) => {
        store.set(format, data);
      },
      getData: (format: string) => store.get(format) ?? "",
    };
    writePaneDock(transfer, { v: 1, source: "session", sessionId: "s-1", title: "设计" });
    expect(readPaneDock(transfer)).toEqual({ v: 1, source: "session", sessionId: "s-1", title: "设计" });
    expect(store.has(PANE_DOCK_MIME)).toBe(true);
    writePaneDock(transfer, { v: 1, source: "rail", tabId: "review", scope: "session", sessionId: "s-1" });
    expect(readPaneDock(transfer)?.source).toBe("rail");
  });

  it("rejects a malformed payload", () => {
    expect(readPaneDock({ getData: () => "" })).toBeNull();
    expect(readPaneDock({ getData: () => "not-json" })).toBeNull();
    expect(readPaneDock({ getData: () => JSON.stringify({ v: 1, source: "session" }) })).toBeNull();
  });

  it("recognises a docked session tab id", () => {
    expect(sessionIdFromDockedTab(dockedSessionTabId("session-9"))).toBe("session-9");
    expect(sessionIdFromDockedTab("review")).toBeNull();
  });

  it("sends a docked session back to the session bar", () => {
    expect(classifySessionBarDrop(
      { v: 1, source: "rail", tabId: dockedSessionTabId("session-9") },
      null,
    )).toEqual({ action: "restore-session", sessionId: "session-9" });
  });

  it("opens a side chat that already has a session, and keeps a review tab as a center panel", () => {
    expect(classifySessionBarDrop(
      { v: 1, source: "rail", tabId: "side" },
      { id: "side", kind: "side", childSessionId: "child-1" },
    )).toEqual({ action: "open-session", sessionId: "child-1", closeTabId: "side" });
    expect(classifySessionBarDrop(
      { v: 1, source: "rail", tabId: "review" },
      { id: "review", kind: "review" },
    )).toEqual({ action: "show-in-center", tabId: "review" });
    expect(classifySessionBarDrop(
      { v: 1, source: "session", sessionId: "s-1", title: "设计" },
      null,
    )).toEqual({ action: "ignore" });
  });

  it("remembers that a rail tab was moved to the center", () => {
    const opened = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "review", title: "审查" });
    const parked = setChatRightRailTabHost(opened, "review", "center");
    expect(parked.activeId).toBe("review");
    expect(parked.tabs[0]?.host).toBe("center");
    const reopened = openChatRightRailTab(parked, { kind: "review" });
    expect(reopened.tabs[0]?.host).toBe("center");
    const returned = setChatRightRailTabHost(reopened, "review", "rail");
    expect(returned.tabs[0]?.host).toBeUndefined();
    expect(returned.activeId).toBe("review");
  });
});
