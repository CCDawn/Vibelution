import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { AgentInstance, SessionDetail, SessionQueryResponse, SessionSummary } from "../api/types";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  evictUnopenableSessionFromCaches,
  reconcileAgentSessionDetailCache,
  removeSessionFromAgentSessionCaches,
  renameAgentDirectoryEntries,
  restoreAgentSessionCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "./chatSessionIndexQuery";
import { mergeSessionDetailIntoSummaries, renameSessionInSummaries } from "./chatSessionState";
import { pinSessionCreatePreserve, isSessionCreatePreserved, resetSessionCreatePreservesForTests } from "./sessionCreatePreserve";
import { isSessionDeleteTombstoned, resetSessionDeleteTombstonesForTests } from "./sessionDeleteTombstone";

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

function detail(patch: Partial<SessionDetail> = {}): SessionDetail {
  return {
    ...session("session-a", "Alpha"),
    agentId: "agent-a",
    messages: [],
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...patch,
  } as SessionDetail;
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

  it("updates Agent-scoped session caches after a session rename", () => {
    const queryClient = new QueryClient();
    const agentAKey = ["sessions", "agent", "agent-a"] as const;
    const agentBKey = ["sessions", "agent", "agent-b"] as const;
    queryClient.setQueryData(agentAKey, page([session("session-a", "Alpha")]));
    queryClient.setQueryData(agentBKey, page([session("session-b", "Beta")]));

    updateAgentSessionSummaryCaches(queryClient, (sessions) =>
      renameSessionInSummaries(sessions, "session-a", "Renamed Alpha", "2026-06-09T08:05:00"),
    );

    expect(queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.items[0]?.title).toBe("Renamed Alpha");
    expect(queryClient.getQueryData<SessionQueryResponse>(agentBKey)?.items[0]?.title).toBe("Beta");
  });

  it("keeps a just-created session in paginated pages when a server refetch omits it", async () => {
    const { pinSessionCreatePreserve, resetSessionCreatePreservesForTests } = await import("./sessionCreatePreserve");
    resetSessionCreatePreservesForTests();
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.sessions(), [
      session("session-new", "Fresh"),
      session("session-old", "Old"),
    ]);
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([session("session-new", "Fresh"), session("session-old", "Old")], "", 2)],
      pageParams: [""],
    });
    pinSessionCreatePreserve({
      ...session("session-new", "Fresh"),
      agentId: "agent-a",
    });

    updateSessionSummaryCaches(queryClient, (sessions) =>
      (sessions ?? []).filter((item) => item.id !== "session-gone"),
    );
    // Simulate what useSessionIndexQuery returns after a stale server page.
    const { mergePreservedCreatedSessions } = await import("./sessionCreatePreserve");
    const filteredItems = mergePreservedCreatedSessions(
      [session("session-old", "Old")],
      { localItems: [session("session-new", "Fresh"), session("session-old", "Old")] },
    );
    expect(filteredItems.map((item) => item.id)).toEqual(["session-new", "session-old"]);
  });

  it("reconciles an authoritative detail only into its owning Agent session cache", () => {
    const queryClient = new QueryClient();
    const agentAKey = ["sessions", "agent", "agent-a"] as const;
    const agentBKey = ["sessions", "agent", "agent-b"] as const;
    queryClient.setQueryData(agentAKey, page([{
      ...session("session-a", "Alpha"),
      agentId: "agent-a",
      status: "stopping",
      currentPhase: "stopping",
      childStatus: "stopping",
    }]));
    queryClient.setQueryData(agentBKey, page([{
      ...session("session-b", "Beta"),
      agentId: "agent-b",
      status: "running",
      currentPhase: "running",
    }]));

    reconcileAgentSessionDetailCache(queryClient, detail({
      status: "ready",
      currentPhase: "ready",
      childStatus: "ready",
      taskSummary: "本轮已按请求停止。",
    }));

    const reconciled = queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.items[0];
    expect(reconciled).toMatchObject({
      status: "ready",
      currentPhase: "ready",
      childStatus: "ready",
      taskSummary: "本轮已按请求停止。",
    });
    expect(queryClient.getQueryData<SessionQueryResponse>(agentBKey)?.items[0]).toMatchObject({
      status: "running",
      currentPhase: "running",
    });
  });

  it("updates the root Agent directory label without renaming other Agents", () => {
    const agents = [
      { agentId: "agent-a", displayName: "Alpha" },
      { agentId: "agent-b", displayName: "Beta" },
    ] as AgentInstance[];

    expect(renameAgentDirectoryEntries(agents, "agent-a", "Renamed Alpha")).toMatchObject([
      { agentId: "agent-a", displayName: "Renamed Alpha" },
      { agentId: "agent-b", displayName: "Beta" },
    ]);
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

  it("removes a deleted session from Agent tab caches and restores it after failure", () => {
    const queryClient = new QueryClient();
    const agentAKey = ["sessions", "agent", "agent-a"] as const;
    const agentBKey = ["sessions", "agent", "agent-b"] as const;
    queryClient.setQueryData(agentAKey, page([
      session("session-delete", "Delete"),
      session("session-keep", "Keep"),
    ], "", 2));
    queryClient.setQueryData(agentBKey, page([session("session-other", "Other")], "", 1));
    const snapshots = captureAgentSessionCacheSnapshots(queryClient);

    removeSessionFromAgentSessionCaches(queryClient, "session-delete");

    expect(queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.items.map((item) => item.id))
      .toEqual(["session-keep"]);
    expect(queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.totalEstimate).toBe(1);
    expect(queryClient.getQueryData<SessionQueryResponse>(agentBKey)?.items.map((item) => item.id))
      .toEqual(["session-other"]);

    restoreAgentSessionCacheSnapshots(queryClient, snapshots);

    expect(queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.items.map((item) => item.id))
      .toEqual(["session-delete", "session-keep"]);
    expect(queryClient.getQueryData<SessionQueryResponse>(agentAKey)?.totalEstimate).toBe(2);
  });

  it("evicts an unopenable session from list caches without dropping the detail query", () => {
    resetSessionDeleteTombstonesForTests();
    resetSessionCreatePreservesForTests();
    const queryClient = new QueryClient();
    const ghost = session("session-ghost", "Ghost");
    const keep = session("session-keep", "Keep");
    queryClient.setQueryData(queryKeys.sessions(), [ghost, keep]);
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([ghost, keep], "", 2)],
      pageParams: [""],
    });
    queryClient.setQueryData(["sessions", "agent", "agent-a"], page([ghost, keep], "", 2));
    queryClient.setQueryData(queryKeys.session("session-ghost"), detail({ id: "session-ghost" }));
    pinSessionCreatePreserve(ghost);

    evictUnopenableSessionFromCaches(queryClient, "session-ghost");

    expect(queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions())?.map((item) => item.id))
      .toEqual(["session-keep"]);
    expect(queryClient.getQueryData<SessionQueryResponse>(["sessions", "agent", "agent-a"])?.items.map((item) => item.id))
      .toEqual(["session-keep"]);
    expect(queryClient.getQueryData(queryKeys.session("session-ghost"))).toEqual(detail({ id: "session-ghost" }));
    expect(isSessionDeleteTombstoned("session-ghost")).toBe(true);
    expect(isSessionCreatePreserved("session-ghost")).toBe(false);
    resetSessionDeleteTombstonesForTests();
    resetSessionCreatePreservesForTests();
  });
});

