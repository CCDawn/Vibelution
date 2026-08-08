import { describe, expect, it } from "vitest";

import {
  shouldCanonicalizeUrlSessionSelection,
  shouldDeferUrlSessionSync,
} from "./chatSessionRouteSync";

describe("shouldCanonicalizeUrlSessionSelection", () => {
  it("canonicalizes an explicit deep-link target even when the store already paints it", () => {
    expect(
      shouldCanonicalizeUrlSessionSelection({
        requestedSessionId: "session-a",
        activeSessionId: "session-a",
        intentSessionId: "",
      }),
    ).toBe(true);
  });

  it("does not duplicate the select already scheduled by a tab click", () => {
    expect(
      shouldCanonicalizeUrlSessionSelection({
        requestedSessionId: "session-a",
        activeSessionId: "session-a",
        intentSessionId: "session-a",
      }),
    ).toBe(false);
  });

  it("does not send temporary local sessions to the server", () => {
    expect(
      shouldCanonicalizeUrlSessionSelection({
        requestedSessionId: "temp-session-local",
        activeSessionId: "",
        intentSessionId: "",
      }),
    ).toBe(false);
  });
});

describe("shouldDeferUrlSessionSync", () => {
  it("defers URL→active sync while optimistic intent is ahead of the router", () => {
    expect(
      shouldDeferUrlSessionSync({
        requestedSessionId: "terra",
        activeSessionId: "grok",
        intentSessionId: "grok",
        intentAtMs: 1_000,
        nowMs: 1_200,
      }),
    ).toBe(true);
  });

  it("does not defer once the URL matches the optimistic intent", () => {
    expect(
      shouldDeferUrlSessionSync({
        requestedSessionId: "grok",
        activeSessionId: "grok",
        intentSessionId: "grok",
        intentAtMs: 1_000,
        nowMs: 1_200,
      }),
    ).toBe(false);
  });

  it("does not defer browser-back after the intent grace window", () => {
    expect(
      shouldDeferUrlSessionSync({
        requestedSessionId: "terra",
        activeSessionId: "grok",
        intentSessionId: "grok",
        intentAtMs: 1_000,
        nowMs: 4_000,
      }),
    ).toBe(false);
  });

  it("does not defer when active was not set by the latest intent", () => {
    expect(
      shouldDeferUrlSessionSync({
        requestedSessionId: "terra",
        activeSessionId: "other",
        intentSessionId: "grok",
        intentAtMs: 1_000,
        nowMs: 1_200,
      }),
    ).toBe(false);
  });
});
