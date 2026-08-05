import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
const routeSource = `${routeShellSource}\n${routeModelSource}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
import modelSource from "./sourceCollectionRunQueryModel.ts?raw";
import queriesSource from "./useSourceCollectionRunQueries.ts?raw";
import workspaceSource from "./useSourceCollectionWorkspace.ts?raw";

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

  it("is wired via useSourceCollectionWorkspace with promoted payload types", () => {
    // Phase 1: route consumes workspace hook; workspace composes run queries.
    expect(routeSource).toContain("useSourceCollectionWorkspace({");
    expect(workspaceSource).toContain("useSourceCollectionRunQueries({");
    // Payload types live in sourceCollectionRunQueryModel; workbench no longer re-imports the module path string.
    expect(queriesSource).toMatch(/sourceCollectionRunQueryModel|SourceCollectionSummaryPayload/);
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

  it("reuses a recent selected-run summary across workspace remounts", () => {
    expect(queriesSource).toContain("staleTime: 10_000");
    expect(queriesSource).not.toContain('refetchOnMount: "always"');
  });

  it("uses a slower poll for the run list than for active run details", () => {
    expect(workspaceSource).toContain("sourceCollectionRunListRefetchInterval");
  });

  it("does not resolve the summary before a selected run is known", () => {
    expect(queriesSource).toMatch(
      /enabled:\s*Boolean\(\s*options\.effectiveTeamId\s*&&\s*options\.sourceCollectionWorkspaceSelected\s*&&\s*options\.selectedSourceCollectionRunEffectiveId\s*,?\s*\)/,
    );
  });
});
