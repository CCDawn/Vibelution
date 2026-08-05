import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const coreSource = readFileSync(new URL("../useSourceCollectionPresentationCore.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const selectionSource = readFileSync(new URL("./deriveSourceCollectionSelectionPresentation.ts", import.meta.url), "utf8");

describe("deriveSourceCollectionSelectionPresentation R2-n contract", () => {
  it("owns finding/prompt-cache/candidate selection formerly inlined in presentation core", () => {
    expect(selectionSource).toContain("export function deriveSourceCollectionSelectionPresentation");
    expect(selectionSource).toContain("sourceCollectionFindingAssignments");
    expect(selectionSource).toContain("selectedSourceCollectionSearchAccepted");
    expect(selectionSource).toContain("sourceManifestCandidates");
    expect(coreSource).toContain("deriveSourceCollectionSelectionPresentation({");
    expect(coreSource).not.toContain("const sourceCollectionFindingRunOptions = sourceCollectionRuns.map(");
    expect(coreSource).not.toContain("const sourceManifestCandidates = useMemo(");
  });
});
