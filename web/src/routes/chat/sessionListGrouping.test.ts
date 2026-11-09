import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  groupSessionsByTimeline,
  sessionListDateBucket,
  sortSessionsStableRecency,
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

describe("sortSessionsStableRecency", () => {
  it("orders unpinned sessions by updatedAt descending", () => {
    const loaded = [
      session("older", daysAgo(2)),
      session("newest", daysAgo(0)),
      session("middle", daysAgo(1)),
    ];
    expect(sortSessionsStableRecency(loaded).map((item) => item.id))
      .toEqual(["newest", "middle", "older"]);
  });

  it("falls back to lastActive when updatedAt is missing", () => {
    const withLastActive = { ...session("b", daysAgo(1)), updatedAt: "" };
    const sorted = sortSessionsStableRecency([
      session("a", daysAgo(3)),
      withLastActive,
    ]);
    expect(sorted.map((item) => item.id)).toEqual(["b", "a"]);
    expect(Date.parse(withLastActive.lastActive)).toBe(Date.parse(daysAgo(1)));
  });

  it("breaks same-timestamp ties by id descending regardless of loaded order", () => {
    const sameTs = daysAgo(1);
    const forward = sortSessionsStableRecency([
      session("s-a", sameTs),
      session("s-b", sameTs),
      session("s-c", sameTs),
    ]);
    const backward = sortSessionsStableRecency([
      session("s-c", sameTs),
      session("s-b", sameTs),
      session("s-a", sameTs),
    ]);
    expect(forward.map((item) => item.id)).toEqual(["s-c", "s-b", "s-a"]);
    expect(backward.map((item) => item.id)).toEqual(["s-c", "s-b", "s-a"]);
  });

  it("sorts unparsable timestamps last in id descending order", () => {
    const sorted = sortSessionsStableRecency([
      session("bad-2", "not-a-date"),
      session("dated", daysAgo(1)),
      session("bad-1", "not-a-date"),
    ]);
    expect(sorted.map((item) => item.id)).toEqual(["dated", "bad-2", "bad-1"]);
  });

  it("does not mutate the input array", () => {
    const loaded = [session("b", daysAgo(1)), session("a", daysAgo(0))];
    sortSessionsStableRecency(loaded);
    expect(loaded.map((item) => item.id)).toEqual(["b", "a"]);
  });

  it("keeps pinned tier order while cache reordering cannot change display order", () => {
    const build = (headInserted: boolean) => {
      const rows = [
        session("pinned-new", daysAgo(0), 500),
        session("pinned-old", daysAgo(1), 900),
        session("u-1", daysAgo(2)),
        session("u-2", daysAgo(3)),
      ];
      const { pinned, unpinned } = splitPinnedSessions(
        headInserted ? [session("u-temp", daysAgo(0)), ...rows] : rows,
      );
      return {
        pinned: pinned.map((item) => item.id),
        unpinned: sortSessionsStableRecency(unpinned).map((item) => item.id),
      };
    };
    expect(build(false)).toEqual({
      pinned: ["pinned-old", "pinned-new"],
      unpinned: ["u-1", "u-2"],
    });
    // A head-inserted row (cache merge order) must not reshuffle the others.
    expect(build(true)).toEqual({
      pinned: ["pinned-old", "pinned-new"],
      unpinned: ["u-temp", "u-1", "u-2"],
    });
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
