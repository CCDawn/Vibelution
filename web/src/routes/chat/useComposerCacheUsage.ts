import { useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSessionUsageSummary } from "../../api/usage";
import { getLauncherAssistantUsageSummary } from "../../api/launcherAssistant";
import { buildComposerCacheUsageModel, type ComposerCacheUsageSnapshot } from "../../components/conversation/composerCacheUsageModel";

export const composerCacheUsageQueryKey = (source: "session" | "assistant", agentId: string, sessionId: string) =>
  ["composer-cache-usage", source, agentId, sessionId] as const;

export function useComposerCacheUsage({
  sessionId, agentId, source, refreshMarker, enabled = true, running = false,
}: {
  sessionId: string;
  agentId: string;
  source: "session" | "assistant";
  refreshMarker: string;
  enabled?: boolean;
  running?: boolean;
}) {
  const client = useQueryClient();
  const active = enabled && Boolean(sessionId && agentId);
  const key = useMemo(() => composerCacheUsageQueryKey(source, agentId, sessionId), [source, agentId, sessionId]);
  const owner = JSON.stringify(key);
  const previous = useRef({ owner, refreshMarker });
  const query = useQuery<ComposerCacheUsageSnapshot>({ queryKey: key, enabled: active, retry: false, staleTime: 0,
    queryFn: async ({ signal }) => {
      if (source === "session") {
        const result = await fetchSessionUsageSummary(sessionId, agentId);
        signal.throwIfAborted();
        return result;
      }
      const result = await getLauncherAssistantUsageSummary();
      signal.throwIfAborted();
      if (result.sessionId !== sessionId || result.agentId !== agentId)
        throw new Error("ASSISTANT_USAGE_IDENTITY_MISMATCH");
      return result;
    },
  });
  useEffect(() => {
    const last = previous.current;
    previous.current = { owner, refreshMarker };
    // The existing detail stream owns call/turn updates; do not add a polling loop.
    if (active && last.owner === owner && last.refreshMarker !== refreshMarker)
      void client.cancelQueries({ queryKey: key, exact: true }).then(() =>
        client.invalidateQueries({ queryKey: key, exact: true }));
  }, [active, client, key, owner, refreshMarker]);
  const model = useMemo(() => buildComposerCacheUsageModel({ snapshot: query.data,
    loading: query.isPending, error: query.isError, updating: running || query.isFetching,
  }), [query.data, query.isPending, query.isError, query.isFetching, running]);
  return active ? model : null;
}
