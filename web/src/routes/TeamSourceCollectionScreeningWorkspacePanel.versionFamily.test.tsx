import { describe, expect, it } from "vitest";

import panelSource from "./TeamSourceCollectionScreeningWorkspacePanel.tsx?raw";
import teamsRouteSource from "./TeamsRoute.tsx?raw";
import presentationSource from "./teams/useSourceCollectionPresentation.ts?raw";

describe("TeamSourceCollectionScreeningWorkspacePanel version family contract", () => {
  it("shows the version chain and prevents independent approval of superseded records", () => {
    expect(panelSource).toContain("sourceCollectionCandidateVersionFamily");
    expect(panelSource).toContain("versionFamily.chainLabel");
    expect(panelSource).toContain("versionFamily.evidenceLabel");
    expect(panelSource).toContain("sourceCollectionIndependentSourceCount");
    expect(panelSource).toContain("独立来源");
    expect(panelSource).toContain("versionFamily?.isSuperseded");
    expect(panelSource).toContain("versionFamily?.reviewDisabledReason");
  });

  it("keeps aggregate quality guidance in the single recovery summary panel", () => {
    expect(panelSource).not.toContain("actionItems.slice(0, 3)");
    expect(panelSource).not.toContain("statusItems={teamWorkflowSourceQualityStatus");
  });

  it("counts pending review from reviewable candidate state instead of extraction artifacts", () => {
    // Owned by useSourceCollectionPresentation after presentation extract.
    expect(presentationSource).toContain("sourceCollectionReviewableRunCandidates");
    expect(presentationSource).toContain('candidate.sourceVersionFamily?.state !== "superseded"');
    expect(presentationSource).toContain("sourceCollectionRunReviewableCandidateCount - sourceCollectionRunAssessedCount");
    expect(presentationSource).not.toContain(
      "Math.max(0, sourceCollectionProjectedCandidateCount - sourceCollectionProjectedAssessedCount)",
    );
    expect(teamsRouteSource).toContain("useSourceCollectionPresentation({");
  });
});
