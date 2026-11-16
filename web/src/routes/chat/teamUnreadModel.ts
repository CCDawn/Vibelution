import type { ConversationSummary, SessionSummary, Team } from "../../api/types";
import type { ReadCursorEntry } from "../../api/readCursors";

/**
 * Unread is a pure projection over timestamps the rail already renders:
 *
 * - a direct session is unread when its last activity is newer than the
 *   conversation cursor;
 * - a group room is unread when its last update is newer than its cursor;
 * - a team badge is the number of unread member sessions plus unread rooms.
 *
 * The server only stores cursors, so there is no second message authority and
 * no background unread job to drift from the visible timeline.
 */

export type ReadCursorIndex = Map<string, number>;

const SCOPE_SEPARATOR = ":";

export function readCursorKey(kind: "team" | "conversation", id: string): string {
  return `${kind}${SCOPE_SEPARATOR}${id}`;
}

export function parseTimestampMs(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function buildReadCursorIndex(cursors: readonly ReadCursorEntry[]): ReadCursorIndex {
  const index: ReadCursorIndex = new Map();
  for (const cursor of cursors) {
    const scopeId = String(cursor.scopeId || "").trim();
    if (!scopeId) continue;
    const readAtMs = parseTimestampMs(cursor.readAt);
    if (!readAtMs) continue;
    const key = readCursorKey(cursor.scopeKind, scopeId);
    index.set(key, Math.max(index.get(key) ?? 0, readAtMs));
  }
  return index;
}

export function sessionUnread(
  session: Pick<SessionSummary, "id" | "lastActive" | "updatedAt" | "hiddenFromIndex">,
  index: ReadCursorIndex,
): boolean {
  if (session.hiddenFromIndex) return false;
  const readAtMs = index.get(readCursorKey("conversation", session.id)) ?? 0;
  const lastActivityMs = parseTimestampMs(session.lastActive || session.updatedAt);
  return lastActivityMs > readAtMs;
}

export function roomUnread(
  room: Pick<ConversationSummary, "roomId" | "conversationId" | "updatedAt">,
  index: ReadCursorIndex,
): boolean {
  const roomId = String(room.roomId || room.conversationId || "").trim();
  if (!roomId) return false;
  const readAtMs = index.get(readCursorKey("conversation", roomId)) ?? 0;
  return parseTimestampMs(room.updatedAt) > readAtMs;
}

export type TeamUnreadInput = {
  team: Pick<Team, "teamId" | "linkedChatRoomId" | "linkedChatRoom">;
  sessions: readonly SessionSummary[];
  rooms: readonly ConversationSummary[];
  index: ReadCursorIndex;
};

export function countTeamUnread({ team, sessions, rooms, index }: TeamUnreadInput): number {
  let unread = 0;
  for (const session of sessions) {
    if (sessionUnread(session, index)) unread += 1;
  }
  for (const room of rooms) {
    if (roomUnread(room, index)) unread += 1;
  }
  return unread;
}

/** Entries that mark a whole team read: every member session plus every room. */
export function teamReadEntries(
  { team, sessions, rooms }: Omit<TeamUnreadInput, "index">,
  readAt: string,
): Array<{ scopeKind: "conversation"; scopeId: string; readAt: string }> {
  const ids = new Set<string>();
  for (const session of sessions) {
    const id = String(session.id || "").trim();
    if (id) ids.add(id);
  }
  for (const room of rooms) {
    const id = String(room.roomId || room.conversationId || "").trim();
    if (id) ids.add(id);
  }
  const linkedRoomId = String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim();
  if (linkedRoomId) ids.add(linkedRoomId);
  return [...ids].map((scopeId) => ({ scopeKind: "conversation" as const, scopeId, readAt }));
}
