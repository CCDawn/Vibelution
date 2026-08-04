import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const presentationSource = readFileSync(new URL("./useSourceCollectionPresentation.ts", import.meta.url), "utf8");

describe("useSourceCollectionPresentation contract", () => {
  it("TeamsRoute consumes the presentation hook and no longer owns SC mutation surfaces inline", () => {
    expect(routeSource).toContain("useSourceCollectionPresentation({");
    expect(routeSource).not.toContain("buildTeamsRouteMutationSurface({");
    expect(routeSource).not.toContain("buildSourceCollectionWriteMutationSurface({");
    expect(routeSource).not.toContain("const sourceCollectionSummary = sourceCollectionSummaryQuery.data");
  });

  it("presentation owns summary, readiness, action adapters, and stage helpers", () => {
    expect(presentationSource).toContain("export function useSourceCollectionPresentation");
    expect(presentationSource).toContain("buildTeamsRouteMutationSurface");
    expect(presentationSource).toContain("buildSourceCollectionWriteMutationSurface");
    expect(presentationSource).toContain("sourceCollectionStageActionReadinessFor");
    expect(presentationSource).toContain("runKnowledgeCollectionLoopAction");
    expect(presentationSource).toContain("sourceCollectionDisplayState");
  });
});
