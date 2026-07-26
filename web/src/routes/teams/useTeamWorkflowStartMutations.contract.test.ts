import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
import modelSource from "./workflowStartMutationModel.ts?raw";
import mutationsSource from "./useTeamWorkflowStartMutations.ts?raw";

const mutationOwners = [
  "seedSourceCollectionAgentSessionContextMutation",
  "startSourceCollectionStageSessionTaskMutation",
  "startAiSearchRunMutation",
  "startSourceCollectionRunMutation",
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
    expect(routeSource).toContain("useTeamWorkflowStartMutations({");
    expect(routeSource).toContain("workflowStartMutationModel");
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
    expect(mutationsSource).toContain("/workflow-orchestration/stage-rounds/start");
    expect(mutationsSource).toContain("idempotencyKey: payload.idempotencyKey");
  });
});
