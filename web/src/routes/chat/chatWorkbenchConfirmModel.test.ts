import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import { sessionConfirmTitle } from "./chatWorkbenchConfirmModel";

function sessionFixture(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "调研团队讨论记录",
    ...overrides,
  };
}

describe("sessionConfirmTitle (ISS-035)", () => {
  it("names the session title first, not the agent display name", () => {
    expect(sessionConfirmTitle(sessionFixture({
      title: "2026 年秋季调研会话",
      agentDisplayName: "沈清和",
    }))).toBe("2026 年秋季调研会话");
  });

  it("falls back to the agent display name when the session has no title", () => {
    expect(sessionConfirmTitle(sessionFixture({
      title: "",
      agentDisplayName: "沈清和",
    }))).toBe("沈清和");
  });

  it("falls back to the session id when neither title nor agent name exists", () => {
    expect(sessionConfirmTitle(sessionFixture({
      title: "",
      agentDisplayName: "",
    }))).toBe("session-1");
    expect(sessionConfirmTitle(sessionFixture({
      title: "   ",
      agentDisplayName: undefined,
    }))).toBe("session-1");
  });

  it("trims the resolved title", () => {
    expect(sessionConfirmTitle(sessionFixture({
      title: "  带空白边界的新会话  ",
      agentDisplayName: "沈清和",
    }))).toBe("带空白边界的新会话");
  });
});
