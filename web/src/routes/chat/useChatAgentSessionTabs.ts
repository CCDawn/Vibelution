import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { querySessions } from "../../api/chat";
import type { AgentInstance, SessionQueryResponse, SessionSummary } from "../../api/types";
import { isRepresentedInAgentSessionTabs } from "../conversationIndexModel";
import { mergePreservedCreatedSessions } from "../sessionCreatePreserve";
import { filterOutTombstonedSessions } from "../sessionDeleteTombstone";
import { markSessionActivitySnapshotsSeen } from "../sessionActivityIndicator";
import { recoveredSessionSummariesForAgent } from "./chatSessionCreateRecovery";
import { buildAgentSessionTabs } from "./chatSessionSurfaceModel";

export function mergeAgentSessionTabSources(
  agentItems: readonly SessionSummary[] | null | undefined,
  visibleItems: readonly SessionSummary[],
  recoveredItems: readonly SessionSummary[],
): SessionSummary[] {
  return filterOutTombstonedSessions([
    ...recoveredItems,
    ...(agentItems ?? []),
    ...visibleItems,
  ]) ?? [];
}

export type UseChatAgentSessionTabsInput = {
  queryClient: ReturnType<typeof useQueryClient>;
  selectedChatAgentId: string;
  agentsById: Map<string, AgentInstance>;
  allVisibleSessions: readonly SessionSummary[];
  activeSessionId: string | null;
  secondaryChatDataEnabled: boolean;
  sessionsRefetchInterval: number | false;
  directRefetchIntervalInBackground: boolean;
};

export type UseChatAgentSessionTabsResult = {
  rightIndexSessions: SessionSummary[];
  agentSessionTabs: SessionSummary[];
};

export function useChatAgentSessionTabs({
  queryClient,
  selectedChatAgentId,
  agentsById,
  allVisibleSessions,
  activeSessionId,
  secondaryChatDataEnabled,
  sessionsRefetchInterval,
  directRefetchIntervalInBackground,
}: UseChatAgentSessionTabsInput): UseChatAgentSessionTabsResult {
  const [, setSessionActivitySeenEpoch] = useState(0);

  const selectedAgentSessionsQuery = useQuery({
    queryKey: ["sessions", "agent", selectedChatAgentId],
    queryFn: async () => {
      const payload = await querySessions({
        agentId: selectedChatAgentId,
        limit: 100,
      });
      const previous = queryClient.getQueryData<SessionQueryResponse>([
        "sessions",
        "agent",
        selectedChatAgentId,
      ]);
      const items = mergePreservedCreatedSessions(payload.items ?? [], {
        localItems: previous?.items ?? [],
      }).filter((session) => String(session.agentId || "").trim() === selectedChatAgentId);
      return {
        ...payload,
        items,
        totalEstimate:
          typeof payload.totalEstimate === "number"
            ? Math.max(payload.totalEstimate, items.length)
            : items.length,
      };
    },
    enabled: secondaryChatDataEnabled && Boolean(selectedChatAgentId),
    refetchInterval: sessionsRefetchInterval,
    refetchIntervalInBackground: directRefetchIntervalInBackground,
  });

  const rightIndexSessions = useMemo(
    () => allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session)),
    [allVisibleSessions],
  );

  const selectedAgentVisibleSessions = useMemo(
    () => allVisibleSessions.filter(
      (session) => String(session.agentId || "").trim() === selectedChatAgentId,
    ),
    [allVisibleSessions, selectedChatAgentId],
  );

  const recoveredTempKey = recoveredSessionSummariesForAgent(selectedChatAgentId)
    .map((session) => `${session.id}\n${session.title}`)
    .join("\n");
  const agentSessionTabs = useMemo(
    () => buildAgentSessionTabs({
      sessions: mergeAgentSessionTabSources(
        selectedAgentSessionsQuery.data?.items,
        selectedAgentVisibleSessions,
        recoveredSessionSummariesForAgent(selectedChatAgentId),
      ),
      selectedChatAgentDirectSessionId: agentsById.get(selectedChatAgentId)?.directSessionId,
    }),
    [agentsById, recoveredTempKey, selectedAgentSessionsQuery.data?.items, selectedAgentVisibleSessions, selectedChatAgentId],
  );

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const tabSession = agentSessionTabs.find((session) => session.id === activeSessionId);
    if (markSessionActivitySnapshotsSeen(activeSessionId, [tabSession])) {
      setSessionActivitySeenEpoch((current) => current + 1);
    }
  }, [activeSessionId, agentSessionTabs]);

  return {
    rightIndexSessions,
    agentSessionTabs,
  };
}
