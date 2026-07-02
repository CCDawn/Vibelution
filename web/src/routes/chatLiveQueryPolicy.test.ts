import { describe, expect, it } from "vitest";

import {
  ACTIVE_BACKGROUND_SYNC_POLL_MS,
  ACTIVE_INDEX_POLL_MS,
  ACTIVE_SESSION_DETAIL_POLL_MS,
  resolveChatLiveQueryPolicy,
} from "./chatLiveQueryPolicy";

const baseInput = {
  chatPollingVisible: true,
  chatStartupWarmupActive: false,
  directSessionBackgroundSyncActive: false,
  groupBackgroundSyncActive: false,
  directSessionPanelActive: true,
  legacyGroupRoomActive: false,
  sessionStreamAvailable: true,
  sessionStreamShouldConnect: true,
  groupStreamShouldConnect: false,
  activeSessionId: "session-live",
  activeRootSessionId: "session-live",
};

describe("resolveChatLiveQueryPolicy", () => {
  it("lets the direct session stream own live direct-session queries", () => {
    const policy = resolveChatLiveQueryPolicy(baseInput);

    expect(policy.directSessionStreamOwnsLiveQueries).toBe(true);
    expect(policy.groupStreamOwnsLiveQueries).toBe(false);
    expect(policy.sessionsRefetchInterval).toBe(false);
    expect(policy.conversationsRefetchInterval).toBe(false);
    expect(policy.sessionDetailRefetchInterval).toBe(false);
    expect(policy.childSessionsRefetchInterval).toBe(false);
  });

  it("falls back to foreground polling when direct stream cannot own the query", () => {
    const policy = resolveChatLiveQueryPolicy({
      ...baseInput,
      sessionStreamAvailable: false,
      sessionStreamShouldConnect: false,
    });

    expect(policy.directSessionStreamOwnsLiveQueries).toBe(false);
    expect(policy.sessionsRefetchInterval).toBe(ACTIVE_INDEX_POLL_MS);
    expect(policy.conversationsRefetchInterval).toBe(ACTIVE_INDEX_POLL_MS);
    expect(policy.sessionDetailRefetchInterval).toBe(ACTIVE_SESSION_DETAIL_POLL_MS);
    expect(policy.childSessionsRefetchInterval).toBe(ACTIVE_INDEX_POLL_MS);
  });

  it("uses background sync intervals when the page is hidden and no stream owns the query", () => {
    const policy = resolveChatLiveQueryPolicy({
      ...baseInput,
      chatPollingVisible: false,
      sessionStreamAvailable: false,
      sessionStreamShouldConnect: false,
      directSessionBackgroundSyncActive: true,
    });

    expect(policy.sessionsRefetchInterval).toBe(ACTIVE_BACKGROUND_SYNC_POLL_MS);
    expect(policy.conversationsRefetchInterval).toBe(ACTIVE_BACKGROUND_SYNC_POLL_MS);
    expect(policy.sessionDetailRefetchInterval).toBe(ACTIVE_BACKGROUND_SYNC_POLL_MS);
    expect(policy.childSessionsRefetchInterval).toBe(ACTIVE_BACKGROUND_SYNC_POLL_MS);
    expect(policy.directRefetchIntervalInBackground).toBe(true);
  });

  it("lets group streams suppress the shared conversation index without suppressing direct sessions", () => {
    const policy = resolveChatLiveQueryPolicy({
      ...baseInput,
      directSessionPanelActive: false,
      legacyGroupRoomActive: true,
      sessionStreamShouldConnect: false,
      groupStreamShouldConnect: true,
    });

    expect(policy.directSessionStreamOwnsLiveQueries).toBe(false);
    expect(policy.groupStreamOwnsLiveQueries).toBe(true);
    expect(policy.sessionsRefetchInterval).toBe(ACTIVE_INDEX_POLL_MS);
    expect(policy.conversationsRefetchInterval).toBe(false);
    expect(policy.sessionDetailRefetchInterval).toBe(ACTIVE_SESSION_DETAIL_POLL_MS);
  });
});
