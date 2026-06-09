import { describe, expect, it } from "vitest";

import type { Team } from "../api/types";
import { teamCategoryLabel, teamMemberPreview, teamStatusLabel } from "./GroupSessionIndexItems";

function team(overrides: Partial<Team>): Team {
  return {
    teamId: "team-1",
    name: "科研团队",
    description: "",
    purpose: "",
    status: "active",
    teamKind: "",
    teamCategory: "",
    teamSource: "manual",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    canvas: {
      path: "",
      nodeCount: 0,
      edgeCount: 0,
    },
    ...overrides,
  };
}

describe("GroupSessionIndexItems helpers", () => {
  it("localizes known Team status labels and delegates unknown status to the route fallback", () => {
    const fallback = (status: string) => `status:${status}`;

    expect(teamStatusLabel("active", "zh", fallback)).toBe("启用中");
    expect(teamStatusLabel("archived", "en", fallback)).toBe("Archived");
    expect(teamStatusLabel("paused", "zh", fallback)).toBe("status:paused");
  });

  it("prefers named member previews before compact member counts", () => {
    expect(teamMemberPreview(team({
      memberCount: 4,
      members: [
        { memberId: "1", agentId: "a1", agentCode: "A001", agentName: "广撒网", role: "search", purpose: "", agentStatus: "active" },
        { memberId: "2", agentId: "a2", agentCode: "A002", agentName: "", role: "review", purpose: "", agentStatus: "active" },
        { memberId: "3", agentId: "a3", agentCode: "A003", agentName: "证据审查", role: "evidence", purpose: "", agentStatus: "active" },
        { memberId: "4", agentId: "a4", agentCode: "A004", agentName: "未展示", role: "extra", purpose: "", agentStatus: "active" },
      ],
    }), "zh")).toBe("广撒网, A002, 证据审查");
    expect(teamMemberPreview(team({ memberCount: 2 }), "en")).toBe("2");
    expect(teamMemberPreview(team({ memberCount: 0 }), "zh")).toBe("待绑定");
  });

  it("uses Team category before kind and falls back to a localized custom label", () => {
    expect(teamCategoryLabel(team({ teamCategory: "科研", teamKind: "research" }), "zh")).toBe("科研");
    expect(teamCategoryLabel(team({ teamCategory: "", teamKind: "research" }), "en")).toBe("research");
    expect(teamCategoryLabel(team({ teamCategory: "", teamKind: "" }), "zh")).toBe("自定义团队");
  });
});
