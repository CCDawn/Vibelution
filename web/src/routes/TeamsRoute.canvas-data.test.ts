import { describe, expect, it } from "vitest";

import { canvasFromKnownTeamId, canvasFromTeamOrFallback, memberCanvasFromTeam, resolveTeamsRouteEffectiveTeamId } from "./TeamsRoute.canvasData";

describe("TeamsRoute canvas data bootstrap", () => {
  it("uses a known URL team id before the slow team list arrives", () => {
    expect(
      resolveTeamsRouteEffectiveTeamId({
        forcedTeamId: "",
        selectedTeamId: "",
        requestedTeamId: "ai-search-team",
        requestedAgentTeamId: "",
        visibleTeamIds: [],
        fallbackTeamId: "",
      }),
    ).toBe("ai-search-team");
  });

  it("does not request arbitrary unknown team ids before the list confirms them", () => {
    expect(
      resolveTeamsRouteEffectiveTeamId({
        forcedTeamId: "",
        selectedTeamId: "",
        requestedTeamId: "unknown-team",
        requestedAgentTeamId: "",
        visibleTeamIds: [],
        fallbackTeamId: "",
      }),
    ).toBe("");
  });

  it("preserves the existing selection priority once visible teams are known", () => {
    expect(
      resolveTeamsRouteEffectiveTeamId({
        forcedTeamId: "",
        selectedTeamId: "research-team",
        requestedTeamId: "ai-search-team",
        requestedAgentTeamId: "knowledge-expansion-team",
        visibleTeamIds: ["research-team", "ai-search-team", "knowledge-expansion-team"],
        fallbackTeamId: "ai-search-team",
      }),
    ).toBe("research-team");
  });
});

describe("TeamsRoute canvas fallback data", () => {
  const fallbackCanvas = {
    schemaVersion: 1,
    canvasKind: "team_organization_canvas",
    teamId: "ai-search-team",
    updatedAt: "2026-07-05T00:00:00Z",
    path: "workspace/teams/ai-search-team/canvas.json",
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes: [
      { id: "lead", label: "搜索范围负责人", role: "ai_search_scope_lead", purpose: "", agentId: "A011", agentCode: "A011", agentName: "沈清和", status: "active", x: 10, y: 20 },
    ],
    edges: [],
  };

  it("uses the independent canvas payload while full team detail is still loading", () => {
    expect(canvasFromTeamOrFallback(null, fallbackCanvas).nodes).toHaveLength(1);
  });

  it("prefers full team detail canvas when it is available", () => {
    const detailCanvas = {
      ...fallbackCanvas,
      updatedAt: "2026-07-05T00:01:00Z",
      nodes: [
        ...fallbackCanvas.nodes,
        { id: "quality", label: "信号源质检", role: "signal_quality_gate", purpose: "", agentId: "A014", agentCode: "A014", agentName: "秦景行", status: "active", x: 100, y: 20 },
      ],
    };

    expect(canvasFromTeamOrFallback({ canvas: detailCanvas } as never, fallbackCanvas).nodes).toHaveLength(2);
  });

  it("builds a temporary member canvas while durable canvas data is still loading", () => {
    const canvas = memberCanvasFromTeam({
      teamId: "ai-search-team",
      name: "AI 搜索范围团队",
      canvasPath: "workspace/teams/ai-search-team/canvas.json",
      members: [
        { memberId: "m1", agentId: "A011", agentCode: "A011", agentName: "沈清和", role: "ai_search_scope_lead", purpose: "科研负责人", agentStatus: "active" },
        { memberId: "m2", agentId: "A012", agentCode: "A012", agentName: "夏云舒", role: "global_primary_sources", purpose: "全球官方源维护", agentStatus: "active" },
        { memberId: "m3", agentId: "A013", agentCode: "A013", agentName: "宋言初", role: "cn_primary_sources", purpose: "中国 AI 源维护", agentStatus: "active" },
        { memberId: "m4", agentId: "A014", agentCode: "A014", agentName: "秦景行", role: "signal_quality_gate", purpose: "信号源质检", agentStatus: "active" },
      ],
    } as never);

    expect(canvas?.nodes.map((node) => node.label)).toEqual(["科研负责人", "全球官方源维护", "中国 AI 源维护", "信号源质检"]);
    expect(canvas?.edges).toHaveLength(3);
  });

  it("shows an AI search canvas skeleton before any API payload arrives", () => {
    const canvas = canvasFromKnownTeamId("ai-search-team");

    expect(canvas?.nodes.map((node) => node.label)).toEqual(["搜索范围负责人", "全球官方源维护", "中国 AI 源维护", "信号源质检"]);
    expect(canvas?.edges.map((edge) => edge.label)).toContain("一手源回链");
  });

  it("does not invent skeleton canvases for arbitrary teams", () => {
    expect(canvasFromKnownTeamId("unknown-team")).toBeNull();
  });
});
