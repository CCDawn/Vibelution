import { describe, expect, it } from "vitest";

import type { TeamWorkflowCandidate } from "../../../api/types";
import {
  compactSourceCollectionQuerySeeds,
  sourceCollectionCollectionModeLabel,
  sourceCollectionModeForTeam,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusLabel,
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
});
