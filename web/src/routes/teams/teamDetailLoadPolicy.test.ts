import { describe, expect, it } from "vitest";

import {
  isForeignTeamDetailQueryKey,
  resolveLinkedChatRoomQueryEnabled,
  resolveResearchProjectsQueryEnabled,
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

  it("loads research projects for the team-wide status chrome while gating source-collection runs", () => {
    expect(
      resolveResearchProjectsQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
      }),
    ).toBe(true);
    expect(
      resolveResearchProjectsQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: false,
      }),
    ).toBe(false);
    expect(
      resolveResearchProjectsQueryEnabled({
        effectiveTeamId: "",
        researchWorkflowTeamSelected: true,
      }),
    ).toBe(false);

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
        researchWorkspaceView: "overview",
        sourceCollectionStandalone: false,
        challengeProgramProgressVisible: false,
      }),
    ).toBe(false);
    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "source_collection",
        sourceCollectionStandalone: false,
        challengeProgramProgressVisible: true,
      }),
    ).toBe(false);
    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "experiment",
        sourceCollectionStandalone: false,
        challengeProgramProgressVisible: false,
      }),
    ).toBe(true);
    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "iteration",
        sourceCollectionStandalone: false,
        challengeProgramProgressVisible: false,
      }),
    ).toBe(true);
    expect(
      resolveResearchSecondaryStatusQueryEnabled({
        effectiveTeamId: "t1",
        researchWorkflowTeamSelected: true,
        researchWorkspaceView: "overview",
        sourceCollectionStandalone: false,
        challengeProgramProgressVisible: true,
      }),
    ).toBe(true);
  });

  it("loads linked-room detail only for visible communication surfaces", () => {
    const base = {
      linkedChatRoomId: "room-1",
      teamDetailReady: true,
      researchWorkflowTeamSelected: true,
      researchCanvasVisible: false,
      researchWorkspaceView: "overview" as const,
    };
    expect(resolveLinkedChatRoomQueryEnabled(base)).toBe(false);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, researchWorkspaceView: "source_collection" })).toBe(false);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, researchWorkspaceView: "discussion" })).toBe(true);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, researchCanvasVisible: true, researchWorkspaceView: "discussion" })).toBe(false);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, researchWorkflowTeamSelected: false })).toBe(true);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, teamDetailReady: false })).toBe(false);
    expect(resolveLinkedChatRoomQueryEnabled({ ...base, linkedChatRoomId: "" })).toBe(false);
  });

  it("detects foreign team detail cache keys", () => {
    expect(isForeignTeamDetailQueryKey(["teams", "old", "detail", "light"], "new")).toBe(true);
    expect(isForeignTeamDetailQueryKey(["teams", "new", "detail", "light"], "new")).toBe(false);
    expect(isForeignTeamDetailQueryKey(["teams", "new", "canvas"], "new")).toBe(false);
  });
});
