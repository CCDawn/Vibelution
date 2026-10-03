import { describe, expect, it } from "vitest";

import {
  shouldEnableSessionIndexQuery,
  shouldShowConversationIndexLoading,
} from "./chatSessionStartupGate";

describe("chat session startup gate", () => {
  it("keeps the staged session index paused only while the bootstrap is actively fetching", () => {
    expect(shouldEnableSessionIndexQuery({
      hasRouteTarget: false,
      bootstrapIsFetched: false,
      bootstrapIsError: false,
      bootstrapFetchStatus: "fetching",
    })).toBe(false);
  });

  it("enables the session index when a session is already open", () => {
    expect(shouldEnableSessionIndexQuery({
      hasRouteTarget: false,
      hasActiveSession: true,
      bootstrapIsFetched: false,
      bootstrapIsError: false,
      bootstrapFetchStatus: "fetching",
    })).toBe(true);
  });

  it("recovers the session index after an aborted bootstrap returns to idle", () => {
    expect(shouldEnableSessionIndexQuery({
      hasRouteTarget: false,
      bootstrapIsFetched: false,
      bootstrapIsError: false,
      bootstrapFetchStatus: "idle",
    })).toBe(true);
  });

  it.each([
    { label: "a requested route target", hasRouteTarget: true, bootstrapIsFetched: false, bootstrapIsError: false, bootstrapFetchStatus: "fetching" as const },
    { label: "a completed bootstrap", hasRouteTarget: false, bootstrapIsFetched: true, bootstrapIsError: false, bootstrapFetchStatus: "idle" as const },
    { label: "a failed bootstrap", hasRouteTarget: false, bootstrapIsFetched: false, bootstrapIsError: true, bootstrapFetchStatus: "idle" as const },
  ])("enables the session index for $label", ({
    hasRouteTarget,
    bootstrapIsFetched,
    bootstrapIsError,
    bootstrapFetchStatus,
  }) => {
    expect(shouldEnableSessionIndexQuery({
      hasRouteTarget,
      bootstrapIsFetched,
      bootstrapIsError,
      bootstrapFetchStatus,
    })).toBe(true);
  });
});

describe("directory ready gating", () => {
  const settledGateInput = {
    hasRouteTarget: false,
    bootstrapIsFetched: true,
    bootstrapIsError: false,
    bootstrapFetchStatus: "idle" as const,
  };

  it("holds the session index while the backend directory store is mid-startup", () => {
    expect(shouldEnableSessionIndexQuery({
      ...settledGateInput,
      directoryReady: false,
    })).toBe(false);
  });

  it("holds the session index even for a route target until the directory reports", () => {
    expect(shouldEnableSessionIndexQuery({
      ...settledGateInput,
      hasRouteTarget: true,
      directoryReady: false,
    })).toBe(false);
  });

  it("enables the session index once the directory reports ready", () => {
    expect(shouldEnableSessionIndexQuery({
      ...settledGateInput,
      directoryReady: true,
    })).toBe(true);
  });

  it("treats an unknown readiness as ready so older payloads never wedge the list", () => {
    expect(shouldEnableSessionIndexQuery({
      ...settledGateInput,
      directoryReady: undefined,
    })).toBe(true);
  });

  it("reopens the session index when the bounded readiness wait expires", () => {
    expect(shouldEnableSessionIndexQuery({
      ...settledGateInput,
      directoryReady: false,
      directoryReadyWaitExpired: true,
    })).toBe(true);
  });
});

describe("directory gate loading state", () => {
  it("shows a skeleton while the directory gate holds the index back", () => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading: false,
      conversationsHasData: false,
      conversationsIsLoading: false,
      sessionsHasData: false,
      sessionsIsLoading: false,
      directoryGatePending: true,
    })).toBe(true);
  });

  it("does not claim a loading gate once the directory reports ready", () => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading: false,
      conversationsHasData: false,
      conversationsIsLoading: false,
      sessionsHasData: false,
      sessionsIsLoading: false,
      directoryGatePending: false,
    })).toBe(false);
  });
});

describe("conversation index loading state", () => {
  it("does not show a skeleton for disabled pending queries", () => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading: false,
      conversationsHasData: false,
      conversationsIsLoading: false,
      sessionsHasData: false,
      sessionsIsLoading: false,
    })).toBe(false);
  });

  it.each([
    { label: "the active-session bootstrap", bootstrapIsLoading: true, conversationsIsLoading: false, sessionsIsLoading: false },
    { label: "conversations", bootstrapIsLoading: false, conversationsIsLoading: true, sessionsIsLoading: false },
    { label: "sessions", bootstrapIsLoading: false, conversationsIsLoading: false, sessionsIsLoading: true },
  ])("shows a skeleton while $label are actually loading without data", ({
    bootstrapIsLoading,
    conversationsIsLoading,
    sessionsIsLoading,
  }) => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading,
      conversationsHasData: false,
      conversationsIsLoading,
      sessionsHasData: false,
      sessionsIsLoading,
    })).toBe(true);
  });

  it("keeps existing directory data visible during background refreshes", () => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading: true,
      conversationsHasData: true,
      conversationsIsLoading: true,
      sessionsHasData: true,
      sessionsIsLoading: true,
    })).toBe(false);
  });

  it("does not claim the directory is empty while visible sessions wait for Agent rows", () => {
    expect(shouldShowConversationIndexLoading({
      bootstrapIsLoading: false,
      conversationsHasData: false,
      conversationsIsLoading: false,
      sessionsHasData: true,
      sessionsIsLoading: false,
      agentsHasData: false,
      agentsIsLoading: true,
      visibleSessionCount: 3,
    })).toBe(true);
  });
});
