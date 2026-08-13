export type SessionBootstrapFetchStatus = "fetching" | "paused" | "idle";

type SessionIndexQueryGateInput = {
  hasRouteTarget: boolean;
  hasActiveSession?: boolean;
  bootstrapIsFetched: boolean;
  bootstrapIsError: boolean;
  bootstrapFetchStatus: SessionBootstrapFetchStatus;
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
};

export function shouldEnableSessionIndexQuery({
  hasRouteTarget,
  hasActiveSession = false,
  bootstrapIsFetched,
  bootstrapIsError,
  bootstrapFetchStatus,
}: SessionIndexQueryGateInput): boolean {
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
}: ConversationIndexLoadingInput): boolean {
  if (visibleSessionCount > 0 && !agentsHasData) {
    return agentsIsLoading || !conversationsHasData;
  }
  const hasDirectoryData = conversationsHasData || sessionsHasData || agentsHasData;
  return !hasDirectoryData
    && (bootstrapIsLoading || conversationsIsLoading || sessionsIsLoading || agentsIsLoading);
}
