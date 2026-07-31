import { describe, expect, it } from "vitest";

import type { TeamWorkflowCandidate } from "../../../api/types";
import {
  compactSourceCollectionQuerySeeds,
  sourceCollectionCandidateQualityState,
  sourceCollectionCollectionModeLabel,
  sourceCollectionModeForTeam,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusLabel,
  sourceCollectionSimpleCandidateStatusPresentation,
  sourceCollectionStatusLabel,
  sourceCollectionStorageArtifactsForRun,
  splitDraftList,
} from "./presentationModel";

function candidate(partial: Partial<TeamWorkflowCandidate> & Pick<TeamWorkflowCandidate, "candidateId">): TeamWorkflowCandidate {
  return {
    candidateId: partial.candidateId,
    candidateType: partial.candidateType || "source_manifest",
    title: partial.title || partial.candidateId,
    currentState: partial.currentState || "",
    qualityStatus: partial.qualityStatus || "",
    metadata: partial.metadata || {},
  } as TeamWorkflowCandidate;
}

describe("source-collection presentationModel", () => {
  it("splits and compact seeds for source-collection drafts", () => {
    expect(splitDraftList("a, b；c\nd", 3)).toEqual(["a", "b", "c"]);
    expect(compactSourceCollectionQuerySeeds("主主题", "seed-a")).toEqual(["seed-a", "主主题"]);
  });

  it("labels run status and collection mode", () => {
    expect(sourceCollectionStatusLabel("waiting_for_writeback", "zh")).toContain("回写");
    expect(sourceCollectionCollectionModeLabel("mixed", "en")).toBe("Mixed");
  });

  it("forces web_search mode for non knowledge-expansion teams", () => {
    expect(
      sourceCollectionModeForTeam(
        { teamId: "research-team", teamKind: "research" } as never,
        {
          title: "",
          topic: "",
          goal: "",
          querySeeds: "",
          inputRefs: "",
          searchLanguages: "",
          sourceTypes: "",
          maxResultsPerQuery: 8,
          collectionMode: "mixed",
          localScanRoots: "",
        },
      ),
    ).toBe("web_search");
  });

  it("maps storage paths and candidate presentation tones", () => {
    const artifacts = sourceCollectionStorageArtifactsForRun("team-1", "run-1");
    expect(artifacts?.searchPlanPath).toContain("source_collection_runs/run-1/search_plan.json");
    expect(sourceCollectionResultTone("source_quality_approved")).toBe("ready");
    expect(sourceCollectionSimpleCandidateStatusLabel(
      candidate({ candidateId: "c1", qualityStatus: "approved", currentState: "source_screened" }),
      "zh",
    )).toBe("通过");
  });

  it("explains how to repair a source that needs revision", () => {
    const source = candidate({
      candidateId: "c-needs-evidence",
      qualityStatus: "source_quality_needs_revision",
      currentState: "source_needs_quality_revision",
      metadata: {
        metadataOnlyDownload: true,
        contentExtraction: {
          status: "extracted",
          summary: "",
          evidenceRefs: [],
          keyFindings: [],
        },
        sourceQualityAssessment: {
          decision: "needs_revision",
          requiredFixes: [],
          scores: {
            relevance: 82,
            reliability: 76,
            accessibility: 57,
            extractionReadiness: 58,
            overall: 68,
          },
        },
      },
    });
    const presentation = sourceCollectionSimpleCandidateStatusPresentation(source, "zh");

    expect(presentation.label).toBe("待补资料");
    expect(presentation.title).toContain("补充可核验的全文或公开摘要");
    expect(presentation.title).toContain("证据锚点");
    expect(presentation.title).toContain("重新运行资料质量审查");
    expect(sourceCollectionCandidateQualityState(source)).toEqual({
      assessed: true,
      approved: false,
      needsRevision: true,
    });
  });
});
