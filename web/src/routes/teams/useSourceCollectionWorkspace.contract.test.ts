import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeShellSource = readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8");
const routeModelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
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
    expect(hookSource).toContain("sourceCollectionStageWritebackAwaitingTask");
    expect(hookSource).toContain("sourceCollectionFreshProjectDraft");
    expect(hookSource).toContain("setSourceCollectionResultPageByStage({");
  });

  it("TeamsRoute does not re-declare SC pagination reset or writeback-awaiting derived", () => {
    expect(routeSource).not.toContain(
      "const sourceCollectionStageWritebackAwaitingTask = sourceCollectionStageWritebackSyncActive && sourceCollectionPendingStageTaskIdList.length > 0",
    );
  });
});
