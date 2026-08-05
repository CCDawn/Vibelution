import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
const presentationCoreSource = readFileSync(new URL("./useSourceCollectionPresentationCore.ts", import.meta.url), "utf8");
const presentationPipelineSource = readFileSync(new URL("./useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const presentationSource = `${presentationCoreSource}\n${presentationPipelineSource}`;

describe("useSourceCollectionPresentation contract", () => {
  it("TeamsRoute consumes the presentation hook and no longer owns SC mutation surfaces inline", () => {
    expect(routeSource).toContain("useTeamsScComposition");
    expect(routeSource).not.toContain("buildTeamsRouteMutationSurface({");
    expect(routeSource).not.toContain("buildSourceCollectionWriteMutationSurface({");
    expect(routeSource).not.toContain("const sourceCollectionSummary = sourceCollectionSummaryQuery.data");
  });

  it("presentation owns summary, readiness, action adapters, and stage helpers", () => {
    expect(presentationCoreSource).toContain("export function useSourceCollectionPresentationCore");
    expect(presentationCoreSource).toContain("useSourceCollectionPresentationPipeline");
    expect(presentationSource).toContain("buildTeamsRouteMutationSurface");
    expect(presentationSource).toContain("buildSourceCollectionWriteMutationSurface");
    expect(presentationSource).toContain("sourceCollectionStageActionReadinessFor");
    expect(presentationSource).toContain("runKnowledgeCollectionLoopAction");
    expect(presentationSource).toContain("sourceCollectionDisplayState");
  });
});
