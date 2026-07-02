import { resolvePollingInterval, type PollingInterval } from "../app/pollingPolicy";

export const ACTIVE_INDEX_POLL_MS = 3_000;
export const ACTIVE_BACKGROUND_SYNC_POLL_MS = 5_000;
export const ACTIVE_SESSION_DETAIL_POLL_MS = 3_000;

export type ChatLiveQueryPolicyInput = {
  chatPollingVisible: boolean;
  chatStartupWarmupActive: boolean;
  directSessionBackgroundSyncActive: boolean;
  groupBackgroundSyncActive: boolean;
  directSessionPanelActive: boolean;
  legacyGroupRoomActive: boolean;
  sessionStreamAvailable: boolean;
  sessionStreamShouldConnect: boolean;
  groupStreamShouldConnect: boolean;
  activeSessionId: string;
  activeRootSessionId: string;
};

export type ChatLiveQueryPolicy = {
  directSessionStreamOwnsLiveQueries: boolean;
  groupStreamOwnsLiveQueries: boolean;
  sessionsRefetchInterval: PollingInterval;
  conversationsRefetchInterval: PollingInterval;
  sessionDetailRefetchInterval: PollingInterval;
  childSessionsRefetchInterval: PollingInterval;
  directRefetchIntervalInBackground: boolean;
  sharedRefetchIntervalInBackground: boolean;
};

export function resolveChatLiveQueryPolicy(input: ChatLiveQueryPolicyInput): ChatLiveQueryPolicy {
  const directSessionStreamOwnsLiveQueries = Boolean(
    input.sessionStreamAvailable
    && input.sessionStreamShouldConnect
    && input.directSessionPanelActive,
  );
  const groupStreamOwnsLiveQueries = Boolean(
    input.sessionStreamAvailable
    && input.groupStreamShouldConnect
    && input.legacyGroupRoomActive,
  );
  const directBackgroundMs =
    input.directSessionBackgroundSyncActive && !directSessionStreamOwnsLiveQueries
      ? ACTIVE_BACKGROUND_SYNC_POLL_MS
      : false;
  const groupBackgroundMs =
    input.groupBackgroundSyncActive && !groupStreamOwnsLiveQueries
      ? ACTIVE_BACKGROUND_SYNC_POLL_MS
      : false;
  const sharedBackgroundMs = directBackgroundMs || groupBackgroundMs ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false;

  return {
    directSessionStreamOwnsLiveQueries,
    groupStreamOwnsLiveQueries,
    sessionsRefetchInterval: resolvePollingInterval(
      input.chatPollingVisible,
      directSessionStreamOwnsLiveQueries ? false : ACTIVE_INDEX_POLL_MS,
      { backgroundMs: directBackgroundMs },
    ),
    conversationsRefetchInterval: resolvePollingInterval(
      input.chatPollingVisible,
      directSessionStreamOwnsLiveQueries || groupStreamOwnsLiveQueries ? false : ACTIVE_INDEX_POLL_MS,
      { backgroundMs: sharedBackgroundMs },
    ),
    sessionDetailRefetchInterval: input.activeSessionId
      ? resolvePollingInterval(
          input.chatPollingVisible,
          directSessionStreamOwnsLiveQueries ? false : ACTIVE_SESSION_DETAIL_POLL_MS,
          { backgroundMs: directBackgroundMs },
        )
      : false,
    childSessionsRefetchInterval: input.activeRootSessionId
      ? resolvePollingInterval(
          input.chatPollingVisible,
          directSessionStreamOwnsLiveQueries ? false : ACTIVE_INDEX_POLL_MS,
          { backgroundMs: directBackgroundMs },
        )
      : false,
    directRefetchIntervalInBackground: input.chatStartupWarmupActive || input.directSessionBackgroundSyncActive,
    sharedRefetchIntervalInBackground:
      input.chatStartupWarmupActive || input.directSessionBackgroundSyncActive || input.groupBackgroundSyncActive,
  };
}
