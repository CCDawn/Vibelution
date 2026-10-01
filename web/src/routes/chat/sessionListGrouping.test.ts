import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  groupSessionsByTimeline,
  sessionListDateBucket,
  splitPinnedSessions,
} from "./sessionListGrouping";

function session(id: string, updatedAt: string, pinnedAtMs?: number): SessionSummary {
  return {
    id,
    title: id,
    status: "ready",
    taskSummary: "",
    lastActive: updatedAt,
    updatedAt,
    currentPhase: "ready",
    ...(pinnedAtMs !== undefined ? { pinnedAtMs } : {}),
  };
}

const NOW = new Date("2026-10-01T12:00:00").getTime();

function daysAgo(days: number, hour = 10): string {
  const date = new Date(NOW - days * 86_400_000);
  date.setHours(hour, 0, 0, 0);
  return date.toISOString();
}

describe("sessionListDateBucket", () => {
  it("buckets by local day boundaries", () => {
    expect(sessionListDateBucket(Date.parse("2026-10-01T00:00:01"), NOW)).toBe("today");
    expect(sessionListDateBucket(Date.parse("2026-09-30T23:59:00"), NOW)).toBe("yesterday");
    expect(sessionListDateBucket(Date.parse("2026-09-27T08:00:00"), NOW)).toBe("thisWeek");
    expect(sessionListDateBucket(Date.parse("2026-09-20T08:00:00"), NOW)).toBe("earlier");
    expect(sessionListDateBucket(Date.parse("2026-10-02T08:00:00"), NOW)).toBe("today");
  });

  it("treats invalid timestamps as earlier via grouping skip", () => {
    expect(groupSessionsByTimeline([session("bad", "not-a-date")], NOW)).toEqual([]);
  });
});

describe("splitPinnedSessions", () => {
  it("separates pinned sessions in pinned_at_ms order", () => {
    const sessions = [
      session("a", daysAgo(0), 100),
      session("b", daysAgo(1)),
      session("c", daysAgo(2), 300),
      session("d", daysAgo(3), 200),
    ];
    const { pinned, unpinned } = splitPinnedSessions(sessions);
    expect(pinned.map((item) => item.id)).toEqual(["c", "d", "a"]);
    expect(unpinned.map((item) => item.id)).toEqual(["b"]);
  });
});

describe("groupSessionsByTimeline", () => {
  it("groups into ordered non-empty buckets, newest first within a bucket", () => {
    const groups = groupSessionsByTimeline(
      [
        session("old-1", daysAgo(30)),
        session("today-late", new Date(NOW - 3_600_000).toISOString()),
        session("yesterday", daysAgo(1)),
        session("week", daysAgo(4)),
        session("today-early", new Date(NOW - 7_200_000).toISOString()),
        session("old-2", daysAgo(20)),
      ],
      NOW,
    );
    expect(groups.map((group) => group.bucket)).toEqual([
      "today",
      "yesterday",
      "thisWeek",
      "earlier",
    ]);
    expect(groups[0]?.sessions.map((item) => item.id)).toEqual(["today-late", "today-early"]);
    expect(groups[3]?.sessions.map((item) => item.id)).toEqual(["old-2", "old-1"]);
  });
});
