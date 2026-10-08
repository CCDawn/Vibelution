import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  ARCHIVED_SESSION_RAIL_COLLAPSED_LIMIT,
  sortArchivedSessions,
  visibleArchivedSessions,
} from "./archivedSessionRailModel";

function session(id: string, updatedAt: string, createdAt = updatedAt): SessionSummary {
  return {
    id,
    title: id,
    status: "idle",
    taskSummary: "",
    lastActive: updatedAt,
    updatedAt,
    createdAt,
    currentPhase: "idle",
    conversationIndexErrors: [],
  };
}

describe("archived session rail model", () => {
  it("sorts by the rail preference and keeps the collapsed page at 20", () => {
    const sessions = Array.from({ length: 21 }, (_, index) => session(
      `s-${index}`,
      `2026-06-${String(index + 1).padStart(2, "0")}T00:00:00.000Z`,
      `2026-01-${String((index % 28) + 1).padStart(2, "0")}T00:00:00.000Z`,
    ));
    const byUpdated = sortArchivedSessions(sessions, "updatedAt");
    expect(byUpdated[0]?.id).toBe("s-20");
    expect(visibleArchivedSessions(byUpdated, false)).toHaveLength(ARCHIVED_SESSION_RAIL_COLLAPSED_LIMIT);
    expect(visibleArchivedSessions(byUpdated, true)).toHaveLength(21);

    const byCreated = sortArchivedSessions(sessions, "createdAt");
    expect(byCreated[0]?.id).toBe("s-20");
  });
});
