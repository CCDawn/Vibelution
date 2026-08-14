import { describe, expect, it } from "vitest";

import {
  resolveArchivedSessionRouteTransition,
  resolveAuthoritativeArchivedSessionIds,
} from "./chatSessionRouteSync";

describe("resolveArchivedSessionRouteTransition", () => {
  it("retires an archived explicit route target and replaces it with the fallback", () => {
    expect(resolveArchivedSessionRouteTransition({
      archivedSessionIds: ["session-archived"],
      requestedSessionId: "session-archived",
      fallbackSessionId: "session-live",
    })).toEqual({
      shouldRetireRoute: true,
      nextRequestedSessionId: "session-live",
    });
  });

  it("removes the stale URL target when there is no surviving fallback session", () => {
    expect(resolveArchivedSessionRouteTransition({
      archivedSessionIds: ["session-archived"],
      requestedSessionId: "session-archived",
      fallbackSessionId: "",
    })).toEqual({
      shouldRetireRoute: true,
      nextRequestedSessionId: "",
    });
  });

  it("never retires a route that does not point at an archived session", () => {
    expect(resolveArchivedSessionRouteTransition({
      archivedSessionIds: ["session-archived"],
      requestedSessionId: "session-other",
      fallbackSessionId: "session-live",
    })).toEqual({
      shouldRetireRoute: false,
      nextRequestedSessionId: "session-other",
    });
  });

  it("never retires a bare route", () => {
    expect(resolveArchivedSessionRouteTransition({
      archivedSessionIds: ["session-archived"],
      requestedSessionId: "",
      fallbackSessionId: "session-live",
    })).toEqual({
      shouldRetireRoute: false,
      nextRequestedSessionId: "",
    });
  });
});

describe("resolveAuthoritativeArchivedSessionIds", () => {
  it("uses the archive transaction's complete session list instead of a partial loaded index", () => {
    expect(resolveAuthoritativeArchivedSessionIds({
      optimisticSessionIds: ["session-visible"],
      archiveSummary: {
        sessions: {
          sessionIds: ["session-visible", "session-not-loaded", "session-visible"],
        },
      },
    })).toEqual(["session-visible", "session-not-loaded"]);
  });

  it("keeps the optimistic list only for legacy archive responses without a session summary", () => {
    expect(resolveAuthoritativeArchivedSessionIds({
      optimisticSessionIds: ["session-visible", "session-visible"],
      archiveSummary: {},
    })).toEqual(["session-visible"]);
  });
});
