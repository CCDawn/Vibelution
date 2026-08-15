import { describe, expect, it } from "vitest";

import apiSource from "./stageRounds.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";
import startMutationsSource from "../routes/teams/useTeamWorkflowStartMutations.ts?raw";

describe("stage-round API", () => {
  it("owns status and start transports", () => {
    expect(apiSource).toContain("export function fetchResearchStageRoundStatus");
    expect(apiSource).toContain("export function startResearchStageRound");
    expect(apiSource).toContain("/workflow-orchestration/stage-rounds/status");
    expect(apiSource).toContain("/workflow-orchestration/stage-rounds/start");
  });

  it("keeps resource and start hooks free of those paths", () => {
    expect(resourcesSource).toContain("fetchResearchStageRoundStatus<");
    expect(resourcesSource).not.toContain("/workflow-orchestration/stage-rounds/status");
    expect(startMutationsSource).toContain("startResearchStageRound<");
    expect(startMutationsSource).not.toContain("/workflow-orchestration/stage-rounds/start");
  });
});
