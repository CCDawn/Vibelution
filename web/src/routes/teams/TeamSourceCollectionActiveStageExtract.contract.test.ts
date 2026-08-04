import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const injectSource = readFileSync(new URL("./TeamSourceCollectionActiveStageInject.tsx", import.meta.url), "utf8");
const bagSource = readFileSync(new URL("./source-collection/extractionRecoveryBag.ts", import.meta.url), "utf8");

describe("active-stage extraction recovery bag extraction", () => {
  it("TeamsRoute builds the bag through a named helper and ActiveStageInject normalizes it", () => {
    expect(routeSource).toContain("function buildActiveStageExtractionRecoveryBag()");
    expect(routeSource).toContain("extractionRecovery={buildActiveStageExtractionRecoveryBag()}");
    expect(routeSource).not.toContain("extractionRecovery={{\n          candidateProjection:");
    expect(injectSource).toContain("buildSourceCollectionExtractionRecoveryBag");
    expect(bagSource).toContain("export type SourceCollectionExtractionRecoveryBag");
    expect(bagSource).toContain("export function buildSourceCollectionExtractionRecoveryBag");
  });

  it("route still wires stage render callbacks and advanceToRelations", () => {
    expect(routeSource).toContain("renderSourceCollectionConversation={renderSourceCollectionConversation}");
    expect(routeSource).toContain("renderSourceCollectionScreeningPanel={renderSourceCollectionScreeningPanel}");
    expect(routeSource).toContain("renderSourceCollectionGraphPanel={renderSourceCollectionGraphPanel}");
    expect(routeSource).toContain("renderSourceCollectionMemoryPanel={renderSourceCollectionMemoryPanel}");
    expect(routeSource).toContain('advanceToRelations: () => selectSourceCollectionStage("relations")');
  });
});
