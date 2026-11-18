import { resolvePollingInterval, type PollingInterval } from "../app/pollingPolicy";

export const ACTIVE_INDEX_POLL_MS = 3_000;
export const ACTIVE_BACKGROUND_SYNC_POLL_MS = 5_000;
export const ACTIVE_SESSION_DETAIL_POLL_MS = 3_000;
/**
 * Group-room catalog poll (GET /api/conversations?type=group_room, limit 100).
 * Measured ~34 ms / ~16 KB per page against a 144-item index — the catalog no
 * longer pulls the direct-session half (covered by the session index query),
 * so the poll cadence relaxes from the 3s index beat to 15s without hurting
 * rail freshness; room create/archive paths still invalidate immediately.
 */
export const CONVERSATIONS_CATALOG_POLL_MS = 15_000;

export type ChatLiveQueryPolicyInput = {
  chatPollingVisible: boolean;
  chatStartupWarmupActive: boolean;
  directSessionBackgroundSyncActive: boolean;
  groupBackgroundSyncActive: boolean;
  directSessionPanelActive: boolean;
  standardGroupRoomActive: boolean;
  sessionStreamAvailable: boolean;
  sessionStreamShouldConnect: boolean;
  /** True only after EventSource onopen for the active direct session. */
  sessionStreamConnected: boolean;
  /**
   * True only after the global session-index rail stream opened. That stream is
   * the only carrier for every session's row, so the index query may stop
   * polling only while it is really open. Absent means "assume open" so older
   * callers keep their previous behaviour.
   */
  sessionIndexStreamConnected?: boolean;
  groupStreamShouldConnect: boolean;
  /** True only after EventSource onopen for the active group room. */
  groupStreamConnected: boolean;
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

/**
 * Stream owns live queries only when we intend to connect AND the socket is open.
 * Intent-only ownership left a gap when EventSource failed silently and polling stayed off.
 */
export function resolveChatLiveQueryPolicy(input: ChatLiveQueryPolicyInput): ChatLiveQueryPolicy {
  const directSessionStreamOwnsLiveQueries = Boolean(
    input.sessionStreamAvailable
    && input.sessionStreamShouldConnect
    && input.sessionStreamConnected
    && input.directSessionPanelActive,
  );
  // The detail stream only covers the session it streams; the rail's global
  // index stream is what carries every other row. Without it a background
  // turn's settle never reaches the list, so polling has to stay on.
  const sessionIndexRailOwnsIndexQuery =
    directSessionStreamOwnsLiveQueries && input.sessionIndexStreamConnected !== false;
  const groupStreamOwnsLiveQueries = Boolean(
    input.sessionStreamAvailable
    && input.groupStreamShouldConnect
    && input.groupStreamConnected
    && input.standardGroupRoomActive,
  );
  const directBackgroundMs =
    input.directSessionBackgroundSyncActive && !sessionIndexRailOwnsIndexQuery
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
      sessionIndexRailOwnsIndexQuery ? false : ACTIVE_INDEX_POLL_MS,
      { backgroundMs: directBackgroundMs },
    ),
    conversationsRefetchInterval: resolvePollingInterval(
      input.chatPollingVisible,
      directSessionStreamOwnsLiveQueries || groupStreamOwnsLiveQueries ? false : CONVERSATIONS_CATALOG_POLL_MS,
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
