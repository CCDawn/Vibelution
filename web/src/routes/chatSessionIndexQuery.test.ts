import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { SessionQueryResponse, SessionSummary } from "../api/types";
import {
  captureSessionIndexCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateSessionSummaryCaches,
} from "./chatSessionIndexQuery";
import { renameSessionInSummaries } from "./chatSessionState";

function session(id: string, title: string): SessionSummary {
  return {
    id,
    title,
    status: "ready",
    taskSummary: "summary",
    lastActive: "2026-06-09T08:00:00",
    updatedAt: "2026-06-09T08:00:00",
    currentPhase: "ready",
  };
}

function page(items: SessionSummary[], nextCursor = "", totalEstimate = items.length): SessionQueryResponse {
  return {
    items,
    nextCursor,
    totalEstimate,
    filters: {
      q: "",
      agentId: "",
      sessionKind: "",
      state: "",
      sort: "updatedAt_desc",
      limit: 50,
      cursor: "",
    },
  };
}

describe("chatSessionIndexQuery cache helpers", () => {
  it("updates legacy and paginated session caches together", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.sessions(), [session("session-a", "Alpha"), session("session-b", "Beta")]);
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([session("session-a", "Alpha")], "1", 2), page([session("session-b", "Beta")], "", 2)],
      pageParams: ["", "1"],
    });

    updateSessionSummaryCaches(queryClient, (sessions) =>
      renameSessionInSummaries(sessions, "session-b", "Renamed Beta", "2026-06-09T08:05:00"),
    );

    expect(queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions())?.find((item) => item.id === "session-b")?.title)
      .toBe("Renamed Beta");
    const paginated = queryClient.getQueryData<{ pages: SessionQueryResponse[] }>(queryKeys.sessionQuery("", 50));
    expect(paginated?.pages.flatMap((item) => item.items).find((item) => item.id === "session-b")?.title).toBe("Renamed Beta");
  });

  it("restores paginated session caches after optimistic failures", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([session("session-a", "Alpha")])],
      pageParams: [""],
    });
    const snapshots = captureSessionIndexCacheSnapshots(queryClient);

    updateSessionSummaryCaches(queryClient, (sessions) =>
      renameSessionInSummaries(sessions, "session-a", "Temporary", "2026-06-09T08:05:00"),
    );
    restoreSessionIndexCacheSnapshots(queryClient, snapshots);

    const paginated = queryClient.getQueryData<{ pages: SessionQueryResponse[] }>(queryKeys.sessionQuery("", 50));
    expect(paginated?.pages[0]?.items[0]?.title).toBe("Alpha");
  });
});
