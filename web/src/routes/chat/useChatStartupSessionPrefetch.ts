import { useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";
import { isTempSessionId } from "../sessionOptimisticIds";
import { fetchSessionDetailWindow, SESSION_DETAIL_PREFETCH_STALE_MS } from "./chatSessionDetailHelpers";
import { readCurrentChatSelectionPreference } from "./useChatSelectionPersistence";

/** Warm the last-viewed body while the directory validates startup selection. */
export function useChatStartupSessionPrefetch({ queryClient, enabled, requestedSessionId }: {
  queryClient: QueryClient;
  enabled: boolean;
  requestedSessionId: string;
}) {
  const [rememberedSessionId] = useState(() => String(readCurrentChatSelectionPreference()?.sessionId || "").trim());
  const allowed = enabled && (!requestedSessionId || requestedSessionId === rememberedSessionId);

  useEffect(() => {
    if (!allowed || !rememberedSessionId || isTempSessionId(rememberedSessionId)
      || isSessionDeleteTombstoned(rememberedSessionId)) return;
    const queryKey = queryKeys.session(rememberedSessionId);
    if (queryClient.getQueryState(queryKey)?.fetchStatus === "fetching") return;
    // This read is speculative: errors must not tombstone rows or navigate.
    // The normal route/catalog owners still validate which session is shown.
    let pending = true;
    void queryClient.prefetchQuery({
      queryKey,
      queryFn: ({ signal }) => fetchSessionDetailWindow(rememberedSessionId, { signal, includeSecondary: false }),
      staleTime: SESSION_DETAIL_PREFETCH_STALE_MS,
    }).finally(() => { pending = false; });
    return () => {
      const query = queryClient.getQueryCache().find({ queryKey, exact: true });
      if (pending && query?.state.fetchStatus === "fetching" && query.getObserversCount() === 0) {
        void queryClient.cancelQueries({ queryKey, exact: true });
      }
    };
  }, [allowed, queryClient, rememberedSessionId]);
  return allowed && rememberedSessionId && !isTempSessionId(rememberedSessionId)
    && !isSessionDeleteTombstoned(rememberedSessionId) ? rememberedSessionId : "";
}
