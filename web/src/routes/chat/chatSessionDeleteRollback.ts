import type { InfiniteData, QueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentInstance,
  SessionQueryResponse,
  SessionSummary,
} from "../../api/types";
import type {
  AgentSessionCacheSnapshot,
  SessionIndexCacheSnapshot,
} from "../chatSessionIndexQuery";
import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";

type DeleteSnapshot = {
  previousSessions?: SessionSummary[];
  previousSessionIndexCaches?: SessionIndexCacheSnapshot;
  previousAgentSessionCaches?: AgentSessionCacheSnapshot;
  previousAgents?: AgentInstance[];
};

function restoreMissing(
  current: SessionSummary[] | undefined,
  previous: SessionSummary[] | undefined,
  ids: Set<string>,
) {
  const present = new Set((current ?? []).map((item) => item.id));
  const missing = (previous ?? []).filter(
    (item) =>
      ids.has(item.id) &&
      !present.has(item.id) &&
      !isSessionDeleteTombstoned(item.id),
  );
  return missing.length ? [...(current ?? []), ...missing] : current;
}

/** Restore only the failed deletion's membership, preserving newer cache edits. */
export function restoreUndeletedSessionCaches(
  queryClient: QueryClient,
  sessionIds: string[],
  snapshot: DeleteSnapshot | undefined,
) {
  const ids = new Set(sessionIds);
  queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (current) =>
    restoreMissing(current, snapshot?.previousSessions, ids),
  );
  for (const [key, previous] of snapshot?.previousSessionIndexCaches ?? []) {
    if (!previous) continue;
    queryClient.setQueryData<InfiniteData<SessionQueryResponse, string>>(
      key,
      (current) => {
        const baseline = current ?? {
          ...previous,
          pages: previous.pages.map((page) => ({ ...page, items: [], totalEstimate: 0 })),
        };
        const present = baseline.pages.flatMap((page) => page.items);
        const restored = restoreMissing(
          present,
          previous.pages.flatMap((page) => page.items),
          ids,
        );
        if (restored === present || !baseline.pages.length) return current;
        const added = (restored ?? []).slice(present.length);
        return {
          ...baseline,
          pages: baseline.pages.map((page, index) => ({
            ...page,
            items:
              index === baseline.pages.length - 1
                ? [...page.items, ...added]
                : page.items,
            totalEstimate:
              typeof page.totalEstimate === "number"
                ? page.totalEstimate + added.length
                : page.totalEstimate,
          })),
        };
      },
    );
  }
  for (const [key, previous] of snapshot?.previousAgentSessionCaches ?? []) {
    if (!previous) continue;
    queryClient.setQueryData<SessionQueryResponse>(key, (current) => {
      const items = restoreMissing(current?.items, previous.items, ids);
      if (!items || items === current?.items) return current;
      const baseline = current ?? { ...previous, items: [], totalEstimate: 0 };
      return {
        ...baseline,
        items,
        totalEstimate:
          typeof baseline.totalEstimate === "number"
            ? baseline.totalEstimate + items.length - baseline.items.length
            : baseline.totalEstimate,
      };
    });
  }
  queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
    current?.map((agent) => {
      const previous = snapshot?.previousAgents?.find(
        (item) => item.agentId === agent.agentId,
      );
      const sessionId = previous?.directSessionId;
      return sessionId &&
        ids.has(sessionId) &&
        !agent.directSessionId &&
        !isSessionDeleteTombstoned(sessionId)
        ? { ...agent, directSessionId: sessionId }
        : agent;
    }),
  );
}
