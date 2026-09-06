import { describe, expect, it } from "vitest";
import type { SessionSummary } from "../api/types";
import { recentAgentSessions, searchAgentSessionHistory } from "./agentSessionHistory";

const sessions = Array.from({ length: 100 }, (_, i) => ({
  id: `session-${i}`, title: `讨论 ${i}`, taskSummary: i === 12 ? "来源核验" : "", updatedAt: new Date(i * 1000).toISOString(),
})) as SessionSummary[];

describe("agent session history", () => {
  it("keeps five recent sessions and the active/renaming targets without deleting history", () => {
    const visible = recentAgentSessions(sessions, ["session-12", "session-13"]);
    expect(visible.map(s => s.id)).toEqual(["session-12", "session-13", "session-95", "session-96", "session-97", "session-98", "session-99"]);
    expect(sessions).toHaveLength(100);
    expect(sessions[0].id).toBe("session-0");
  });
  it("searches all history rather than the visible tabs", () => {
    expect(searchAgentSessionHistory(sessions, " 来源核验 ").map(s => s.id)).toEqual(["session-12"]);
    expect(searchAgentSessionHistory(sessions, "SESSION-99").map(s => s.id)).toEqual(["session-99"]);
    expect(searchAgentSessionHistory(sessions, "不存在")).toEqual([]);
    expect(searchAgentSessionHistory(sessions, "")).toHaveLength(100);
  });
});
