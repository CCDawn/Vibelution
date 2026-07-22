import { describe, expect, it } from "vitest";

import {
  isForeignTeamDetailQueryKey,
  resolveResearchSecondaryStatusQueryEnabled,
  resolveSourceCollectionRunsQueryEnabled,
  resolveTeamCanvasQueryEnabled,
  resolveTeamDetailLoadMode,
} from "./teamDetailLoadPolicy";

describe("teamDetailLoadPolicy", () => {
  it("prefers light team detail for first paint", () => {
    expect(resolveTeamDetailLoadMode()).toBe("light");
    expect(resolveTeamDetailLoadMode({ sourceCollectionStandalone: false, researchWorkspaceView: "overview" })).toBe(
      "light",
    );
    expect(resolveTeamDetailLoadMode({ sourceCollectionStandalone: true })).toBe("light");
  });

  it("loads canvas only for active canvas surfaces", () => {
    expect(
      resolveTeamCanvasQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "overview",
        sourceCollectionStandalone: false,
      }),
    ).toBe(false);
    expect(
      resolveTeamCanvasQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "canvas",
        sourceCollectionStandalone: false,
      }),
    ).toBe(true);
    expect(
      resolveTeamCanvasQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: false,
        researchWorkspaceView: "overview",
        sourceCollectionStandalone: false,
      }),
    ).toBe(true);
    expect(
      resolveTeamCanvasQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: false,
        researchWorkspaceView: "overview",
        sourceCollectionStandalone: true,
      }),
    ).toBe(false);
  });

  it("gates source-collection runs and secondary research status queries", () => {
    expect(
      resolveSourceCollectionRunsQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).toBe(false);
    expect(
      resolveSourceCollectionRunsQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        sourceCollectionWorkspaceSelected: true,
      }),
    ).toBe(true);

    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "source_collection",
        sourceCollectionStandalone: false,
      }),
    ).toBe(false);
    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "experiment",
        sourceCollectionStandalone: false,
      }),
    ).toBe(true);
  });

  it("detects foreign team detail cache keys", () => {
    expect(isForeignTeamDetailQueryKey(["teams", "old", "detail", "light"], "new")).toBe(true);
    expect(isForeignTeamDetailQueryKey(["teams", "new", "detail", "light"], "new")).toBe(false);
    expect(isForeignTeamDetailQueryKey(["teams", "new", "canvas"], "new")).toBe(false);
  });
});
