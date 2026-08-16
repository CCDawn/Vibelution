import { useEffect, useMemo, useState } from "react";

import type { AgentInstance, SessionDetail, SessionSummary } from "../../api/types";
import { visibleDirectoryAgents } from "../AgentConversationDirectory";
import { isVisibleDirectSession } from "../conversationIndexModel";
import { markSessionActivitySnapshotsSeen } from "../sessionActivityIndicator";

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

  const allVisibleSessions = useMemo(() => {
    const merged = [...(sessions ?? []), ...(childSessions ?? [])];
    return merged
      .filter(isVisibleDirectSession)
      .filter((session) => !pendingArchiveAgentIds.has(String(session.agentId || "").trim()))
      .filter((session, index, items) => items.findIndex((item) => item.id === session.id) === index);
  }, [childSessions, pendingArchiveAgentIds, sessions]);

  const sessionsById = useMemo(
    () => new Map(allVisibleSessions.map((session) => [session.id, session])),
    [allVisibleSessions],
  );

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const directorySession = sessionsById.get(activeSessionId);
    const detailSession = detail?.id === activeSessionId ? detail : undefined;
    const wrote = markSessionActivitySnapshotsSeen(activeSessionId, [
      directorySession,
      directSessionActiveSummary?.id === activeSessionId ? directSessionActiveSummary : undefined,
      detailSession,
    ]);
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
    () => String(
      sessionDetailAgentId
      || directSessionActiveSummary?.agentId
      || sessionsById.get(activeSessionId || "")?.agentId
      || "",
    ).trim(),
    [activeSessionId, directSessionActiveSummary?.agentId, sessionDetailAgentId, sessionsById],
  );

  return {
    allVisibleSessions,
    sessionsById,
    visibleChatAgents,
    activeSessionAgentId,
  };
}
