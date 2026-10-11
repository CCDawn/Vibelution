import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentInstance,
  SessionQueryResponse,
  SessionSummary,
} from "../../api/types";
import {
  markSessionDeleteTombstone,
  resetSessionDeleteTombstonesForTests,
} from "../sessionDeleteTombstone";
import { restoreUndeletedSessionCaches } from "./chatSessionDeleteRollback";

const row = (id: string, title = id) =>
  ({ id, title, agentId: "agent" }) as SessionSummary;
const page = (items: SessionSummary[]) =>
  ({ items, totalEstimate: items.length }) as SessionQueryResponse;
afterEach(resetSessionDeleteTombstonesForTests);

describe("session delete rollback", () => {
  it("restores failed membership in paged caches without undoing newer rows or direct bindings", () => {
    const client = new QueryClient();
    const indexKey = ["sessions", "query", "test"];
    const agentKey = ["sessions", "agent", "agent"];
    const previous = [row("failed"), row("deleted"), row("changed", "old")];
    client.setQueryData(indexKey, {
      pages: [page([row("changed", "new"), row("new")])],
      pageParams: [""],
    });
    client.setQueryData(agentKey, page([row("changed", "new"), row("new")]));
    client.setQueryData(queryKeys.agents(), [
      { agentId: "agent", directSessionId: "new", displayName: "new name" },
    ]);
    markSessionDeleteTombstone("deleted");

    restoreUndeletedSessionCaches(client, ["failed", "deleted"], {
      previousSessions: previous,
      previousSessionIndexCaches: [
        [indexKey, { pages: [page(previous)], pageParams: [""] }],
      ],
      previousAgentSessionCaches: [[agentKey, page(previous)]],
      previousAgents: [
        {
          agentId: "agent",
          directSessionId: "failed",
          displayName: "old name",
        } as AgentInstance,
      ],
    });

    const restored = client.getQueryData<{ pages: SessionQueryResponse[] }>(
      indexKey,
    )!;
    expect(
      restored.pages[0].items.map((item) => [item.id, item.title]),
    ).toEqual([
      ["changed", "new"],
      ["new", "new"],
      ["failed", "failed"],
    ]);
    expect(restored.pages[0].totalEstimate).toBe(3);
    expect(client.getQueryData<SessionQueryResponse>(agentKey)?.items).toEqual(
      restored.pages[0].items,
    );
    expect(
      client.getQueryData<AgentInstance[]>(queryKeys.agents())?.[0],
    ).toMatchObject({ directSessionId: "new", displayName: "new name" });
    client.clear();
  });

  it("keeps newer detail-derived summaries for the restored session", () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.sessions(), [row("failed", "fresh")]);
    restoreUndeletedSessionCaches(client, ["failed"], {
      previousSessions: [row("failed", "stale")],
    });
    expect(
      client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.[0].title,
    ).toBe("fresh");
    client.clear();
  });
});
