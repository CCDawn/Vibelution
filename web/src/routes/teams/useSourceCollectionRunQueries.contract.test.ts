import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
import modelSource from "./sourceCollectionRunQueryModel.ts?raw";
import queriesSource from "./useSourceCollectionRunQueries.ts?raw";

describe("source-collection run queries contract", () => {
  it("owns selected-run detail queries", () => {
    expect(queriesSource).toContain("sourceCollectionSummaryQuery");
    expect(queriesSource).toContain("sourceCollectionRunStatusQuery");
    expect(queriesSource).toContain("sourceCollectionRecordsQuery");
    expect(queriesSource).toContain("sourceCollectionAssignmentsQuery");
    expect(queriesSource.match(/\buseQuery\(/g) ?? []).toHaveLength(4);
  });

  it("stays free of mutations and streaming", () => {
    expect(queriesSource).not.toContain("useMutation");
    expect(queriesSource).not.toMatch(/\bnew EventSource\b/);
  });

  it("is wired from TeamsRoute with promoted payload types", () => {
    expect(routeSource).toContain("useSourceCollectionRunQueries({");
    expect(routeSource).toContain("sourceCollectionRunQueryModel");
    expect(modelSource).toContain("export type SourceCollectionSummaryPayload");
    expect(modelSource).toContain("export type DataProcessingRecordListPayload");
    expect(routeSource).not.toContain("type SourceCollectionSummaryPayload =");
    expect(routeSource).not.toContain("type DataProcessingRecordListPayload =");
  });

  it("preserves summary and data-processing detail endpoints", () => {
    expect(queriesSource).toContain("/workflow-orchestration/source-collection/summary");
    expect(queriesSource).toContain("/records");
    expect(queriesSource).toContain("/collection-assignments");
    expect(queriesSource).toContain("/status");
  });
});
