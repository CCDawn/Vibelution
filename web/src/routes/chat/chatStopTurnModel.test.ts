import { describe, expect, it } from "vitest";

import type { SessionDetail } from "../../api/types";
import {
  resolveSessionStopTurnId,
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
});
