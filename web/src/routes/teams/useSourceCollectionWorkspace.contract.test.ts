import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const hookSource = readFileSync(new URL("./useSourceCollectionWorkspace.ts", import.meta.url), "utf8");

describe("useSourceCollectionWorkspace Phase 1 contract", () => {
  it("TeamsRoute consumes the SC workspace hook and no longer declares SC useState", () => {
    expect(routeSource).toContain("useSourceCollectionWorkspace({");
    expect(routeSource).not.toContain("const [sourceCollectionDraft, setSourceCollectionDraft]");
    expect(routeSource).not.toContain("const [selectedSourceCollectionRunId, setSelectedSourceCollectionRunId]");
    expect(routeSource).not.toContain("const [selectedSourceCollectionStageId, setSelectedSourceCollectionStageId]");
    expect(routeSource).not.toContain("const sourceCollectionRunsQuery = useQuery");
    expect(routeSource).not.toContain("} = useSourceCollectionRunQueries({");
  });

  it("hook owns project/run list, default selection, writeback sync, and detail queries", () => {
    expect(hookSource).toContain("export function useSourceCollectionWorkspace");
    expect(hookSource).toContain("sourceCollectionRunsForTeam");
    expect(hookSource).toContain("selectDefaultSourceCollectionRun");
    expect(hookSource).toContain("useSourceCollectionRunQueries");
    expect(hookSource).toContain("sourceCollectionStageWritebackSyncActive");
    expect(hookSource).toContain("sourceCollectionFreshProjectDraft");
  });
});
