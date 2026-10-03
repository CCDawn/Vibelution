export type SessionBootstrapFetchStatus = "fetching" | "paused" | "idle";

type SessionIndexQueryGateInput = {
  hasRouteTarget: boolean;
  hasActiveSession?: boolean;
  bootstrapIsFetched: boolean;
  bootstrapIsError: boolean;
  bootstrapFetchStatus: SessionBootstrapFetchStatus;
  /** Directory store readiness from the bootstrap payload; unknown counts as ready. */
  directoryReady?: boolean;
  /** Bounded fallback: the readiness wait expired, so recover via the normal poll. */
  directoryReadyWaitExpired?: boolean;
};

type ConversationIndexLoadingInput = {
  bootstrapIsLoading: boolean;
  conversationsHasData: boolean;
  conversationsIsLoading: boolean;
  sessionsHasData: boolean;
  sessionsIsLoading: boolean;
  agentsHasData?: boolean;
  agentsIsLoading?: boolean;
  visibleSessionCount?: number;
  /** True while the session index is held back by the directory ready gate. */
  directoryGatePending?: boolean;
};

export function shouldEnableSessionIndexQuery({
  hasRouteTarget,
  hasActiveSession = false,
  bootstrapIsFetched,
  bootstrapIsError,
  bootstrapFetchStatus,
  directoryReady = true,
  directoryReadyWaitExpired = false,
}: SessionIndexQueryGateInput): boolean {
  if (!directoryReady && !directoryReadyWaitExpired) {
    // The backend only serves its startup empty page now; hold the query until
    // the bootstrap payload flips the bit or the bounded fallback expires.
    return false;
  }
  return hasRouteTarget
    || hasActiveSession
    || bootstrapIsFetched
    || bootstrapIsError
    || bootstrapFetchStatus === "idle";
}

export function shouldShowConversationIndexLoading({
  bootstrapIsLoading,
  conversationsHasData,
  conversationsIsLoading,
  sessionsHasData,
  sessionsIsLoading,
  agentsHasData = false,
  agentsIsLoading = false,
  visibleSessionCount = 0,
  directoryGatePending = false,
}: ConversationIndexLoadingInput): boolean {
  if (directoryGatePending) {
    // Without this the held-back index renders as an empty list, which is
    // exactly the startup illusion the ready gate exists to remove.
    return true;
  }
  if (visibleSessionCount > 0 && !agentsHasData) {
    return agentsIsLoading || !conversationsHasData;
  }
  const hasDirectoryData = conversationsHasData || sessionsHasData || agentsHasData;
  return !hasDirectoryData
    && (bootstrapIsLoading || conversationsIsLoading || sessionsIsLoading || agentsIsLoading);
}
