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

  it("TeamsRoute consumes SC write mutation surface for quality/graph/knowledge flags", () => {
    expect(routeSource).toContain("buildSourceCollectionWriteMutationSurface({");
    expect(routeSource).not.toContain(
      "buildCandidateGraphMutation.isPending && buildCandidateGraphMutation.variables?.teamId === selectedTeam?.teamId",
    );
    expect(routeSource).not.toContain(
      "assessSourceQualityMutation.isPending && assessSourceQualityMutation.variables?.teamId === selectedTeam?.teamId",
    );
  });

  it("helper owns scoping, candidate-id extraction, and SC write surface", () => {
    expect(surfaceSource).toContain("export function teamScopedMutationSurface");
    expect(surfaceSource).toContain("export function teamScopedMutationCandidateId");
    expect(surfaceSource).toContain("export function buildTeamsRouteMutationSurface");
    expect(surfaceSource).toContain("export function buildSourceCollectionWriteMutationSurface");
    expect(surfaceSource).toContain("export function buildSourceCollectionQualityBatchFeedback");
  });
});
