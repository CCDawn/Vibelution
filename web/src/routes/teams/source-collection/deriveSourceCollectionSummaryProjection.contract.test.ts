import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const coreSource = readFileSync(new URL("../useSourceCollectionPresentationCore.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const summarySource = readFileSync(new URL("./deriveSourceCollectionSummaryProjection.ts", import.meta.url), "utf8");
const helpersSource = readFileSync(new URL("./createSourceCollectionStageActionHelpers.ts", import.meta.url), "utf8");
const scCompositionSource = readFileSync(new URL("../useTeamsScComposition.ts", import.meta.url), "utf8");

describe("R2-o presentation + scComposition contracts", () => {
  it("summary projection owns stage-round / phase-close / records unpacking", () => {
    expect(summarySource).toContain("export function deriveSourceCollectionSummaryProjection");
    expect(summarySource).toContain("selectSourceCollectionStageRound");
    expect(summarySource).toContain("sourceCollectionPhaseCloseGateForRun");
    expect(coreSource).toContain("deriveSourceCollectionSummaryProjection({");
    expect(coreSource).not.toContain("const sourceCollectionSummaryStageRound = useMemo");
  });

  it("stage action helpers own finding/extraction/relations/ingestion readiness", () => {
    expect(helpersSource).toContain("export function createSourceCollectionStageActionHelpers");
    expect(helpersSource).toContain("sourceCollectionStageActionReadinessFor");
    expect(coreSource).toContain("createSourceCollectionStageActionHelpers({");
    expect(coreSource).not.toContain("const sourceCollectionStageTaskActionLabel = (stageId");
  });

  it("scComposition spreads presentation + stage surfaces without flat re-list", () => {
    expect(scCompositionSource).toContain("...presentation");
    expect(scCompositionSource).toContain("...stageSurfaces");
    expect(scCompositionSource).toContain("composeSourceCollectionStageSurfaces({");
    expect(scCompositionSource).not.toContain("sourceCollectionProjectedCollectedCountText,");
    // Was ~40k+ chars with flat re-list; passthrough form should stay under 20k.
    expect(scCompositionSource.length).toBeLessThan(20000);
  });
});
