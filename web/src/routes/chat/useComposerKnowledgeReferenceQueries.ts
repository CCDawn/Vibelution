import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchKnowledgeOverview, listAgentKnowledgeBases, searchKnowledgeItems } from "../../api/knowledge";
import { queryKeys } from "../../api/queryKeys";

/** Load reference candidates on picker intent or @ input, retaining agent-scoped caches. */
export function useComposerKnowledgeReferenceQueries(agentId: string, draft = "") {
  const [requestedAgentId, setRequestedAgentId] = useState("");
  const enabled = Boolean(agentId) && (requestedAgentId === agentId || draft.includes("@"));
  const agentKnowledgeBasesQuery = useQuery({
    queryKey: ["knowledge", "agent-bases", agentId],
    queryFn: () => listAgentKnowledgeBases<{ knowledgeBases?: Array<{ knowledgeBaseId?: string; name?: string; description?: string }> }>(
      agentId, { actorAgentId: agentId },
    ),
    enabled,
    staleTime: 60_000,
  });
  const agentKnowledgeOverviewQuery = useQuery({
    queryKey: ["knowledge", "overview", agentId],
    queryFn: () => fetchKnowledgeOverview<{ summary?: { itemCount?: number } }>({ agentId }),
    enabled,
    staleTime: 60_000,
  });
  const hasItems = (agentKnowledgeOverviewQuery.data?.summary?.itemCount ?? 0) > 0;
  const agentKnowledgeItemsQuery = useQuery({
    queryKey: queryKeys.knowledgeSearch("", agentId, "", "", "keyword"),
    queryFn: () => searchKnowledgeItems<{ results?: Array<{
      knowledgeItemId?: string; knowledgeBaseId?: string; title?: string; knowledgeBaseName?: string;
    }> }>({ agentId, limit: 20 }),
    enabled: enabled && hasItems,
    staleTime: 60_000,
  });
  const queries = [agentKnowledgeBasesQuery, agentKnowledgeOverviewQuery, ...(hasItems ? [agentKnowledgeItemsQuery] : [])];
  const loading = enabled && queries.some(query => query.isPending);
  const error = enabled && queries.some(query => query.isError);
  const onRequest = useCallback(() => {
    if (!agentId) return;
    setRequestedAgentId(agentId);
    if (agentKnowledgeBasesQuery.isError) void agentKnowledgeBasesQuery.refetch();
    if (agentKnowledgeOverviewQuery.isError) void agentKnowledgeOverviewQuery.refetch();
    if (hasItems && agentKnowledgeItemsQuery.isError) void agentKnowledgeItemsQuery.refetch();
  }, [agentId, hasItems, agentKnowledgeBasesQuery.isError, agentKnowledgeBasesQuery.refetch,
    agentKnowledgeOverviewQuery.isError, agentKnowledgeOverviewQuery.refetch,
    agentKnowledgeItemsQuery.isError, agentKnowledgeItemsQuery.refetch]);
  const knowledgeReferenceState = useMemo(() => ({ loading, error, onRequest }), [loading, error, onRequest]);
  return { agentKnowledgeBasesQuery, agentKnowledgeItemsQuery, knowledgeReferenceState };
}
