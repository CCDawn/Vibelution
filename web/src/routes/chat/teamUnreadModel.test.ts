import { describe, expect, it } from "vitest";

import type { ConversationSummary, SessionSummary, Team } from "../../api/types";
import {
  buildReadCursorIndex,
  countTeamUnread,
  parseTimestampMs,
  readCursorKey,
  roomUnread,
  sessionUnread,
  teamReadEntries,
} from "./teamUnreadModel";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "Session",
    status: "active",
    taskSummary: "",
    lastActive: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    currentPhase: "",
    excludedContextSummary: "",
    ...overrides,
  } as SessionSummary;
}

function room(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "room-1",
    type: "group_room",
    title: "Room",
    status: "active",
    summary: "",
    updatedAt: "2026-01-01T00:00:00Z",
    workspacePath: "",
    ...overrides,
  } as ConversationSummary;
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    teamId: "team-1",
    name: "Team",
    description: "",
    purpose: "",
    status: "active",
    teamKind: "custom",
    teamCategory: "",
    teamSource: "manual",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
    ...overrides,
  } as Team;
}

describe("teamUnreadModel", () => {
  it("treats activity after the cursor as unread", () => {
    const index = buildReadCursorIndex([
      { scopeKind: "conversation", scopeId: "session-1", readAt: "2026-01-02T00:00:00Z" },
    ]);
    expect(sessionUnread(session({ lastActive: "2026-01-03T00:00:00Z" }), index)).toBe(true);
    expect(sessionUnread(session({ lastActive: "2026-01-01T00:00:00Z" }), index)).toBe(false);
  });

  it("ignores hidden sessions", () => {
    const index = new Map<string, number>();
    expect(sessionUnread(session({ hiddenFromIndex: true }), index)).toBe(false);
  });

  it("counts unread member sessions and rooms", () => {
    const index = buildReadCursorIndex([
      { scopeKind: "conversation", scopeId: "session-1", readAt: "2026-01-02T00:00:00Z" },
      { scopeKind: "conversation", scopeId: "session-2", readAt: "2026-01-02T00:00:00Z" },
      { scopeKind: "conversation", scopeId: "room-1", readAt: "2026-01-01T00:00:00Z" },
    ]);
    const result = countTeamUnread({
      team: team(),
      sessions: [
        session({ id: "session-1", lastActive: "2026-01-03T00:00:00Z" }),
        session({ id: "session-2", lastActive: "2026-01-01T00:00:00Z" }),
      ],
      rooms: [room({ roomId: "room-1", updatedAt: "2026-01-03T00:00:00Z" })],
      index,
    });
    expect(result).toBe(2);
  });

  it("keeps the newest cursor when the same scope is written twice", () => {
    const index = buildReadCursorIndex([
      { scopeKind: "conversation", scopeId: "session-1", readAt: "2026-01-05T00:00:00Z" },
      { scopeKind: "conversation", scopeId: "session-1", readAt: "2026-01-01T00:00:00Z" },
    ]);
    expect(index.get(readCursorKey("conversation", "session-1"))).toBe(parseTimestampMs("2026-01-05T00:00:00Z"));
  });

  it("collects every member session and room for a team mark-read", () => {
    const entries = teamReadEntries(
      {
        team: team({ linkedChatRoomId: "room-linked" }),
        sessions: [session({ id: "session-1" }), session({ id: "session-2" })],
        rooms: [room({ roomId: "room-1" })],
      },
      "2026-01-06T00:00:00Z",
    );
    expect(entries.map((entry) => entry.scopeId).sort()).toEqual(["room-1", "room-linked", "session-1", "session-2"]);
    expect(entries.every((entry) => entry.scopeKind === "conversation")).toBe(true);
  });

  it("flags rooms by last update", () => {
    const index = buildReadCursorIndex([
      { scopeKind: "conversation", scopeId: "room-1", readAt: "2026-01-02T00:00:00Z" },
    ]);
    expect(roomUnread(room({ roomId: "room-1", updatedAt: "2026-01-03T00:00:00Z" }), index)).toBe(true);
    expect(roomUnread(room({ roomId: "room-1", updatedAt: "2026-01-01T00:00:00Z" }), index)).toBe(false);
  });
});
