import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionSummary } from "../../api/types";
import type { AgentSessionCacheSnapshot, SessionIndexCacheSnapshot } from "../chatSessionIndexQuery";

type RenameSnapshot = {
  previousSessions: SessionSummary[] | undefined;
  previousSessionIndexCaches: SessionIndexCacheSnapshot;
  previousAgentSessionCaches: AgentSessionCacheSnapshot;
  previousDetail: SessionDetail | undefined;
  optimisticUpdatedAt: string;
};

/** Undo only this rename's fields; keep later renames and live conversation data. */
function restoreFields<T extends SessionSummary>(
  current: T | undefined,
  previous: SessionSummary | undefined,
  title: string,
  optimisticUpdatedAt: string,
): T | undefined {
  if (!current || !previous || current.id !== previous.id || current.title !== title) {
    return current;
  }
  return {
    ...current,
    title: previous.title,
    taskTitle: current.taskTitle === title ? previous.taskTitle : current.taskTitle,
    agentDisplayName: current.agentDisplayName === title ? previous.agentDisplayName : current.agentDisplayName,
    updatedAt: current.updatedAt === optimisticUpdatedAt ? previous.updatedAt : current.updatedAt,
  };
}

export function rollbackSessionRename(
  queryClient: QueryClient,
  variables: { sessionId: string; title: string },
  snapshot: RenameSnapshot,
): void {
  const restoreRows = (current: SessionSummary[] | undefined, previous: SessionSummary[] | undefined) => {
    const oldSession = previous?.find((session) => session.id === variables.sessionId);
    return current?.map((session) => session.id === variables.sessionId
      ? restoreFields(session, oldSession, variables.title, snapshot.optimisticUpdatedAt) ?? session
      : session);
  };
  queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (current) =>
    restoreRows(current, snapshot.previousSessions),
  );
  for (const [key, previous] of snapshot.previousSessionIndexCaches) {
    const oldRows = previous?.pages.flatMap((page) => page.items);
    queryClient.setQueryData<NonNullable<typeof previous>>(key, (current) => current ? {
      ...current,
      pages: current.pages.map((page) => ({ ...page, items: restoreRows(page.items, oldRows) ?? page.items })),
    } : current);
  }
  for (const [key, previous] of snapshot.previousAgentSessionCaches) {
    queryClient.setQueryData<NonNullable<typeof previous>>(key, (current) => current ? {
      ...current,
      items: restoreRows(current.items, previous?.items) ?? current.items,
    } : current);
  }
  queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) =>
    restoreFields(current, snapshot.previousDetail, variables.title, snapshot.optimisticUpdatedAt),
  );
}
