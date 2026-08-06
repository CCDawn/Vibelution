import { describe, expect, it } from "vitest";

import { shouldDeferUrlSessionSync } from "./chatSessionRouteSync";

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
