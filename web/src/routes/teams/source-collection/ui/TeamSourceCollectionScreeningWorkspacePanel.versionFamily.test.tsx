import { describe, expect, it } from "vitest";

import panelSource from "./TeamSourceCollectionScreeningWorkspacePanel.tsx?raw";
import teamsRouteShell from "../../TeamsRouteWorkbench.tsx?raw";
import teamsRouteModel from "../../useTeamsWorkbenchModel.tsx?raw";
import scCompositionSource from "../../useTeamsScComposition.ts?raw";
const teamsRouteSource = `${teamsRouteShell}\n${teamsRouteModel}\n${scCompositionSource}`;
import presentationCoreSource from "../../useSourceCollectionPresentationCore.ts?raw";
import presentationPipelineSource from "../../useSourceCollectionPresentationPipeline.ts?raw";
import presentationMidSource from "../../useSourceCollectionPresentationMid.ts?raw";
import presentationTailSource from "../../useSourceCollectionPresentationTail.ts?raw";
const presentationSource = `${presentationCoreSource}\n${presentationPipelineSource}\n${presentationMidSource}\n${presentationTailSource}`;
import listMetricsSource from "../deriveSourceCollectionListMetrics.ts?raw";

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
    // R2-l: reviewable candidate filtering lives in deriveSourceCollectionListMetrics.
    expect(presentationSource).toContain("sourceCollectionReviewableRunCandidates");
    expect(listMetricsSource).toContain('candidate.sourceVersionFamily?.state !== "superseded"');
    expect(listMetricsSource).toContain("sourceCollectionRunReviewableCandidateCount");
    // Pending screening uses reviewable-assessed gap when run candidates exist (display labels / metrics chain).
    expect(presentationSource).toContain("deriveSourceCollectionListMetrics");
    expect(listMetricsSource).not.toContain(
      "Math.max(0, sourceCollectionProjectedCandidateCount - sourceCollectionProjectedAssessedCount)",
    );
    expect(teamsRouteSource).toContain("useTeamsScComposition");
    expect(scCompositionSource).toContain("useSourceCollectionPresentation({");
  });
});
