import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const coreSource = readFileSync(new URL("../useSourceCollectionPresentationCore.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const labelsSource = readFileSync(new URL("./deriveSourceCollectionDisplayLabels.ts", import.meta.url), "utf8");
const downstreamSource = readFileSync(new URL("./deriveSourceCollectionDownstreamMetrics.ts", import.meta.url), "utf8");
const stageDisplaySource = readFileSync(new URL("./deriveSourceCollectionStageDisplaySurfaces.ts", import.meta.url), "utf8");

describe("deriveSourceCollectionDisplayLabels R2-m contract", () => {
  it("owns count/label text derivation formerly inlined in presentation core", () => {
    expect(labelsSource).toContain("export function deriveSourceCollectionDisplayLabels");
    expect(labelsSource).toContain("sourceCollectionRunPendingScreeningCount");
    expect(labelsSource).toContain("sourceCollectionCollectedRunSummaryText");
    expect(coreSource).toContain("deriveSourceCollectionDisplayLabels({");
    expect(coreSource).not.toContain("const sourceCollectionCollectedCountText = sourceCollectionCountText(");
    expect(coreSource).not.toContain("const sourceCollectionRunPendingScreeningCount = Math.max(");
  });
});

describe("deriveSourceCollectionDownstreamMetrics R2-m contract", () => {
  it("owns graph/memory/ingest metrics formerly inlined in presentation core", () => {
    expect(downstreamSource).toContain("export function deriveSourceCollectionDownstreamMetrics");
    expect(downstreamSource).toContain("sourceCollectionProjectedFormalKnowledgeCount");
    expect(downstreamSource).toContain("sourceCollectionCanBuildGraph");
    expect(coreSource).toContain("deriveSourceCollectionDownstreamMetrics({");
    expect(coreSource).not.toContain("const candidateGraphNodeCount = teamWorkflowCandidateGraph?.summary.nodeCount");
    expect(coreSource).not.toContain("const sourceCollectionCanBuildGraph = sourceCollectionRunApprovedCount > 0");
  });
});

describe("deriveSourceCollectionStageDisplaySurfaces R2-m contract", () => {
  it("owns stage display loading/state + extraction metric labels", () => {
    expect(stageDisplaySource).toContain("export function deriveSourceCollectionStageDisplaySurfaces");
    expect(stageDisplaySource).toContain("sourceCollectionExtractionLoadingMetric");
    expect(stageDisplaySource).toContain("sourceCollectionIngestionReadyForExperiment");
    expect(coreSource).toContain("deriveSourceCollectionStageDisplaySurfaces({");
    expect(coreSource).not.toContain("const sourceCollectionFindingDisplayLoading = sourceCollectionRecordsDataLoading");
    expect(coreSource).not.toContain("const sourceCollectionExtractionLoadingMetric = sourceCollectionProjectedCandidateCount > 0");
  });
});
