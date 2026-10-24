import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import { sessionBulkDeletable } from "./chatSessionBulkModel";

function session(status: string, currentPhase: string): SessionSummary {
  return {
    id: "session-1",
    title: "Session",
    status,
    currentPhase,
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
  };
}

describe("session bulk delete eligibility", () => {
  it.each([
    ["paused execution", "paused", "paused", false],
    ["running status with resting current phase", "running", "ready", false],
    ["unknown activity", "future_phase", "", false],
    ["resting session", "ready", "ready", true],
  ])("follows the activity policy for %s", (_name, status, currentPhase, deletable) => {
    expect(sessionBulkDeletable(session(status, currentPhase))).toBe(deletable);
  });
});