describe("chatSessionIndexQuery reference stabilization", () => {
  it("keeps cache values reference-identical when a folded detail changes no summary content", () => {
    const queryClient = new QueryClient();
    const stable = { ...session("session-a", "Alpha"), agentId: "agent-a" };
    const other = session("session-b", "Beta");
    queryClient.setQueryData(queryKeys.sessions(), [stable, other]);
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([stable, other], "", 2)],
      pageParams: [""],
    });
    const flatBefore = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
    const paginatedBefore = queryClient.getQueryData(queryKeys.sessionQuery("", 50));

    // Stream snapshot applies rebuild the target object through
    // mergeSessionDetailIntoSummaries even when nothing visible changed.
    updateSessionSummaryCaches(queryClient, (sessions) =>
      mergeSessionDetailIntoSummaries(sessions, detail({ id: "session-a" })),
    );

    expect(queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions())).toBe(flatBefore);
    expect(queryClient.getQueryData(queryKeys.sessionQuery("", 50))).toBe(paginatedBefore);
  });

  it("rotates only the changed session, its page, and the data container", () => {
    const queryClient = new QueryClient();
    const alpha = session("session-a", "Alpha");
    const beta = session("session-b", "Beta");
    const gamma = session("session-c", "Gamma");
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([alpha], "1", 3), page([beta, gamma], "", 3)],
      pageParams: ["", "1"],
    });
    const before = queryClient.getQueryData<{ pages: SessionQueryResponse[] }>(queryKeys.sessionQuery("", 50));

    updateSessionSummaryCaches(queryClient, (sessions) =>
      (sessions ?? []).map((item) => (item.id === "session-b" ? { ...item, title: "Beta renamed" } : item)),
    );

    const after = queryClient.getQueryData<{ pages: SessionQueryResponse[] }>(queryKeys.sessionQuery("", 50));
    expect(after).toBeTruthy();
    expect(after).not.toBe(before);
    expect(after?.pages[0]).toBe(before?.pages[0]);
    expect(after?.pages[1]).not.toBe(before?.pages[1]);
    expect(after?.pages[0]?.items[0]).toBe(alpha);
    expect(after?.pages[1]?.items[0]).not.toBe(beta);
    expect(after?.pages[1]?.items[0]?.title).toBe("Beta renamed");
    expect(after?.pages[1]?.items[1]).toBe(gamma);
  });

  it("keeps paginated data reference-stable when a refetched payload carries the same content", () => {
    const queryClient = new QueryClient();
    const alpha = session("session-a", "Alpha");
    queryClient.setQueryData(queryKeys.sessionQuery("", 50), {
      pages: [page([alpha], "", 1)],
      pageParams: [""],
    });
    const before = queryClient.getQueryData(queryKeys.sessionQuery("", 50));

    updateSessionSummaryCaches(queryClient, (sessions) => (sessions ?? []).map((item) => ({ ...item })));

    expect(queryClient.getQueryData(queryKeys.sessionQuery("", 50))).toBe(before);
  });

  it("keeps the Agent cache object reference-stable when reconcile folds an equivalent detail", () => {
    const queryClient = new QueryClient();
    const agentKey = ["sessions", "agent", "agent-a"] as const;
    queryClient.setQueryData(agentKey, page([{ ...session("session-a", "Alpha"), agentId: "agent-a" }], "", 1));
    const before = queryClient.getQueryData(agentKey);

    reconcileAgentSessionDetailCache(queryClient, detail({ id: "session-a" }));

    expect(queryClient.getQueryData(agentKey)).toBe(before);
  });

  it("rotates the reconciled Agent cache when the detail changes a summary field", () => {
    const queryClient = new QueryClient();
    const agentKey = ["sessions", "agent", "agent-a"] as const;
    const sibling = session("session-b", "Beta");
    queryClient.setQueryData(agentKey, page([
      { ...session("session-a", "Alpha"), agentId: "agent-a" },
      sibling,
    ], "", 2));
    const before = queryClient.getQueryData<SessionQueryResponse>(agentKey);

    reconcileAgentSessionDetailCache(queryClient, detail({ id: "session-a", taskSummary: "新的摘要" }));

    const after = queryClient.getQueryData<SessionQueryResponse>(agentKey);
    expect(after).not.toBe(before);
    expect(after?.items[0]).not.toBe(before?.items[0]);
    expect(after?.items[0]?.taskSummary).toBe("新的摘要");
    expect(after?.items[1]).toBe(sibling);
  });
});
