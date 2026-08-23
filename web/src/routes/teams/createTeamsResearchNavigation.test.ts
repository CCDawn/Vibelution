import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalChallengeCupWorkspaceRoute } from "./researchWorkspaceModel";

const source = readFileSync(resolve(import.meta.dirname, "createTeamsResearchNavigation.ts"), "utf8");

describe("createTeamsResearchNavigation", () => {
  it("sends research teams to the canonical workflow route and never teamMode=canvas", () => {
    expect(source).toContain("if (isResearchWorkflowTeam(team))");
    expect(source).toContain("setResearchWorkspaceView(\"workflow\")");
    expect(source).toContain("setTeamShellMode(\"board\")");
    expect(source).toContain("canonicalChallengeCupWorkspaceRoute(team.teamId, searchParams)");
    expect(source).toContain("if (researchWorkflowTeamSelected)");
    expect(source).toContain("canonicalChallengeCupWorkspaceRoute(effectiveTeamId, searchParams)");
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
});
