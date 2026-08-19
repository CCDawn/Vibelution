import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(import.meta.dirname, "createTeamsResearchNavigation.ts"), "utf8");

describe("createTeamsResearchNavigation", () => {
  it("sends research teams to teamWorkspaceRoute on board, never teamMode=canvas", () => {
    expect(source).toContain("if (isResearchWorkflowTeam(team))");
    expect(source).toContain("setResearchWorkspaceView(\"workflow\")");
    expect(source).toContain("setTeamShellMode(\"board\")");
    expect(source).toContain("teamWorkspaceRoute(team.teamId)");
    expect(source).toContain("if (researchWorkflowTeamSelected)");
    expect(source).toContain("teamWorkspaceRoute(effectiveTeamId)");
    expect(source).toContain("params.set(\"teamMode\", \"board\")");
    expect(source).toMatch(/setTeamShellMode\(\"canvas\"\)[\s\S]*nextParams\.set\(\"teamMode\", \"canvas\"\)/);
  });
});
