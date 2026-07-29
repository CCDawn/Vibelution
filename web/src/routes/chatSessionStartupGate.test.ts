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
});
