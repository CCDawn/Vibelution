import { describe, expect, it } from "vitest";

import experimentApiSource from "../../api/teamExperiment.ts?raw";
import routeSource from "../TeamsRoute.tsx?raw";
import mutationsSource from "./useTeamExperimentLoopMutations.ts?raw";

const mutationOwners = [
  "createExperimentPlanMutation",
  "materializeEngineeringProxyHypothesisMutation",
  "reviewExperimentHypothesisMutation",
  "createExperimentHypothesisRevisionMutation",
  "freezeExperimentDesignMutation",
  "registerExperimentBaselineArtifactMutation",
  "runExperimentSmokeMutation",
  "registerExperimentSmokeResultMutation",
  "registerExperimentFullRunResultMutation",
  "requestExperimentKnowledgeIngestionMutation",
  "createResearchLoopMutation",
  "recordResearchLoopEvidenceMutation",
  "recordResearchLoopDecisionMutation",
  "materializeResearchLoopIterationDesignMutation",
] as const;

describe("team experiment loop mutations contract", () => {
  const reviewMutationSource = mutationsSource
    .split("const reviewExperimentHypothesisMutation = useMutation({")[1]
    ?.split("const createExperimentHypothesisRevisionMutation = useMutation({")[0] ?? "";

  it("owns the experiment + research-loop write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(mutationOwners.length);
    mutationOwners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
      expect(mutationsSource).toContain(`${owner},`);
    });
  });

  it("stays free of streaming, local UI state, and navigation", () => {
    expect(mutationsSource).not.toMatch(/\bnew EventSource\b/);
    expect(mutationsSource).not.toContain("useState");
    expect(mutationsSource).not.toContain("useEffect");
    expect(mutationsSource).not.toContain("useNavigate");
    expect(mutationsSource).not.toContain("react-router-dom");
  });

  it("is wired from TeamsRoute while Route no longer defines those mutations inline", () => {
    expect(routeSource).toContain("useTeamExperimentLoopMutations({");
    mutationOwners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("preserves key write endpoints used by experiment ledger and research loop", () => {
    expect(mutationsSource).toContain("/workflow-orchestration/experiments/plan");
    expect(mutationsSource).toContain("materializeTeamEngineeringProxyHypothesis(");
    expect(mutationsSource).toContain("reviewTeamExperimentHypothesis(");
    expect(mutationsSource).toContain("createTeamExperimentHypothesisRevision(");
    expect(experimentApiSource).toContain("/hypotheses/engineering-proxy");
    expect(experimentApiSource).toContain("/research/review/decide");
    expect(experimentApiSource).toContain("/hypotheses/${encodeURIComponent(candidateId)}/revision");
    expect(mutationsSource).toContain("/baseline-artifact");
    expect(mutationsSource).toContain("runTeamExperimentSmoke(");
    expect(mutationsSource).not.toContain("/smoke-run");
    expect(experimentApiSource).toContain("/smoke-run");
    expect(experimentApiSource).toContain("encodeURIComponent(teamId)");
    expect(experimentApiSource).toContain("encodeURIComponent(planId)");
    expect(experimentApiSource).toContain("JSON.stringify(request)");
    expect(experimentApiSource).toContain("recordedByAgent");
    expect(mutationsSource).toContain("/smoke-result");
    expect(mutationsSource).toContain("/full-run-result");
    expect(mutationsSource).toContain("/knowledge-ingestion-request");
    expect(mutationsSource).toContain("/workflow-orchestration/research-loop/loops");
    expect(mutationsSource).toContain("/evidence");
    expect(mutationsSource).toContain("/decision");
    expect(mutationsSource).toContain("/design-draft");
  });

  it("updates the experiment status cache from the authoritative review response", () => {
    expect(reviewMutationSource).toContain("if (payload.experimentStatus)");
    expect(reviewMutationSource).toContain(
      "queryClient.setQueryData(\n          experimentPlanningStatusQueryKey(variables.teamId),\n          payload.experimentStatus,",
    );
  });
});
