import { describe, expect, it } from "vitest";

import {
  isProjectAgentBusEventRevoked,
  projectAgentBusEventsForTeam,
  projectAgentBusTimelineUrl,
} from "./projectAgentBus";
import type { ProjectAgentBusEvent, ProjectAgentBusTimeline } from "./types";

function event(eventId: string, teamId: string, status = ""): ProjectAgentBusEvent {
  return {
    eventId,
    messageType: "user_guidance",
    targetScope: "all",
    targetAgentIds: [],
    targetAgentCodes: [],
    targetAgentNames: [],
    mentionedTokens: [],
    unresolvedMentions: [],
    content: eventId,
    summary: eventId,
    status,
    createdBy: "user",
    createdAt: "2026-05-29T00:00:00Z",
    updatedAt: "2026-05-29T00:00:00Z",
    metadata: teamId ? { teamId } : {},
    deliveries: [],
    interruptions: [],
  };
}

describe("projectAgentBus api helpers", () => {
  it("builds canonical timeline urls", () => {
    expect(projectAgentBusTimelineUrl()).toBe("/api/project-agent-bus");
    expect(projectAgentBusTimelineUrl(120)).toBe("/api/project-agent-bus?limit=120");
  });

  it("detects revoked bus events without leaking status normalization to routes", () => {
    expect(isProjectAgentBusEventRevoked(event("a", "team-1", " revoked "))).toBe(true);
    expect(isProjectAgentBusEventRevoked(event("b", "team-1", "sent"))).toBe(false);
    expect(isProjectAgentBusEventRevoked(event("c", "team-1"))).toBe(false);
  });

  it("returns newest team events first from a shared project bus timeline", () => {
    const timeline: ProjectAgentBusTimeline = {
      activeAgentCount: 2,
      updatedAt: "2026-05-29T00:00:00Z",
      events: [
        event("old-match", "team-1"),
        event("other-team", "team-2"),
        event("new-match", "team-1"),
      ],
    };

    expect(projectAgentBusEventsForTeam(timeline, "team-1")).toEqual([
      expect.objectContaining({ eventId: "new-match" }),
      expect.objectContaining({ eventId: "old-match" }),
    ]);
    expect(projectAgentBusEventsForTeam(timeline, "team-1", 1)).toEqual([
      expect.objectContaining({ eventId: "new-match" }),
    ]);
  });

  it("returns no team events when no team is selected", () => {
    expect(projectAgentBusEventsForTeam(undefined, "")).toEqual([]);
  });
});
