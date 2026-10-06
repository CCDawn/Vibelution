import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionQueryResponse, SessionSummary } from "../../api/types";
import { captureAgentSessionCacheSnapshots, captureSessionIndexCacheSnapshots } from "../chatSessionIndexQuery";
import { renameSessionDetail, renameSessionInSummaries } from "../chatSessionState";
import { rollbackSessionRename } from "./chatSessionRenameRollback";

const oldTime = "2026-10-07T00:00:00Z";
const optimisticTime = "2026-10-07T00:01:00Z";
const laterTime = "2026-10-07T00:02:00Z";
const indexKey = queryKeys.sessionQuery("", 50);
const agentKey = ["sessions", "agent", "agent-a"];

function session(id: string, title: string): SessionSummary {
  return { id, title, status: "ready", taskSummary: "", lastActive: oldTime, updatedAt: oldTime, currentPhase: "ready" };
}

function arrange() {
  const client = new QueryClient();
  const rows = [session("a", "Alpha"), session("b", "Beta")];
  const page: SessionQueryResponse = {
    items: rows, nextCursor: "", totalEstimate: 2,
    filters: { q: "", agentId: "", sessionKind: "", state: "", sort: "updatedAt_desc", limit: 50, cursor: "" },
  };
  const detail = { ...rows[0], messages: [], defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [] } as SessionDetail;
  client.setQueryData(queryKeys.sessions(), rows);
  client.setQueryData(indexKey, { pages: [page], pageParams: [""] });
  client.setQueryData(agentKey, page);
  client.setQueryData(queryKeys.session("a"), detail);
  const snapshot = {
    previousSessions: rows,
    previousSessionIndexCaches: captureSessionIndexCacheSnapshots(client),
    previousAgentSessionCaches: captureAgentSessionCacheSnapshots(client),
    previousDetail: detail,
    optimisticUpdatedAt: optimisticTime,
  };
  return { client, rows, page, detail, snapshot };
}

describe("rollbackSessionRename", () => {
  it("restores A's title across caches without losing B's confirmed rename, new rows or live detail", () => {
    const { client, rows, page, detail, snapshot } = arrange();
    const optimistic = renameSessionInSummaries(rows, "a", "Attempt A", optimisticTime)!;
    const confirmedB = { ...rows[1], title: "Confirmed B", updatedAt: laterTime };
    const newRow = session("c", "Created while saving");
    const currentRows = [{ ...optimistic[0], currentPhase: "running", updatedAt: laterTime }, confirmedB, newRow];
    const liveMessages = [{ id: "live", role: "user", content: "new message", timestamp: laterTime }];
    const liveDetail = { ...renameSessionDetail(detail, "a", "Attempt A", optimisticTime), messages: liveMessages, updatedAt: laterTime };
    client.setQueryData(queryKeys.sessions(), currentRows);
    client.setQueryData(indexKey, { pages: [{ ...page, items: currentRows, totalEstimate: 3 }], pageParams: ["new cursor"] });
    client.setQueryData(agentKey, { ...page, items: currentRows, totalEstimate: 3 });
    client.setQueryData(queryKeys.session("a"), liveDetail);

    rollbackSessionRename(client, { sessionId: "a", title: "Attempt A" }, snapshot);

    const expected = [{ ...currentRows[0], title: "Alpha" }, confirmedB, newRow];
    expect(client.getQueryData(queryKeys.sessions())).toEqual(expected);
    expect(client.getQueryData(indexKey)).toEqual({ pages: [{ ...page, items: expected, totalEstimate: 3 }], pageParams: ["new cursor"] });
    expect(client.getQueryData(agentKey)).toEqual({ ...page, items: expected, totalEstimate: 3 });
    expect(client.getQueryData(queryKeys.session("a"))).toEqual({ ...liveDetail, title: "Alpha" });
    client.clear();
  });

  it("does not overwrite a newer successful title on the same session", () => {
    const { client, rows, snapshot } = arrange();
    const newer = { ...rows[0], title: "Newer confirmed title", updatedAt: laterTime };
    client.setQueryData(queryKeys.sessions(), [newer, rows[1]]);
    rollbackSessionRename(client, { sessionId: "a", title: "Earlier attempt" }, snapshot);
    expect(client.getQueryData(queryKeys.sessions())).toEqual([newer, rows[1]]);
    client.clear();
  });

  it("restores optimistic child task fields and timestamp without resurrecting a removed row", () => {
    const { client, rows, snapshot } = arrange();
    snapshot.previousSessions = [{ ...rows[0], sessionKind: "child", taskTitle: "Original task" }, rows[1]];
    const renamed = renameSessionInSummaries(snapshot.previousSessions, "a", "Attempt", optimisticTime)!;
    client.setQueryData(queryKeys.sessions(), renamed);
    rollbackSessionRename(client, { sessionId: "a", title: "Attempt" }, snapshot);
    expect(client.getQueryData(queryKeys.sessions())).toEqual(snapshot.previousSessions);
    client.setQueryData(queryKeys.sessions(), [rows[1]]);
    rollbackSessionRename(client, { sessionId: "a", title: "Attempt" }, snapshot);
    expect(client.getQueryData(queryKeys.sessions())).toEqual([rows[1]]);
    client.clear();
  });
});
