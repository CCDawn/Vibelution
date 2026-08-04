import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const surfaceSource = readFileSync(new URL("./teamMutationSurface.ts", import.meta.url), "utf8");

describe("teamMutationSurface Phase 4 contract", () => {
  it("TeamsRoute consumes buildTeamsRouteMutationSurface instead of repeating team-scoped ternaries", () => {
    expect(routeSource).toContain("buildTeamsRouteMutationSurface({");
    expect(routeSource).not.toContain(
      "startSourceCollectionRunMutation.isPending && startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId",
    );
    expect(routeSource).not.toContain(
      "createExperimentPlanMutation.isPending && createExperimentPlanMutation.variables?.teamId === selectedTeam?.teamId",
    );
  });

  it("helper owns scoping and candidate-id extraction", () => {
    expect(surfaceSource).toContain("export function teamScopedMutationSurface");
    expect(surfaceSource).toContain("export function teamScopedMutationCandidateId");
    expect(surfaceSource).toContain("export function buildTeamsRouteMutationSurface");
  });
});
