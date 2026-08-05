import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
import mutationBundleSource from "./useTeamsMutationBundle.ts?raw";
const routeSource = `${routeShellSource}\n${routeModelSource}\n${routeFoundationSource}\n${routeShellPhaseSource}\n${mutationBundleSource}`;
import modelSource from "./workflowStartMutationModel.ts?raw";
import mutationsSource from "./useTeamWorkflowStartMutations.ts?raw";

const mutationOwners = [
  "seedSourceCollectionAgentSessionContextMutation",
  "startSourceCollectionStageSessionTaskMutation",
  "startAiSearchRunMutation",
  "startSourceCollectionRunMutation",
  "resetResearchProjectSourceCollectionMutation",
  "startResearchStageRoundMutation",
] as const;

describe("team workflow start mutations contract", () => {
  it("owns the start/session write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(mutationOwners.length);
    mutationOwners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
      expect(mutationsSource).toContain(`${owner},`);
    });
  });

  it("stays free of streaming and local UI state hooks", () => {
    expect(mutationsSource).not.toMatch(/\bnew EventSource\b/);
    expect(mutationsSource).not.toContain("useState");
    expect(mutationsSource).not.toContain("useEffect");
  });

  it("is wired from TeamsRoute while Route no longer defines those mutations inline", () => {
    // R2-g: model → mutation bundle → workflow start mutations.
    expect(routeModelSource).toContain("useTeamsMutationBundle({");
    expect(mutationBundleSource).toContain("useTeamWorkflowStartMutations({");
    // Start payload model is owned by workflowStartMutationModel (imported by start mutations).
    expect(mutationsSource).toContain("workflowStartMutationModel");
    expect(routeSource).not.toMatch(/\bconst \w+Mutation = useMutation\(/);
    mutationOwners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("promotes ResearchStageRoundStartPayload out of TeamsRoute", () => {
    expect(modelSource).toContain("export type ResearchStageRoundStartPayload");
    expect(routeSource).not.toContain("type ResearchStageRoundStartPayload =");
  });

  it("preserves key start/session write endpoints", () => {
    expect(mutationsSource).toContain("/agent-session-context");
    expect(mutationsSource).toContain("/stage-session-tasks");
    expect(mutationsSource).toContain("/ai-search-runs");
    expect(mutationsSource).toContain("/workflow-orchestration/source-collection-runs");
    expect(mutationsSource).toContain("resetTeamResearchProjectSourceCollection(");
    expect(mutationsSource).toContain("/workflow-orchestration/stage-rounds/start");
    expect(mutationsSource).toContain("idempotencyKey: payload.idempotencyKey");
  });

  it("removes reset runs from the query cache before allowing a fresh source batch", () => {
    expect(mutationsSource).toContain("await queryClient.cancelQueries({");
    expect(mutationsSource).toContain("queryClient.setQueriesData<DataProcessingRunListPayload>(");
    expect(mutationsSource).toContain("!removedRunIds.has(run.runId)");
    expect(mutationsSource).toContain("await queryClient.invalidateQueries({");
  });

  it("derives the research-stage search domain from the active project draft", () => {
    expect(mutationsSource).toContain("domain: payload.draft.topic.trim()");
    expect(mutationsSource).not.toContain('domain: "neuroscience-inspired algorithm discovery"');
  });
});
