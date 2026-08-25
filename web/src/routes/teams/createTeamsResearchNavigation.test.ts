import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Dispatch, SetStateAction } from "react";
import type { SetURLSearchParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Team } from "../../api/types";
import { createTeamsResearchNavigation } from "./createTeamsResearchNavigation";
import {
  canonicalChallengeCupWorkspaceRoute,
  canonicalChallengeCupWorkspaceRouteForEffectiveTeam,
} from "./researchWorkspaceModel";
import type { TeamShellMode } from "./teamShellModel";

const source = readFileSync(resolve(import.meta.dirname, "createTeamsResearchNavigation.ts"), "utf8");

function researchTeam(teamId: string): Team {
  return {
    teamId,
    name: teamId,
    description: "",
    purpose: "",
    status: "active",
    teamKind: "research",
    teamCategory: "research",
    teamSource: "research_organization",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "",
    updatedAt: "",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
  };
}

function navigationFor(search: string) {
  const setSearchParamsSpy = vi.fn();
  const setTeamShellModeSpy = vi.fn();
  const setResearchWorkspaceViewSpy = vi.fn();
  const setSelectedTeamIdSpy = vi.fn();
  const setSelectedNodeIdSpy = vi.fn();
  const navigation = createTeamsResearchNavigation({
    searchParams: new URLSearchParams(search),
    setSearchParams: setSearchParamsSpy as unknown as SetURLSearchParams,
    effectiveTeamId: "research-team-a",
    teamShellMode: "board",
    researchWorkflowTeamSelected: true,
    researchWorkspaceView: "workflow",
    setTeamShellMode: setTeamShellModeSpy as unknown as Dispatch<SetStateAction<TeamShellMode>>,
    setResearchWorkspaceView: setResearchWorkspaceViewSpy as unknown as Dispatch<SetStateAction<"workflow">>,
    setSelectedTeamId: setSelectedTeamIdSpy as unknown as Dispatch<SetStateAction<string>>,
    setSelectedNodeId: setSelectedNodeIdSpy as unknown as Dispatch<SetStateAction<string>>,
  });
  return { navigation, setSearchParamsSpy };
}

