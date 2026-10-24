import { useEffect } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";
import type { ConfigBootstrap } from "../api/types";
import { parseChatRouteSelection } from "../routes/chat/chatSelectionProjection";
import { chatWorkbenchBootstrapQueryOptions } from "../routes/chat/chatWorkbenchBootstrapQuery";
import { useChatStartupSessionPrefetch } from "../routes/chat/useChatStartupSessionPrefetch";
import { readCurrentChatSelectionPreference } from "../routes/chat/useChatSelectionPersistence";
import { isWorkbenchModeEnabled } from "./workbenchContract";

/** Overlap native Chat reads with the lazy route chunk without selecting a session. */
export function useChatStartupPrefetch({ queryClient, pathname, search }: {
  queryClient: QueryClient;
  pathname: string;
  search: string;
}) {
  const selection = parseChatRouteSelection(search);
  // Native startup opens `/`. HomeRedirect validates config before restoring
  // Chat, so warm its remembered reads during that wait without selecting it.
  const restore = pathname === "/" ? readCurrentChatSelectionPreference() : null;
  const config = queryClient.getQueryData<ConfigBootstrap>(queryKeys.configPublic());
  const restoringChat = pathname === "/" && selection.kind === "bare"
    && Boolean(restore?.agentId || restore?.sessionId) && isWorkbenchModeEnabled(config, "chat");
  const enabled = restoringChat
    || (pathname === "/chat" && (selection.kind === "bare" || selection.kind === "session"));
  useChatStartupSessionPrefetch({
    queryClient,
    enabled,
    requestedSessionId: selection.kind === "session" ? selection.sessionId : "",
  });

  useEffect(() => {
    if (!enabled) return;
    const options = chatWorkbenchBootstrapQueryOptions(queryClient);
    if (queryClient.getQueryState(options.queryKey)?.fetchStatus === "fetching") return;
    let pending = true;
    void queryClient.prefetchQuery(options).finally(() => { pending = false; });
    return () => {
      const query = queryClient.getQueryCache().find({ queryKey: options.queryKey, exact: true });
      // Only release this shell's orphaned speculative read. A mounted route
      // owns its observer and must keep the shared in-flight request alive.
      if (pending && query?.state.fetchStatus === "fetching" && query.getObserversCount() === 0) {
        void queryClient.cancelQueries({ queryKey: options.queryKey, exact: true });
      }
    };
  }, [enabled, queryClient]);
}
