import { describe, expect, it } from "vitest";

import type { SessionDetail } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import {
  congestedQueryKeysForSessionStop,
  resolveSessionStopTurnId,
  resolveStopOptimisticTarget,
  sessionStopRequestBody,
} from "./chatStopTurnModel";

function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-a",
    title: "Session",
    status: "running",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "running",
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    messages: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...overrides,
  };
}

describe("chat stop turn model", () => {
  it("prefers the authoritative active turn id", () => {
    expect(resolveSessionStopTurnId(detail({
      activeTurnId: "turn-active",
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "hello",
          timestamp: "",
          metadata: { turnId: "turn-message" },
        },
      ],
    }))).toBe("turn-active");
  });

  it("prefers the accepted active-layer turn over a stale detail projection", () => {
    expect(resolveSessionStopTurnId(detail({
      activeTurnId: "turn-stale",
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "hello",
          timestamp: "",
          metadata: { turnId: "turn-stale" },
        },
      ],
    }), "turn-accepted")).toBe("turn-accepted");
  });

  it("does not send a stale stop request while the active layer is still optimistic", () => {
    expect(resolveSessionStopTurnId(detail({ activeTurnId: "turn-stale" }), "optimistic-submit-1")).toBe("");
  });

  it("falls back to the latest accepted user turn", () => {
    expect(resolveSessionStopTurnId(detail({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "hello",
          timestamp: "",
          metadata: { turnId: "turn-message" },
        },
      ],
    }))).toBe("turn-message");
  });

  it("does not create an unbound stop request", () => {
    expect(sessionStopRequestBody("")).toBeUndefined();
    expect(sessionStopRequestBody(" turn-1 ")).toBe('{"turnId":"turn-1"}');
  });

  it("cancels congested catalog queries before a stop POST competes for HTTP/1.1 slots", () => {
    expect(congestedQueryKeysForSessionStop("session-a")).toEqual([
      queryKeys.conversations(),
      queryKeys.sessions(),
      queryKeys.session("session-a"),
      queryKeys.launcherBranchInstances(),
      queryKeys.launcherStatus(),
      queryKeys.gitStatus(),
      queryKeys.agents(),
    ]);
  });

  it("restores the deferred pre-stop detail when the stop POST fails", () => {
    const running = detail({ activeTurnId: "turn-2" });
    const deferredStopping = detail({
      activeTurnId: "turn-2",
      currentPhase: "stopping",
      stopRequested: true,
      stopRequestedAt: "2026-01-01T00:00:05Z",
    });

    const target = resolveStopOptimisticTarget(
      { previousDetail: running, stoppingAt: "2026-01-01T00:00:05Z" },
      deferredStopping,
      "2026-01-01T00:00:09Z",
    );

    expect(target.previousDetail).toBe(running);
    expect(target.stoppingAt).toBe("2026-01-01T00:00:05Z");
  });

  it("falls back to the cached detail when the stop was not deferred", () => {
    const running = detail({ activeTurnId: "turn-2" });

    const target = resolveStopOptimisticTarget(undefined, running, "2026-01-01T00:00:09Z");

    expect(target.previousDetail).toBe(running);
    expect(target.stoppingAt).toBe("2026-01-01T00:00:09Z");
  });
});
