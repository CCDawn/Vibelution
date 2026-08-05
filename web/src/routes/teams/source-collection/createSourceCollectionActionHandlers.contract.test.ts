import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const presentationSource = readFileSync(
  new URL("../useSourceCollectionPresentationCore.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("../useSourceCollectionPresentationMid.ts", import.meta.url),
  "utf8",
) + "\n" + readFileSync(
  new URL("../useSourceCollectionPresentationTail.ts", import.meta.url),
  "utf8",
);
const handlersSource = readFileSync(
  new URL("./createSourceCollectionActionHandlers.ts", import.meta.url),
  "utf8",
);

describe("F3 createSourceCollectionActionHandlers", () => {
  it("presentation wires action handlers via factory (not inline runSourceCollection*)", () => {
    expect(presentationSource).toContain("createSourceCollectionActionHandlers");
    expect(presentationSource).not.toContain("const runSourceCollectionScreeningAction =");
    expect(presentationSource).not.toContain("const runSourceCollectionGraphAction =");
    expect(presentationSource).not.toContain("const runSourceCollectionCandidateExtractionAction =");
    expect(presentationSource).not.toContain("const runKnowledgeCollectionLoopAction =");
    expect(presentationSource).not.toContain("const runSourceCollectionSearchFromHeader =");
  });

  it("factory owns run/open/select handlers surface", () => {
    expect(handlersSource).toContain("export function createSourceCollectionActionHandlers");
    expect(handlersSource).toContain("runSourceCollectionScreeningAction");
    expect(handlersSource).toContain("runSourceCollectionGraphAction");
    expect(handlersSource).toContain("runSourceCollectionCandidateExtractionAction");
    expect(handlersSource).toContain("runKnowledgeCollectionLoopAction");
    expect(handlersSource).toContain("runSourceCollectionSearchFromHeader");
    expect(handlersSource).toContain("runSourceCollectionCollectionAction");
    expect(handlersSource).toContain("openSourceCollectionStorageTarget");
    expect(handlersSource).toContain("scrollSourceCollectionPanelIntoView");
  });
});
