export type SessionBootstrapFetchStatus = "fetching" | "paused" | "idle";

type SessionIndexQueryGateInput = {
  hasRouteTarget: boolean;
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
};

export function shouldEnableSessionIndexQuery({
  hasRouteTarget,
  bootstrapIsFetched,
  bootstrapIsError,
  bootstrapFetchStatus,
}: SessionIndexQueryGateInput): boolean {
  return hasRouteTarget
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
}: ConversationIndexLoadingInput): boolean {
  const hasDirectoryData = conversationsHasData || sessionsHasData;
  return !hasDirectoryData
    && (bootstrapIsLoading || conversationsIsLoading || sessionsIsLoading);
}
