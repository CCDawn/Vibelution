import { describe, expect, it } from "vitest";

import { resolveTeamWorkflowResourceDemand } from "./teamWorkflowResourceDemand";

describe("resolveTeamWorkflowResourceDemand", () => {
  it("enables candidate list on overview and SC workspace", () => {
    expect(resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "overview",
      sourceCollectionWorkspaceSelected: false,
      selectedSourceCollectionStageId: null,
    }).teamWorkflowCandidateListEnabled).toBe(true);

    expect(resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "iteration",
      sourceCollectionWorkspaceSelected: true,
      selectedSourceCollectionStageId: "finding",
    }).teamWorkflowCandidateListEnabled).toBe(true);
  });

  it("gates graph and quality to graph view or late SC stages", () => {
    const finding = resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "source_collection",
      sourceCollectionWorkspaceSelected: true,
      selectedSourceCollectionStageId: "finding",
    });
    expect(finding.teamWorkflowGraphEnabled).toBe(false);
    expect(finding.teamWorkflowSourceQualityEnabled).toBe(false);

    const relations = resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "source_collection",
      sourceCollectionWorkspaceSelected: true,
      selectedSourceCollectionStageId: "relations",
    });
    expect(relations.teamWorkflowGraphEnabled).toBe(true);
    expect(relations.teamWorkflowSourceQualityEnabled).toBe(true);
  });

  it("disables stage-round status while SC workspace is selected", () => {
    expect(resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "overview",
      sourceCollectionWorkspaceSelected: false,
      selectedSourceCollectionStageId: null,
    }).researchStageRoundStatusEnabled).toBe(true);

    expect(resolveTeamWorkflowResourceDemand({
      effectiveTeamId: "research-team",
      researchWorkflowTeamSelected: true,
      researchWorkspaceView: "knowledge_collection",
      sourceCollectionWorkspaceSelected: true,
      selectedSourceCollectionStageId: "ingestion",
    }).researchStageRoundStatusEnabled).toBe(false);
  });
});
