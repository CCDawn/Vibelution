import { describe, expect, it } from "vitest";

import apiSource from "./dataProcessing.ts?raw";
import queriesSource from "../routes/teams/useSourceCollectionRunQueries.ts?raw";
import workspaceSource from "../routes/teams/useSourceCollectionWorkspace.ts?raw";

describe("data-processing catalog API", () => {
  it("owns the SC run list, status, records, and assignment transports", () => {
    expect(apiSource).toContain("export function listDataProcessingRuns");
    expect(apiSource).toContain("export function fetchDataProcessingRunStatus");
    expect(apiSource).toContain("export function listDataProcessingRunRecords");
    expect(apiSource).toContain("export function listDataProcessingCollectionAssignments");
    expect(apiSource).toContain("/api/data-processing/runs?");
    expect(apiSource).toContain("/status");
    expect(apiSource).toContain("/records");
    expect(apiSource).toContain("/collection-assignments");
    expect(apiSource).toContain('search.set("startedFrom", options.startedFrom)');
  });

  it("keeps SC workspace and run queries free of those data-processing paths", () => {
    expect(workspaceSource).toContain("listDataProcessingRuns(");
    expect(workspaceSource).not.toContain("/api/data-processing/runs");
    expect(queriesSource).toContain("fetchDataProcessingRunStatus(");
    expect(queriesSource).toContain("listDataProcessingRunRecords<");
    expect(queriesSource).toContain("listDataProcessingCollectionAssignments(");
    expect(queriesSource).not.toContain("/api/data-processing/runs");
  });
});
