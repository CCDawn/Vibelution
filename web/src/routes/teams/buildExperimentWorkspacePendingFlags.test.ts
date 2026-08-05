import { describe, expect, it } from "vitest";

import { buildExperimentWorkspacePendingFlags } from "./buildExperimentWorkspacePendingFlags";

describe("buildExperimentWorkspacePendingFlags", () => {
  it("scopes pending flags to the active team id", () => {
    const flags = buildExperimentWorkspacePendingFlags({
      teamId: "research-team",
      createExperimentPlanMutation: { isPending: true, variables: { teamId: "research-team" } },
      materializeEngineeringProxyHypothesisMutation: { isPending: true, variables: { teamId: "other" } },
      completeScientificHypothesisFromDesignMutation: {
        isPending: true,
        variables: { teamId: "research-team", candidateId: "c-1" },
      },
      reviewExperimentHypothesisMutation: { isPending: false, variables: null },
      createExperimentHypothesisRevisionMutation: { isPending: false, variables: null },
      freezeExperimentDesignMutation: { isPending: false, variables: null },
      registerExperimentBaselineArtifactMutation: { isPending: false, variables: null },
      registerExperimentSmokeResultMutation: { isPending: false, variables: null },
      runExperimentSmokeMutation: { isPending: false, variables: null },
      registerExperimentFullRunResultMutation: { isPending: false, variables: null },
      requestExperimentKnowledgeIngestionMutation: { isPending: false, variables: null },
      createResearchLoopMutation: { isPending: false, variables: null },
      recordResearchLoopEvidenceMutation: { isPending: false, variables: null },
      recordResearchLoopDecisionMutation: { isPending: false, variables: null },
    });
    expect(flags.createExperimentPlanPending).toBe(true);
    expect(flags.materializeEngineeringProxyPending).toBe(false);
    expect(flags.completeScientificHypothesisCandidateId).toBe("c-1");
    expect(flags.reviewExperimentHypothesisCandidateId).toBe("");
  });
});