describe("createTeamsResearchNavigation", () => {
  it("sends research teams to the canonical workflow route and never teamMode=canvas", () => {
    expect(source).toContain("if (isResearchWorkflowTeam(team))");
    expect(source).toContain("setResearchWorkspaceView(\"workflow\")");
    expect(source).toContain("setTeamShellMode(\"board\")");
    expect(source).toContain("canonicalChallengeCupWorkspaceRoute(team.teamId, searchParams)");
    expect(source).toContain("if (researchWorkflowTeamSelected)");
    expect(source).toContain("canonicalChallengeCupWorkspaceRouteForEffectiveTeam(effectiveTeamId, searchParams)");
    expect(source).not.toContain("params.set(\"teamMode\", \"board\")");
    expect(source).toMatch(/setTeamShellMode\(\"canvas\"\)[\s\S]*nextParams\.set\(\"teamMode\", \"canvas\"\)/);
  });

  it("preserves process focus while canonicalizing a legacy research URL", () => {
    const route = canonicalChallengeCupWorkspaceRoute(
      "research-team",
      new URLSearchParams("team=research-team&researchView=overview&questionId=SCI-096&runId=run-1&node=hypothesis_design&panel=question"),
    );

    expect(route).toContain("teamId=research-team");
    expect(route).toContain("researchView=workflow");
    expect(route).toContain("workflowId=challenge-cup-research");
    expect(route).toContain("questionId=SCI-096");
    expect(route).toContain("runId=run-1");
    expect(route).toContain("node=hypothesis_design");
    expect(route).toContain("panel=question");
    expect(route).not.toContain("teamMode=canvas");
  });

  it("clears focus when switching research teams but preserves it for the same team", () => {
    const focus = "questionId=SCI-096&runId=run-a&node=hypothesis_design&panel=question";
    const switchToB = navigationFor(`teamId=research-team-a&researchView=workflow&${focus}`);
    switchToB.navigation.selectTeamRecord(researchTeam("research-team-b"));
    const switchedParams = switchToB.setSearchParamsSpy.mock.calls[0]?.[0] as URLSearchParams;

    expect(switchedParams.get("teamId")).toBe("research-team-b");
    expect(switchedParams.get("researchView")).toBe("workflow");
    expect(switchedParams.get("workflowId")).toBe("challenge-cup-research");
    expect(switchedParams.has("questionId")).toBe(false);
    expect(switchedParams.has("runId")).toBe(false);
    expect(switchedParams.has("node")).toBe(false);
    expect(switchedParams.has("panel")).toBe(false);
    expect(switchToB.setSearchParamsSpy.mock.calls[0]?.[1]).toEqual({ replace: false });

    const sameTeam = navigationFor(`team=research-team-a&${focus}`);
    sameTeam.navigation.selectTeamRecord(researchTeam("research-team-a"));
    const sameTeamParams = sameTeam.setSearchParamsSpy.mock.calls[0]?.[0] as URLSearchParams;

    expect(sameTeamParams.get("teamId")).toBe("research-team-a");
    expect(sameTeamParams.get("questionId")).toBe("SCI-096");
    expect(sameTeamParams.get("runId")).toBe("run-a");
    expect(sameTeamParams.get("node")).toBe("hypothesis_design");
    expect(sameTeamParams.get("panel")).toBe("question");
    expect(sameTeam.setSearchParamsSpy.mock.calls[0]?.[1]).toEqual({ replace: true });

    const conflictingAliases = navigationFor(`teamId=research-team-a&team=research-team-b&${focus}`);
    conflictingAliases.navigation.selectTeamRecord(researchTeam("research-team-a"));
    const conflictingParams = conflictingAliases.setSearchParamsSpy.mock.calls[0]?.[0] as URLSearchParams;
    expect(conflictingParams.has("questionId")).toBe(false);
    expect(conflictingParams.has("runId")).toBe(false);
    expect(conflictingParams.has("node")).toBe(false);
    expect(conflictingParams.has("panel")).toBe(false);
    expect(conflictingAliases.setSearchParamsSpy.mock.calls[0]?.[1]).toEqual({ replace: false });
  });

  it.each([
    ["selectResearchWorkspaceView", (navigation: ReturnType<typeof navigationFor>["navigation"]) => {
      navigation.selectResearchWorkspaceView("overview");
    }],
    ["selectTeamShellMode", (navigation: ReturnType<typeof navigationFor>["navigation"]) => {
      navigation.selectTeamShellMode("canvas");
    }],
  ])("drops cross-team focus in %s and preserves same-team focus", (_path, invoke) => {
    const focus = "questionId=SCI-096&runId=run-a&node=hypothesis_design&panel=question";
    const resolveParams = (search: string) => {
      const state = navigationFor(search);
      invoke(state.navigation);
      return state.setSearchParamsSpy.mock.calls[0]?.[0] as URLSearchParams;
    };

    for (const search of [
      `researchView=overview&${focus}`,
      `teamId=research-team-a&team=research-team-b&researchView=overview&${focus}`,
    ]) {
      const params = resolveParams(search);
      expect(params.get("teamId")).toBe("research-team-a");
      expect(params.get("researchView")).toBe("workflow");
      expect(params.has("questionId")).toBe(false);
      expect(params.has("runId")).toBe(false);
      expect(params.has("node")).toBe(false);
      expect(params.has("panel")).toBe(false);
    }

    const sameTeamParams = resolveParams(`team=research-team-a&researchView=overview&${focus}`);
    expect(sameTeamParams.get("questionId")).toBe("SCI-096");
    expect(sameTeamParams.get("runId")).toBe("run-a");
    expect(sameTeamParams.get("node")).toBe("hypothesis_design");
    expect(sameTeamParams.get("panel")).toBe("question");
  });
});
