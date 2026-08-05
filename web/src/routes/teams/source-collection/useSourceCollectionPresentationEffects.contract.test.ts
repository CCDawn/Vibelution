import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const coreSource = readFileSync(new URL("../useSourceCollectionPresentationCore.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const effectsSource = readFileSync(new URL("./useSourceCollectionPresentationEffects.ts", import.meta.url), "utf8");
const metricsSource = readFileSync(new URL("./deriveSourceCollectionListMetrics.ts", import.meta.url), "utf8");

describe("useSourceCollectionPresentationEffects R2-l contract", () => {
  it("owns stage/search invalidation and candidate hygiene effects", () => {
    expect(effectsSource).toContain("export function useSourceCollectionPresentationEffects");
    expect(effectsSource).toContain("SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS");
    expect(effectsSource).toContain("setSelectedSourceCollectionCandidateId(\"\")");
    expect(coreSource).toContain("useSourceCollectionPresentationEffects({");
    expect(coreSource).not.toContain("Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS");
  });
});

describe("deriveSourceCollectionListMetrics R2-l contract", () => {
  it("owns list/count/loading metrics formerly inlined in presentation core", () => {
    expect(metricsSource).toContain("export function deriveSourceCollectionListMetrics");
    expect(metricsSource).toContain("sourceCollectionProjectedApprovedCount");
    expect(metricsSource).toContain("sourceCollectionActionDataError");
    expect(coreSource).toContain("deriveSourceCollectionListMetrics({");
    expect(coreSource).not.toContain("const sourceCollectionPrimaryDataLoading = Boolean(");
  });
});
