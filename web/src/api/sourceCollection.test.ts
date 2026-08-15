import { describe, expect, it } from "vitest";

import apiSource from "./sourceCollection.ts?raw";
import queriesSource from "../routes/teams/useSourceCollectionRunQueries.ts?raw";

describe("source-collection catalog API", () => {
  it("owns the selected-run summary transport", () => {
    expect(apiSource).toContain("export function fetchSourceCollectionSummary");
    expect(apiSource).toContain("/workflow-orchestration/source-collection/summary");
    expect(apiSource).toContain('search.set("runId", options.runId)');
  });

  it("keeps React Query orchestration free of the summary path", () => {
    expect(queriesSource).toContain("fetchSourceCollectionSummary");
    expect(queriesSource).not.toContain("/workflow-orchestration/source-collection/summary");
  });
});
