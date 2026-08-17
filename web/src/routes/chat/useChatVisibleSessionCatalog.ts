import { useEffect, useMemo, useState } from "react";

import type { AgentInstance, SessionDetail, SessionSummary } from "../../api/types";
import { visibleDirectoryAgents } from "../AgentConversationDirectory";
import { markSessionActivitySnapshotsSeen } from "../sessionActivityIndicator";
import {
  buildSessionsById,
  mergeAllVisibleSessions,
  resolveActiveSessionAgentId,
  resolveActivitySeenSessionSources,
} from "./chatVisibleSessionCatalogModel";

export type UseChatVisibleSessionCatalogInput = {
  sessions: SessionSummary[] | undefined;
  childSessions: SessionSummary[] | undefined;
  pendingArchiveAgentIds: ReadonlySet<string>;
  archiveVisibleAgents: readonly AgentInstance[];
  activeSessionId: string | null;
  detail: SessionDetail | undefined;
  directSessionActiveSummary: SessionSummary | undefined;
  sessionDetailAgentId: string | undefined;
};

export type UseChatVisibleSessionCatalogResult = {
  allVisibleSessions: SessionSummary[];
  sessionsById: Map<string, SessionSummary>;
  visibleChatAgents: AgentInstance[];
  activeSessionAgentId: string;
};

export function useChatVisibleSessionCatalog({
  sessions,
  childSessions,
  pendingArchiveAgentIds,
  archiveVisibleAgents,
  activeSessionId,
  detail,
  directSessionActiveSummary,
  sessionDetailAgentId,
}: UseChatVisibleSessionCatalogInput): UseChatVisibleSessionCatalogResult {
  const [, setSessionActivitySeenEpoch] = useState(0);

  const allVisibleSessions = useMemo(
    () => mergeAllVisibleSessions(sessions, childSessions, pendingArchiveAgentIds),
    [childSessions, pendingArchiveAgentIds, sessions],
  );

  const sessionsById = useMemo(
    () => buildSessionsById(allVisibleSessions),
    [allVisibleSessions],
  );

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const wrote = markSessionActivitySnapshotsSeen(
      activeSessionId,
      resolveActivitySeenSessionSources(
        activeSessionId,
        sessionsById,
        detail,
        directSessionActiveSummary,
      ),
    );
    if (wrote) {
      setSessionActivitySeenEpoch((current) => current + 1);
    }
  }, [
    activeSessionId,
    detail,
    directSessionActiveSummary,
    sessionsById,
  ]);

  const visibleChatAgents = useMemo(
    () => visibleDirectoryAgents([...archiveVisibleAgents], allVisibleSessions),
    [allVisibleSessions, archiveVisibleAgents],
  );

  const activeSessionAgentId = useMemo(
    () => resolveActiveSessionAgentId({
      sessionDetailAgentId,
      directSessionActiveSummary,
      activeSessionId,
      sessionsById,
    }),
    [activeSessionId, directSessionActiveSummary, sessionDetailAgentId, sessionsById],
  );

  return {
    allVisibleSessions,
    sessionsById,
    visibleChatAgents,
    activeSessionAgentId,
  };
}
