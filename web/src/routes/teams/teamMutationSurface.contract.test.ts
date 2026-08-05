import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
const presentationSource = readFileSync(new URL("./useSourceCollectionPresentationCore.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const surfaceSource = readFileSync(new URL("./teamMutationSurface.ts", import.meta.url), "utf8");

describe("teamMutationSurface Phase 4 contract", () => {
  it("SC presentation consumes buildTeamsRouteMutationSurface instead of repeating team-scoped ternaries", () => {
    expect(presentationSource).toContain("buildTeamsRouteMutationSurface({");
    expect(routeSource).toContain("useTeamsScComposition");
    expect(routeSource).not.toContain(
      "startSourceCollectionRunMutation.isPending && startSourceCollectionRunMutation.variables?.teamId === selectedTeam?.teamId",
    );
    expect(routeSource).not.toContain(
      "createExperimentPlanMutation.isPending && createExperimentPlanMutation.variables?.teamId === selectedTeam?.teamId",
    );
  });

  it("SC presentation consumes SC write mutation surface for quality/graph/knowledge flags", () => {
    expect(presentationSource).toContain("buildSourceCollectionWriteMutationSurface({");
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
